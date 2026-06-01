
import os, time, logging, threading, urllib.request, json
import numpy as np
import tensorflow as tf
import joblib
import warnings
warnings.filterwarnings("ignore")

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ipv4, tcp, udp
from ryu.lib import hub

LOG = logging.getLogger('sdn.lstm')

# Path ของไฟล์ Model
BASE        = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH  = os.path.join(BASE, '../ml/model/lstm_sdn_model.h5')
SCALER_PATH = os.path.join(BASE, '../ml/model/scaler.pkl')
LE_PATH     = os.path.join(BASE, '../ml/model/label_encoder.pkl')

BLOCK_THRESHOLD  = 0.90
# BLOCK_DURATION ถูกลบออก — block ถาวรจนกว่า Admin จะปลด
STATS_INTERVAL   = 2
DASH_URL         = 'http://localhost:5000'
WARMUP_SECONDS   = 60
MIN_PPS_CHECK    = 500
CONSECUTIVE_HITS = 2

LOCAL_PORT       = 0xfffffffe
WHITELIST_IPS    = set()
WHITELIST_PORTS  = set()

# Fallback กรณี Model โหลดไม่ได้
FALLBACK_PPS_THRESHOLD = 1000
FALLBACK_BPS_THRESHOLD = 1_000_000

# ─── Topology: host_id → (s1_port, mac, ip) ───
# h1=port1, h2=port2, h3=port3, h4=port4, h_server=port5
HOSTS = {
    1:   (1, '00:00:00:00:00:01', '10.0.0.1'),
    2:   (2, '00:00:00:00:00:02', '10.0.0.2'),
    3:   (3, '00:00:00:00:00:03', '10.0.0.3'),
    4:   (4, '00:00:00:00:00:04', '10.0.0.4'),
    100: (5, '00:00:00:00:00:64', '10.0.0.100'),  # web server
}

# เชื่อมต่อ Database และ Notifier
try:
    import sys
    sys.path.insert(0, os.path.join(BASE, '..'))
    import db_manager as db
    db.init_db()
    HAS_DB = True
    LOG.info("✅ Database connected successfully")
except Exception as e:
    HAS_DB = False
    LOG.error(f"❌ Database connection failed: {e} — จะไม่บันทึกข้อมูลลง DB")

try:
    from notifier import notify_attack, notify_unblock
    HAS_NOTIFY = True
except:
    HAS_NOTIFY = False

def _post(path, data):
    try:
        body = json.dumps(data).encode()
        req  = urllib.request.Request(
            DASH_URL + path, data=body,
            headers={'Content-Type': 'application/json'}, method='POST')
        urllib.request.urlopen(req, timeout=1)
    except:
        pass

def dash(path, data):
    threading.Thread(target=_post, args=(path, data), daemon=True).start()

class IntelligentController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.datapaths     = {}
        self.mac_to_port   = {}
        # ─── ACL: IP-based blocking แทน port-based ───
        self.blocked_ips   = {}   # {ip: {time, dpid, port, label}}
        self.prev_stats    = {}
        self.port_context  = {}
        self.port_ip_map   = {}   # port → last seen src IP
        self.alert_counts  = {}   # port → consecutive hit count
        self.startup_time  = time.time()

        self.active_model_id = None
        self._load_active_model()

        self.monitor_thread = hub.spawn(self._monitor_loop)
        self.unblock_thread = hub.spawn(self._unblock_loop)
        self.model_check_thread = hub.spawn(self._model_check_loop)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp = ev.msg.datapath
        ofp, parser = dp.ofproto, dp.ofproto_parser
        self.datapaths[dp.id] = dp

        # Default Rule: ส่ง Packet ที่ไม่รู้จักเข้า Controller
        self._add_flow(dp, 0, parser.OFPMatch(),
            [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)])

        if dp.id == 1:
            self._install_s1_static_flows(dp)

    # ─────────────────────────────────────────────────────────────────
    # Static Flow Installer
    # ─────────────────────────────────────────────────────────────────
    S1_MAC = None

    def _add_static(self, dp, priority, match_kwargs, actions):
        self._add_flow(dp, priority,
                       dp.ofproto_parser.OFPMatch(**match_kwargs), actions)

    def _out(self, dp, *ports):
        return [dp.ofproto_parser.OFPActionOutput(p) for p in ports]

    def _set_eth_dst(self, dp, mac):
        return dp.ofproto_parser.OFPActionSetField(eth_dst=mac)

    def _set_eth_src(self, dp, mac):
        return dp.ofproto_parser.OFPActionSetField(eth_src=mac)

    def _install_s1_static_flows(self, dp):
        ofp, parser = dp.ofproto, dp.ofproto_parser
        LOG.info("📡 Installing s1 static flows (ACL mode)...")

        # ── LOCAL port: LSTM monitoring ────────────────────────────────
        self._add_flow(dp, 8,
            parser.OFPMatch(in_port=LOCAL_PORT),
            [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER),
             parser.OFPActionOutput(ofp.OFPP_NORMAL)])

        # ── อ่าน s1 LOCAL MAC จาก OVS ─────────────────────────────────
        import subprocess, re
        try:
            out = subprocess.check_output(
                ['ovs-ofctl', '-O', 'OpenFlow13', 'show', 's1'],
                stderr=subprocess.DEVNULL).decode()
            m = re.search(r'LOCAL\(s1\).*?addr:([0-9a-f:]+)', out)
            s1_mac = m.group(1) if m else '00:00:00:00:00:fe'
        except Exception:
            s1_mac = '00:00:00:00:00:fe'
        IntelligentController.S1_MAC = s1_mac
        LOG.info(f"   s1 LOCAL MAC = {s1_mac}")

        ETH_ARP, ETH_IP = 0x0806, 0x0800

        # ── ARP: LOCAL → each host ─────────────────────────────────────
        for hid, (hport, _, hip) in HOSTS.items():
            self._add_static(dp, 200,
                {'eth_type': ETH_ARP, 'in_port': LOCAL_PORT,
                 'arp_tpa': hip},
                self._out(dp, hport))

        # ── ARP: hosts → LOCAL ─────────────────────────────────────────
        for hid, (hport, _, _) in HOSTS.items():
            self._add_static(dp, 200,
                {'eth_type': ETH_ARP, 'in_port': hport,
                 'arp_tpa': '10.0.0.254'},
                [parser.OFPActionOutput(ofp.OFPP_LOCAL)])

        # ── ARP: h→h ──────────────────────────────────────────────────
        for src_id, (src_port, _, _) in HOSTS.items():
            for dst_id, (dst_port, _, dst_ip) in HOSTS.items():
                if src_id == dst_id: continue
                self._add_static(dp, 200,
                    {'eth_type': ETH_ARP, 'in_port': src_port,
                     'arp_tpa': dst_ip},
                    self._out(dp, dst_port))

        # ── IP: LOCAL → hosts ──────────────────────────────────────────
        for hid, (hport, hmac, hip) in HOSTS.items():
            self._add_flow(dp, 200,
                parser.OFPMatch(eth_type=ETH_IP, in_port=LOCAL_PORT,
                                ipv4_dst=hip),
                [self._set_eth_src(dp, s1_mac),
                 self._set_eth_dst(dp, hmac),
                 parser.OFPActionOutput(hport)])

        # ── IP: hosts → LOCAL ──────────────────────────────────────────
        for hid, (hport, _, _) in HOSTS.items():
            self._add_static(dp, 200,
                {'eth_type': ETH_IP, 'in_port': hport,
                 'ipv4_dst': '10.0.0.254'},
                [parser.OFPActionOutput(ofp.OFPP_LOCAL)])
            self._add_static(dp, 200,
                {'eth_type': ETH_IP, 'in_port': hport,
                 'ipv4_dst': ('192.168.56.0', '255.255.255.0')},
                [parser.OFPActionOutput(ofp.OFPP_LOCAL)])

        # ── IP: h→h ───────────────────────────────────────────────────
        for src_id, (src_port, _, _) in HOSTS.items():
            for dst_id, (dst_port, dst_mac, dst_ip) in HOSTS.items():
                if src_id == dst_id: continue
                self._add_flow(dp, 200,
                    parser.OFPMatch(eth_type=ETH_IP, in_port=src_port,
                                    ipv4_dst=dst_ip),
                    [self._set_eth_dst(dp, dst_mac),
                     parser.OFPActionOutput(dst_port)])

        LOG.info("✅ s1 static flows installed (ARP + IP + h→h + LOCAL + WebServer)")

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if not eth: return

        # ดึงข้อมูล IP/Port เพื่อเป็น Context ให้ LSTM
        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        if ip_pkt:
            proto_num = ip_pkt.proto
            dst_p = 0
            t = pkt.get_protocol(tcp.tcp)
            u = pkt.get_protocol(udp.udp)
            if t: dst_p = t.dst_port
            elif u: dst_p = u.dst_port
            self.port_context[in_port] = {'dst_port': dst_p, 'proto': proto_num}
            self.port_ip_map[in_port] = ip_pkt.src

            # ─── ACL: เช็คว่า src IP ถูก block อยู่หรือไม่ ───
            if self._is_ip_blocked(ip_pkt.src):
                return

        # L2 Learning
        self.mac_to_port.setdefault(dp.id, {})
        self.mac_to_port[dp.id][eth.src] = in_port
        out_port = self.mac_to_port[dp.id].get(eth.dst, ofp.OFPP_FLOOD)
        
        actions = [parser.OFPActionOutput(out_port)]
        if out_port != ofp.OFPP_FLOOD:
            self._add_flow(dp, 1, parser.OFPMatch(in_port=in_port, eth_dst=eth.dst), actions)
        
        data = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
        dp.send_msg(parser.OFPPacketOut(datapath=dp, buffer_id=msg.buffer_id,
                                        in_port=in_port, actions=actions, data=data))

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        dpid = ev.msg.datapath.id
        now  = time.time()

        for stat in ev.msg.body:
            port = stat.port_no
            if port > 10 and port != LOCAL_PORT: continue

            key = (dpid, port)
            if key in self.prev_stats:
                prev = self.prev_stats[key]
                dt = now - prev['time']
                if dt <= 0: continue

                rx_pps = (stat.rx_packets - prev['rx_pkts']) / dt
                rx_bps = (stat.rx_bytes - prev['rx_bytes']) / dt
                tx_pps = (stat.tx_packets - prev['tx_pkts']) / dt
                tx_bps = (stat.tx_bytes - prev['tx_bytes']) / dt

                detect_pps = rx_pps
                detect_bps = rx_bps

                # ถ้า IP จาก port นี้ถูก block → แสดง 0
                src_ip = self.port_ip_map.get(port)
                is_blocked = src_ip and src_ip in self.blocked_ips
                display_pps = 0 if is_blocked else rx_pps
                display_bps = 0 if is_blocked else rx_bps

                display_port = 'kali' if port == LOCAL_PORT else port
                dash('/api/traffic', {
                    'port': display_port,
                    'pps': round(display_pps, 1),
                    'bps': round(display_bps / 1024, 1)
                })

                if HAS_DB and int(now) % 3 == 0 and port != LOCAL_PORT:
                    db.log_traffic(port, display_pps, display_bps / 1024)

                if (not is_blocked
                        and detect_pps > MIN_PPS_CHECK
                        and self._warmup_done()):
                    ctx = self.port_context.get(port, {'dst_port': 0, 'proto': 6})
                    self._lstm_check(
                        ev.msg.datapath, port, detect_pps, detect_bps, dt,
                        int(stat.rx_packets - prev['rx_pkts']), 
                        int(stat.rx_bytes - prev['rx_bytes']),
                        ctx['dst_port'], ctx['proto']
                    )
                elif not is_blocked:
                    self.alert_counts.pop(port, None)

            self.prev_stats[key] = {
                'time': now, 'rx_pkts': stat.rx_packets, 'rx_bytes': stat.rx_bytes,
                'tx_pkts': stat.tx_packets, 'tx_bytes': stat.tx_bytes
            }

    def _lstm_check(self, dp, port, pps, bps, duration, pkt_count, byte_count, dst_port, protocol):
        if not self.model:
            if pps > FALLBACK_PPS_THRESHOLD:
                self.alert_counts[port] = self.alert_counts.get(port, 0) + 1
                if self.alert_counts[port] >= CONSECUTIVE_HITS:
                    self._take_action(dp, port, 'DDoS-Fallback', 0.99, pps, bps)
            return

        try:
            duration_us = duration * 1_000_000
            iat_mean = (duration_us / max(pkt_count, 1))
            
            features = np.array([[
                dst_port, protocol, duration_us, pkt_count, 0, 
                byte_count, 0, bps, pps, iat_mean
            ]])

            scaled = self.scaler.transform(features)
            lstm_input = np.reshape(scaled, (1, 1, scaled.shape[1]))

            pred = self.model.predict(lstm_input, verbose=0)
            idx = np.argmax(pred[0])
            conf = float(pred[0][idx])
            label = self.le.inverse_transform([idx])[0]

            LOG.info(f"[LSTM] port={port} label='{label}' conf={conf:.4f} pps={pps:.1f} hits={self.alert_counts.get(port, 0)}")

            dash('/api/ml', {
                'port': port,
                'pred': label,
                'conf': conf
            })

            is_attack = (conf >= BLOCK_THRESHOLD and label.lower() != 'benign') or pps > 10000

            if is_attack:
                self.alert_counts[port] = self.alert_counts.get(port, 0) + 1
                LOG.info(f"[ALERT] port={port} consecutive hit #{self.alert_counts[port]}/{CONSECUTIVE_HITS}")

                if self.alert_counts[port] >= CONSECUTIVE_HITS:
                    if pps > 10000 and (conf < BLOCK_THRESHOLD or label.lower() == 'benign'):
                        LOG.warning(f"🚨 HARD LIMIT REACHED on port {port} (pps={pps})")
                        self._take_action(dp, port, 'DDoS-Anomaly', 0.99, pps, bps)
                    else:
                        self._take_action(dp, port, label, conf, pps, bps)
            else:
                self.alert_counts.pop(port, None)
                
        except Exception as e:
            LOG.error(f"Prediction Error: {e}")

    def _take_action(self, dp, port, label, conf, pps, bps):
        src_ip = self.port_ip_map.get(port)
        if not src_ip:
            LOG.warning(f"⚠️  Cannot block — no IP mapped for port {port}")
            return

        LOG.info(f"AI Prediction: {label} with confidence {conf}")

        # ─── ACL: block เฉพาะ IP ที่โจมตี ───
        if label.lower() == 'udplag':
            self._rate_limit_ip(dp, src_ip, port, conf)
        else:
            self._block_ip(dp, src_ip, port, conf, label)

        # บันทึกและแจ้งเตือน
        if HAS_NOTIFY: notify_attack(port, pps, conf)
        if HAS_DB:
            db.log_attack(port, pps, bps/1024, conf, note=f'{label} src={src_ip}',
                          attack_type=label, dpid=dp.id)
            db.block_ip(src_ip, conf)   # log IP-based block (ไม่มี duration)
        
        dash('/api/attack', {
            'port': port, 
            'ip': src_ip, 
            'label': label, 
            'conf': round(conf, 2),
            'pps': round(pps, 1)
        })
        self.alert_counts.pop(port, None)

    def _block_ip(self, dp, src_ip, port, conf, label=''):
        """─── ACL: Block เฉพาะ IP ที่โจมตี (ถาวรจนกว่า Admin จะปลด) ───"""
        parser = dp.ofproto_parser

        if src_ip in WHITELIST_IPS:
            LOG.warning(f"⚠️  SKIP block — IP {src_ip} is whitelisted")
            return

        if src_ip in self.blocked_ips:
            LOG.warning(f"⚠️  IP {src_ip} already blocked — skipping")
            return

        # Drop rule: match by src IP — permanent (ไม่มี timeout)
        match = parser.OFPMatch(eth_type=0x0800, ipv4_src=src_ip)
        self._add_flow(dp, 500, match, [])   # idle_timeout=0, hard_timeout=0 → ถาวร

        # Drop rule สำหรับ LOCAL port path ด้วย
        match_local = parser.OFPMatch(
            eth_type=0x0800, in_port=LOCAL_PORT, ipv4_src=src_ip)
        self._add_flow(dp, 501, match_local, [])   # ถาวรเช่นกัน

        self.blocked_ips[src_ip] = {
            'time': time.time(), 'dpid': dp.id,
            'port': port, 'label': label
        }
        LOG.warning(f"🚫 ACL BLOCK IP {src_ip} (from port {port}) | {label} {conf:.2%}")
        LOG.warning(f"   ⚠️  Block is PERMANENT — Admin must unblock manually")

    def _rate_limit_ip(self, dp, src_ip, port, conf):
        """─── ACL: Rate-limit เฉพาะ IP ───"""
        parser = dp.ofproto_parser
        match = parser.OFPMatch(eth_type=0x0800, ipv4_src=src_ip)
        actions = [parser.OFPActionSetQueue(1),
                   parser.OFPActionOutput(dp.ofproto.OFPP_FLOOD)]
        self._add_flow(dp, 490, match, actions)   # ถาวรจนกว่า Admin จะปลด
        self.blocked_ips[src_ip] = {
            'time': time.time(), 'dpid': dp.id,
            'port': port, 'label': 'UDPLag'
        }
        LOG.warning(f"🐌 ACL RATE-LIMIT IP {src_ip} (UDPLag) — permanent until admin unblocks")

    def _unblock_ip(self, src_ip, reason='expired'):
        """─── ACL: Unblock IP ───"""
        if src_ip not in self.blocked_ips: return
        info = self.blocked_ips[src_ip]
        dp = self.datapaths.get(info['dpid'])
        port = info.get('port', 0)

        if dp:
            ofp, parser = dp.ofproto, dp.ofproto_parser
            # ลบ drop rules ทั้งหมดของ IP นี้
            for match, pri in [
                (parser.OFPMatch(eth_type=0x0800, ipv4_src=src_ip), 500),
                (parser.OFPMatch(eth_type=0x0800, in_port=LOCAL_PORT, ipv4_src=src_ip), 501),
                (parser.OFPMatch(eth_type=0x0800, ipv4_src=src_ip), 490),
            ]:
                dp.send_msg(parser.OFPFlowMod(dp,
                    command=ofp.OFPFC_DELETE,
                    out_port=ofp.OFPP_ANY, out_group=ofp.OFPG_ANY,
                    match=match, priority=pri))

        del self.blocked_ips[src_ip]
        self.alert_counts.pop(port, None)
        if HAS_DB: db.unblock_port(port, reason)
        if HAS_NOTIFY: notify_unblock(port, reason)
        dash('/api/unblock', {'port': port, 'ip': src_ip})
        LOG.info(f"✅ ACL Unblocked IP {src_ip} (port {port}, {reason})")

    def _is_ip_blocked(self, src_ip):
        """เช็คว่า IP ถูก block อยู่หรือไม่ — block ถาวร ไม่มีการ unblock อัตโนมัติ"""
        return src_ip in self.blocked_ips

    def _warmup_done(self):
        return (time.time() - self.startup_time) >= WARMUP_SECONDS

    def _load_active_model(self):
        m_path = MODEL_PATH
        s_path = SCALER_PATH
        l_path = LE_PATH

        if HAS_DB:
            try:
                active_model = db.get_active_model()
                if active_model:
                    m_path = active_model.get('file_path', m_path)
                    s_path = active_model.get('scaler_path', s_path)
                    l_path = active_model.get('le_path', l_path)
                    self.active_model_id = active_model.get('id')
            except Exception as e:
                LOG.error(f"❌ Failed to fetch active model from DB: {e}")

        try:
            self.model  = tf.keras.models.load_model(m_path)
            self.scaler = joblib.load(s_path) if s_path else None
            self.le     = joblib.load(l_path) if l_path else None
            LOG.info(f"✅ LSTM Model & Scaler loaded successfully (Model ID: {self.active_model_id})")
        except Exception as e:
            self.model = self.scaler = self.le = None
            LOG.error(f"❌ Model Load Error: {e}")

    def _model_check_loop(self):
        while True:
            if HAS_DB:
                try:
                    active_model = db.get_active_model()
                    if active_model:
                        new_id = active_model.get('id')
                        if new_id != self.active_model_id:
                            LOG.info(f"🔄 Active model changed in DB from {self.active_model_id} to {new_id}. Reloading model...")
                            self._load_active_model()
                except Exception as e:
                    pass
            hub.sleep(10)

    def _monitor_loop(self):
        while True:
            for dp in self.datapaths.values():
                dp.send_msg(dp.ofproto_parser.OFPPortStatsRequest(dp, 0, dp.ofproto.OFPP_ANY))
            hub.sleep(STATS_INTERVAL)

    def _unblock_loop(self):
        """Loop นี้คงไว้เพื่อ backward compat — ไม่ทำอะไรเพราะ block เป็นแบบถาวร
        การ unblock ต้องทำผ่าน Admin API เท่านั้น (POST /api/unblock)"""
        while True:
            hub.sleep(60)   # sleep นาน ไม่ต้องทำอะไร

    # ─────────────────────────────────────────────────────────────────
    # Admin API: ปลด block โดย Admin เท่านั้น
    # เรียกจาก Dashboard: POST /api/unblock  {"ip": "x.x.x.x"}
    # ─────────────────────────────────────────────────────────────────
    def admin_unblock_ip(self, src_ip):
        """ปลด block IP — เรียกจาก Dashboard/Admin เท่านั้น"""
        if src_ip not in self.blocked_ips:
            LOG.warning(f"⚠️  Admin unblock: IP {src_ip} not in blocked list")
            return False
        self._unblock_ip(src_ip, reason='admin')
        return True

    def admin_list_blocked(self):
        """รายการ IP ที่ถูก block ทั้งหมด"""
        result = []
        for ip, info in self.blocked_ips.items():
            result.append({
                'ip': ip,
                'port': info.get('port'),
                'label': info.get('label'),
                'blocked_at': time.strftime('%Y-%m-%d %H:%M:%S',
                              time.localtime(info['time']))
            })
        return result

    def _add_flow(self, dp, priority, match, actions, idle_timeout=0, hard_timeout=0):
        ofp, parser = dp.ofproto, dp.ofproto_parser
        inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        dp.send_msg(parser.OFPFlowMod(datapath=dp, priority=priority, match=match,
                                      instructions=inst, idle_timeout=idle_timeout,
                                      hard_timeout=hard_timeout))
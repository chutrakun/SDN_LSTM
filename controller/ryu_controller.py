
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

BLOCK_THRESHOLD  = 0.90          # Fix #2: เพิ่มจาก 0.75 → ลด false positive
BLOCK_DURATION   = 60
STATS_INTERVAL   = 2
DASH_URL         = 'http://localhost:5000'
WARMUP_SECONDS   = 60            # Fix #3: ไม่ตรวจช่วง STP convergence
MIN_PPS_CHECK    = 500           # Fix #2: เพิ่มจาก 100 → กัน traffic ต่ำ
CONSECUTIVE_HITS = 2             # Fix #5: ต้อง detect ต่อเนื่อง 3 รอบก่อน block

LOCAL_PORT       = 5    # Fix #6: OVS LOCAL port (แทน port 5 ที่หายไป)
WHITELIST_IPS    = {
    '192.168.56.1',               # Ubuntu gateway เท่านั้น (ถอด Kali ออก → ให้ detect+block ได้)
}
WHITELIST_PORTS  = set()          # Fix #6: ไม่ whitelist port ใดๆ (port 5 ไม่มีแล้ว)


# Fallback กรณี Model โหลดไม่ได้
FALLBACK_PPS_THRESHOLD = 1000
FALLBACK_BPS_THRESHOLD = 1_000_000

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
        self.blocked_ports = {}
        self.prev_stats    = {}
        self.port_context  = {} # เก็บ L4 Context (Port/Proto)
        self.port_ip_map   = {} # Fix #4: เก็บ IP ล่าสุดของแต่ละ port
        self.alert_counts  = {} # Fix #5: นับ detection ต่อเนื่อง (sliding window)
        self.startup_time  = time.time()  # Fix #3: เวลาเริ่มระบบ (warmup)

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
    # Static Flow Installer — topology จริง (network_topology.py):
    #   s1 switch เดียว:
    #     port1=h1, port2=h2, port3=h3, port4=h4, LOCAL=10.0.0.254
    #   host MACs (autoSetMacs=True):
    #     h1=00:00:00:00:00:01 … h4=00:00:00:00:00:04
    # ─────────────────────────────────────────────────────────────────
    S1_MAC = None

    def _add_static(self, dp, priority, match_kwargs, actions):
        """Shortcut: add permanent flow (no timeout)"""
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
        LOG.info("📡 Installing s1 static flows...")

        # ── LOCAL port: LSTM monitoring ────────────────────────────────
        # priority=8 — packet ที่ไม่ตรง static flow (200) จะขึ้น controller
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

        # host_id → (s1_port, mac)
        # autoSetMacs: h1=port1=MAC:01, h2=port2=MAC:02, ...
        HOSTS = {
            1: (1, '00:00:00:00:00:01'),
            2: (2, '00:00:00:00:00:02'),
            3: (3, '00:00:00:00:00:03'),
            4: (4, '00:00:00:00:00:04'),
        }
        ETH_ARP, ETH_IP = 0x0806, 0x0800

        # ── ARP: LOCAL → each host ─────────────────────────────────────
        for hid, (hport, _) in HOSTS.items():
            self._add_static(dp, 200,
                {'eth_type': ETH_ARP, 'in_port': LOCAL_PORT,
                 'arp_tpa': f'10.0.0.{hid}'},
                self._out(dp, hport))

        # ── ARP: hosts → LOCAL ─────────────────────────────────────────
        for hid, (hport, _) in HOSTS.items():
            self._add_static(dp, 200,
                {'eth_type': ETH_ARP, 'in_port': hport,
                 'arp_tpa': '10.0.0.254'},
                [parser.OFPActionOutput(ofp.OFPP_LOCAL)])

        # ── ARP: h→h ──────────────────────────────────────────────────
        for src_id, (src_port, _) in HOSTS.items():
            for dst_id, (dst_port, _) in HOSTS.items():
                if src_id == dst_id: continue
                self._add_static(dp, 200,
                    {'eth_type': ETH_ARP, 'in_port': src_port,
                     'arp_tpa': f'10.0.0.{dst_id}'},
                    self._out(dp, dst_port))

        # ── IP: LOCAL → hosts ──────────────────────────────────────────
        for hid, (hport, hmac) in HOSTS.items():
            self._add_flow(dp, 200,
                parser.OFPMatch(eth_type=ETH_IP, in_port=LOCAL_PORT,
                                ipv4_dst=f'10.0.0.{hid}'),
                [self._set_eth_src(dp, s1_mac),
                 self._set_eth_dst(dp, hmac),
                 parser.OFPActionOutput(hport)])

        # ── IP: hosts → LOCAL ──────────────────────────────────────────
        for hid, (hport, _) in HOSTS.items():
            self._add_static(dp, 200,
                {'eth_type': ETH_IP, 'in_port': hport,
                 'ipv4_dst': '10.0.0.254'},
                [parser.OFPActionOutput(ofp.OFPP_LOCAL)])
            self._add_static(dp, 200,
                {'eth_type': ETH_IP, 'in_port': hport,
                 'ipv4_dst': ('192.168.56.0', '255.255.255.0')},
                [parser.OFPActionOutput(ofp.OFPP_LOCAL)])

        # ── IP: h→h ───────────────────────────────────────────────────
        for src_id, (src_port, _) in HOSTS.items():
            for dst_id, (dst_port, dst_mac) in HOSTS.items():
                if src_id == dst_id: continue
                self._add_flow(dp, 200,
                    parser.OFPMatch(eth_type=ETH_IP, in_port=src_port,
                                    ipv4_dst=f'10.0.0.{dst_id}'),
                    [self._set_eth_dst(dp, dst_mac),
                     parser.OFPActionOutput(dst_port)])

        LOG.info("✅ s1 static flows installed (ARP + IP + h→h + LOCAL)")
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
            # บันทึก Context
            self.port_context[in_port] = {'dst_port': dst_p, 'proto': proto_num}
            # Fix #4: บันทึก IP → Port mapping สำหรับ block by IP
            self.port_ip_map[in_port] = ip_pkt.src

        if self._is_blocked(in_port): return

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
            # Fix #6: รับ LOCAL port (0xfffffffe) ด้วย เพื่อ monitor traffic จาก Kali
            if port > 10 and port != LOCAL_PORT: continue

            key = (dpid, port)
            if key in self.prev_stats:
                prev = self.prev_stats[key]
                dt = now - prev['time']
                if dt <= 0: continue

                # คำนวณ Rate
                rx_pps = (stat.rx_packets - prev['rx_pkts']) / dt
                rx_bps = (stat.rx_bytes - prev['rx_bytes']) / dt
                tx_pps = (stat.tx_packets - prev['tx_pkts']) / dt
                tx_bps = (stat.tx_bytes - prev['tx_bytes']) / dt

                # ── Fix #1: ตรวจเฉพาะ rx (ขาเข้า) เพื่อไม่ให้ victim ถูก flag ──
                detect_pps = rx_pps
                detect_bps = rx_bps

                # ถ้าพอร์ตถูกบล็อกอยู่ ให้แสดงผลกราฟเป็น 0 เพื่อให้เห็นชัดเจนว่าส่งข้อมูลไม่ผ่าน
                display_pps = 0 if self._is_blocked(port) else rx_pps
                display_bps = 0 if self._is_blocked(port) else rx_bps

                # --- ส่วนที่ส่งข้อมูลไปหน้าเว็บ ---
                # Fix #6B: LOCAL port (0xfffffffe) → แสดงเป็น 'kali' บน Dashboard
                #          และ skip DB เพราะค่า port เกิน PostgreSQL INTEGER range
                display_port = 'kali' if port == LOCAL_PORT else port
                dash('/api/traffic', {
                    'port': display_port,
                    'pps': round(display_pps, 1),
                    'bps': round(display_bps / 1024, 1) # หน่วย KB
                })

                if HAS_DB and int(now) % 3 == 0 and port != LOCAL_PORT:
                    db.log_traffic(port, display_pps, display_bps / 1024)
                # ------------------------------------

                # ── Fix #2+#3: เพิ่ม threshold + warmup period ──
                if (not self._is_blocked(port)
                        and detect_pps > MIN_PPS_CHECK
                        and self._warmup_done()):
                    ctx = self.port_context.get(port, {'dst_port': 0, 'proto': 6})
                    self._lstm_check(
                        ev.msg.datapath, port, detect_pps, detect_bps, dt,
                        int(stat.rx_packets - prev['rx_pkts']), 
                        int(stat.rx_bytes - prev['rx_bytes']),
                        ctx['dst_port'], ctx['proto']
                    )
                elif not self._is_blocked(port):
                    # ── Fix #5: reset sliding window ถ้า traffic ต่ำกว่า threshold ──
                    self.alert_counts.pop(port, None)

            self.prev_stats[key] = {
                'time': now, 'rx_pkts': stat.rx_packets, 'rx_bytes': stat.rx_bytes,
                'tx_pkts': stat.tx_packets, 'tx_bytes': stat.tx_bytes
            }

    def _lstm_check(self, dp, port, pps, bps, duration, pkt_count, byte_count, dst_port, protocol):
        if not self.model:
            if pps > FALLBACK_PPS_THRESHOLD:
                # Fix #5: Fallback ใช้ sliding window เช่นกัน
                self.alert_counts[port] = self.alert_counts.get(port, 0) + 1
                if self.alert_counts[port] >= CONSECUTIVE_HITS:
                    self._take_action(dp, port, 'DDoS-Fallback', 0.99, pps, bps)
            return

        try:
            duration_us = duration * 1_000_000
            iat_mean = (duration_us / max(pkt_count, 1))
            
            # เรียง Features ตามที่ Model ถูก Train มา
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

            # ส่ง ML stat ไปยัง Dashboard ทุกรอบที่คำนวณ
            dash('/api/ml', {
                'port': port,
                'pred': label,
                'conf': conf
            })

            # ── Fix #5: Sliding window — ต้อง detect ต่อเนื่อง N รอบก่อน block ──
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
                # Benign → reset counter
                self.alert_counts.pop(port, None)
                
        except Exception as e:
            LOG.error(f"Prediction Error: {e}")

    def _take_action(self, dp, port, label, conf, pps, bps):
        LOG.info(f"AI Prediction: {label} with confidence {conf}")
        if label.lower() == 'udplag':
            self._rate_limit_port(dp, port, conf)
        else:
            self._block_port(dp, port, conf)

        # บันทึกและแจ้งเตือน
        if HAS_NOTIFY: notify_attack(port, pps, conf)
        if HAS_DB:
            db.log_attack(port, pps, bps/1024, conf, note=label,
                          attack_type=label, dpid=dp.id)
            db.block_port(port, conf, BLOCK_DURATION)
        
        # ส่งสถานะการโจมตีไปหน้า Dashboard
        src_ip = self.port_ip_map.get(port, f'port-{port}')
        dash('/api/attack', {
            'port': port, 
            'ip': src_ip, 
            'label': label, 
            'conf': round(conf, 2),
            'pps': round(pps, 1)
        })
        # Reset counter หลัง block สำเร็จ
        self.alert_counts.pop(port, None)

    def _block_port(self, dp, port, conf):
        parser = dp.ofproto_parser
        src_ip = self.port_ip_map.get(port)

        # Whitelist check
        if port in WHITELIST_PORTS:
            LOG.warning(f"⚠️  SKIP block — port {port} is whitelisted")
            return
        if src_ip and src_ip in WHITELIST_IPS:
            LOG.warning(f"⚠️  SKIP block — IP {src_ip} is whitelisted")
            return

        if src_ip:
            # Fix #6: block by src IP — ครอบคลุม Kali ที่เข้าผ่าน LOCAL port ด้วย
            match_normal = parser.OFPMatch(eth_type=0x0800, ipv4_src=src_ip)
            match_local  = parser.OFPMatch(
                eth_type=0x0800,
                in_port=LOCAL_PORT,
                ipv4_src=src_ip
            )
            LOG.warning(f"🚫 BLOCK IP {src_ip} (port {port}) | Attack: {conf:.2%}")
            # drop บน normal path
            self._add_flow(dp, 100, match_normal, [],
                           idle_timeout=BLOCK_DURATION, hard_timeout=BLOCK_DURATION)
            # drop บน LOCAL port path (Kali → Ubuntu → Mininet)
            self._add_flow(dp, 101, match_local, [],
                           idle_timeout=BLOCK_DURATION, hard_timeout=BLOCK_DURATION)
        else:
            match = parser.OFPMatch(in_port=port)
            LOG.warning(f"🚫 BLOCK port {port} (no IP mapped) | Attack: {conf:.2%}")
            self._add_flow(dp, 100, match, [],
                           idle_timeout=BLOCK_DURATION, hard_timeout=BLOCK_DURATION)

        self.blocked_ports[port] = {'time': time.time(), 'dpid': dp.id, 'ip': src_ip}

    def _rate_limit_port(self, dp, port, conf):
        """── Fix #4: Rate-limit by IP ──"""
        parser = dp.ofproto_parser
        src_ip = self.port_ip_map.get(port)
        if src_ip:
            match = parser.OFPMatch(eth_type=0x0800, ipv4_src=src_ip)
        else:
            match = parser.OFPMatch(in_port=port)
        actions = [parser.OFPActionSetQueue(1), parser.OFPActionOutput(dp.ofproto.OFPP_FLOOD)]
        self._add_flow(dp, 90, match, actions, idle_timeout=BLOCK_DURATION, hard_timeout=BLOCK_DURATION)
        self.blocked_ports[port] = {'time': time.time(), 'dpid': dp.id, 'ip': src_ip}
        LOG.warning(f"🐌 RATE-LIMIT {'IP ' + src_ip if src_ip else 'port ' + str(port)} (UDPLag)")

    def _unblock_port(self, port, reason='expired'):
        if port not in self.blocked_ports: return
        info = self.blocked_ports[port]
        dp = self.datapaths.get(info['dpid'])
        if dp:
            ofp, parser = dp.ofproto, dp.ofproto_parser
            src_ip = info.get('ip')
            if src_ip:
                # Fix #6: ลบทั้ง normal block และ LOCAL port block
                for match, pri in [
                    (parser.OFPMatch(eth_type=0x0800, ipv4_src=src_ip), 100),
                    (parser.OFPMatch(eth_type=0x0800, in_port=LOCAL_PORT, ipv4_src=src_ip), 101),
                ]:
                    dp.send_msg(parser.OFPFlowMod(dp,
                        command=ofp.OFPFC_DELETE,
                        out_port=ofp.OFPP_ANY, out_group=ofp.OFPG_ANY,
                        match=match, priority=pri))
            else:
                match = parser.OFPMatch(in_port=port)
                for p in [100, 90]:
                    dp.send_msg(parser.OFPFlowMod(dp,
                        command=ofp.OFPFC_DELETE,
                        out_port=ofp.OFPP_ANY, out_group=ofp.OFPG_ANY,
                        match=match, priority=p))

        del self.blocked_ports[port]
        self.alert_counts.pop(port, None)
        if HAS_DB: db.unblock_port(port, reason)
        if HAS_NOTIFY: notify_unblock(port, reason)
        dash('/api/unblock', {'port': port})
        LOG.info(f"✅ Unblocked port {port} ({reason})")

    def _is_blocked(self, port):
        if port in self.blocked_ports:
            if time.time() - self.blocked_ports[port]['time'] >= BLOCK_DURATION:
                self._unblock_port(port)
                return False
            return True
        return False

    def _warmup_done(self):
        """Fix #3: ไม่ตรวจจับในช่วง warmup (รอ STP converge)"""
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
        while True:
            for port in list(self.blocked_ports):
                self._is_blocked(port)
            hub.sleep(5)

    def _add_flow(self, dp, priority, match, actions, idle_timeout=0, hard_timeout=0):
        ofp, parser = dp.ofproto, dp.ofproto_parser
        inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        dp.send_msg(parser.OFPFlowMod(datapath=dp, priority=priority, match=match,
                                      instructions=inst, idle_timeout=idle_timeout,
                                      hard_timeout=hard_timeout))
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

BLOCK_THRESHOLD  = 0.75
BLOCK_DURATION   = 60
STATS_INTERVAL   = 2
DASH_URL         = 'http://localhost:5000'
LOCAL_PORT       = 0xfffffffe  # OVS LOCAL port

# อ่าน topology type จาก env var (set โดย dashboard_api.py ตอน restart Mininet)
TOPO_TYPE = os.environ.get('TOPO_TYPE', 'default')

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
except:
    HAS_DB = False

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

        # โหลด LSTM Model
        try:
            self.model  = tf.keras.models.load_model(MODEL_PATH)
            self.scaler = joblib.load(SCALER_PATH)
            self.le     = joblib.load(LE_PATH)
            LOG.info("✅ LSTM Model & Scaler loaded successfully")
        except Exception as e:
            self.model = self.scaler = self.le = None
            LOG.error(f"❌ Model Load Error: {e}")

        self.monitor_thread = hub.spawn(self._monitor_loop)
        self.unblock_thread = hub.spawn(self._unblock_loop)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp = ev.msg.datapath
        ofp, parser = dp.ofproto, dp.ofproto_parser
        self.datapaths[dp.id] = dp

        # table-miss: ส่ง packet ที่ไม่รู้จักขึ้น controller
        self._add_flow(dp, 0, parser.OFPMatch(),
            [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)])

        # install static flows ตาม topology
        topo = TOPO_TYPE
        LOG.info(f"[Switch] dpid={dp.id} connected, topo={topo}")
        if topo == 'tree':
            self._install_tree(dp)
        elif topo == 'mesh':
            self._install_mesh(dp)
        else:
            self._install_default(dp)

    # ─────────────────────────────────────────────────────────────────────
    # Helper methods สำหรับ static flows
    # ─────────────────────────────────────────────────────────────────────
    def _add_static(self, dp, priority, match_kwargs, actions):
        self._add_flow(dp, priority,
                       dp.ofproto_parser.OFPMatch(**match_kwargs), actions)

    def _out(self, dp, *ports):
        return [dp.ofproto_parser.OFPActionOutput(p) for p in ports]

    def _set_dst(self, dp, mac):
        return dp.ofproto_parser.OFPActionSetField(eth_dst=mac)

    def _set_src(self, dp, mac):
        return dp.ofproto_parser.OFPActionSetField(eth_src=mac)

    def _get_s1_mac(self):
        """อ่าน MAC จริงของ s1 LOCAL จาก OVS"""
        import subprocess, re
        try:
            out = subprocess.check_output(
                ['ovs-ofctl', '-O', 'OpenFlow13', 'show', 's1'],
                stderr=subprocess.DEVNULL).decode()
            m = re.search(r'LOCAL\(s1\).*?addr:([0-9a-f:]+)', out)
            return m.group(1) if m else '00:00:00:00:00:fe'
        except Exception:
            return '00:00:00:00:00:fe'

    def _install_local_monitoring(self, dp):
        """LOCAL port monitoring สำหรับ LSTM — ทุก topology"""
        ofp, parser = dp.ofproto, dp.ofproto_parser
        # priority=8: สูงกว่า table-miss(0) ต่ำกว่า static flows(200)
        # packet ที่ไม่ตรง static flow จะขึ้น controller ให้ LSTM เห็น
        self._add_flow(dp, 8,
            parser.OFPMatch(in_port=LOCAL_PORT),
            [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER),
             parser.OFPActionOutput(ofp.OFPP_NORMAL)])

    # ─────────────────────────────────────────────────────────────────────
    # DEFAULT topology: s1 switch เดียว, h1=port1, h2=port2, h3=port3, h4=port4
    # autoSetMacs → MAC = 00:00:00:00:00:0X
    # ─────────────────────────────────────────────────────────────────────
    def _install_default(self, dp):
        if dp.id != 1:
            return
        ofp, parser = dp.ofproto, dp.ofproto_parser
        LOG.info("📡 Installing DEFAULT topology flows on s1...")
        self._install_local_monitoring(dp)

        s1_mac = self._get_s1_mac()
        LOG.info(f"   s1 LOCAL MAC = {s1_mac}")

        ETH_ARP, ETH_IP = 0x0806, 0x0800
        # host_id → (port, mac)
        HOSTS = {
            1: (1, '00:00:00:00:00:01'),
            2: (2, '00:00:00:00:00:02'),
            3: (3, '00:00:00:00:00:03'),
            4: (4, '00:00:00:00:00:04'),
        }

        for hid, (hport, hmac) in HOSTS.items():
            # ARP: LOCAL → host
            self._add_static(dp, 200,
                {'eth_type': ETH_ARP, 'in_port': LOCAL_PORT,
                 'arp_tpa': f'10.0.0.{hid}'},
                self._out(dp, hport))
            # ARP: host → LOCAL
            self._add_static(dp, 200,
                {'eth_type': ETH_ARP, 'in_port': hport,
                 'arp_tpa': '10.0.0.254'},
                [parser.OFPActionOutput(ofp.OFPP_LOCAL)])
            # IP: LOCAL → host (rewrite eth header)
            self._add_flow(dp, 200,
                parser.OFPMatch(eth_type=ETH_IP, in_port=LOCAL_PORT,
                                ipv4_dst=f'10.0.0.{hid}'),
                [self._set_src(dp, s1_mac), self._set_dst(dp, hmac),
                 parser.OFPActionOutput(hport)])
            # IP: host → LOCAL
            self._add_static(dp, 200,
                {'eth_type': ETH_IP, 'in_port': hport,
                 'ipv4_dst': '10.0.0.254'},
                [parser.OFPActionOutput(ofp.OFPP_LOCAL)])
            self._add_static(dp, 200,
                {'eth_type': ETH_IP, 'in_port': hport,
                 'ipv4_dst': ('192.168.56.0', '255.255.255.0')},
                [parser.OFPActionOutput(ofp.OFPP_LOCAL)])

        # h→h ARP + IP
        for sid, (sport, _) in HOSTS.items():
            for did, (dport, dmac) in HOSTS.items():
                if sid == did:
                    continue
                self._add_static(dp, 200,
                    {'eth_type': ETH_ARP, 'in_port': sport,
                     'arp_tpa': f'10.0.0.{did}'},
                    self._out(dp, dport))
                self._add_flow(dp, 200,
                    parser.OFPMatch(eth_type=ETH_IP, in_port=sport,
                                    ipv4_dst=f'10.0.0.{did}'),
                    [self._set_dst(dp, dmac), parser.OFPActionOutput(dport)])

        LOG.info("✅ DEFAULT flows installed (s1: h1-h4 direct + LOCAL)")

    # ─────────────────────────────────────────────────────────────────────
    # TREE topology:
    #   s1 (core): port1=s2, port2=s3, LOCAL
    #   s2: port1=s1, port2=h1, port3=h2
    #   s3: port1=s1, port2=h3, port3=h4
    # ─────────────────────────────────────────────────────────────────────
    def _install_tree(self, dp):
        ofp, parser = dp.ofproto, dp.ofproto_parser
        ETH_ARP, ETH_IP = 0x0806, 0x0800

        if dp.id == 1:
            LOG.info("📡 Installing TREE flows on s1 (core)...")
            self._install_local_monitoring(dp)
            s1_mac = self._get_s1_mac()

            # s1 port mapping: port1=s2 side, port2=s3 side
            # h1,h2 → port1(s2); h3,h4 → port2(s3)
            HOST_PORT = {1: 1, 2: 1, 3: 2, 4: 2}
            HOSTS = {
                1: '00:00:00:00:00:01', 2: '00:00:00:00:00:02',
                3: '00:00:00:00:00:03', 4: '00:00:00:00:00:04',
            }

            for hid, hport in HOST_PORT.items():
                hmac = HOSTS[hid]
                self._add_static(dp, 200,
                    {'eth_type': ETH_ARP, 'in_port': LOCAL_PORT,
                     'arp_tpa': f'10.0.0.{hid}'},
                    self._out(dp, hport))
                self._add_static(dp, 200,
                    {'eth_type': ETH_ARP, 'in_port': hport,
                     'arp_tpa': '10.0.0.254'},
                    [parser.OFPActionOutput(ofp.OFPP_LOCAL)])
                self._add_flow(dp, 200,
                    parser.OFPMatch(eth_type=ETH_IP, in_port=LOCAL_PORT,
                                    ipv4_dst=f'10.0.0.{hid}'),
                    [self._set_src(dp, s1_mac), self._set_dst(dp, hmac),
                     parser.OFPActionOutput(hport)])
                self._add_static(dp, 200,
                    {'eth_type': ETH_IP, 'in_port': hport,
                     'ipv4_dst': '10.0.0.254'},
                    [parser.OFPActionOutput(ofp.OFPP_LOCAL)])
                self._add_static(dp, 200,
                    {'eth_type': ETH_IP, 'in_port': hport,
                     'ipv4_dst': ('192.168.56.0', '255.255.255.0')},
                    [parser.OFPActionOutput(ofp.OFPP_LOCAL)])

            # h→h ผ่าน s1
            for sid, sport in HOST_PORT.items():
                for did, dport in HOST_PORT.items():
                    if sid == did:
                        continue
                    self._add_static(dp, 200,
                        {'eth_type': ETH_ARP, 'in_port': sport,
                         'arp_tpa': f'10.0.0.{did}'},
                        self._out(dp, dport))
                    self._add_flow(dp, 200,
                        parser.OFPMatch(eth_type=ETH_IP, in_port=sport,
                                        ipv4_dst=f'10.0.0.{did}'),
                        [self._set_dst(dp, HOSTS[did]),
                         parser.OFPActionOutput(dport)])
            LOG.info("✅ TREE flows installed on s1")

        elif dp.id == 2:
            # s2: port1=s1, port2=h1, port3=h2
            LOG.info("📡 Installing TREE flows on s2...")
            HOSTS = {'10.0.0.1': (2, '00:00:00:00:00:01'),
                     '10.0.0.2': (3, '00:00:00:00:00:02')}
            for ip, (hport, hmac) in HOSTS.items():
                self._add_static(dp, 200,
                    {'eth_type': ETH_ARP, 'in_port': 1, 'arp_tpa': ip},
                    self._out(dp, hport))
                self._add_flow(dp, 200,
                    parser.OFPMatch(eth_type=ETH_IP, in_port=1,
                                    ipv4_dst=ip),
                    [self._set_dst(dp, hmac), parser.OFPActionOutput(hport)])
                self._add_static(dp, 200,
                    {'eth_type': ETH_ARP, 'in_port': hport},
                    self._out(dp, 1))
                self._add_static(dp, 200,
                    {'eth_type': ETH_IP, 'in_port': hport},
                    self._out(dp, 1))
            LOG.info("✅ TREE flows installed on s2")

        elif dp.id == 3:
            # s3: port1=s1, port2=h3, port3=h4
            LOG.info("📡 Installing TREE flows on s3...")
            HOSTS = {'10.0.0.3': (2, '00:00:00:00:00:03'),
                     '10.0.0.4': (3, '00:00:00:00:00:04')}
            for ip, (hport, hmac) in HOSTS.items():
                self._add_static(dp, 200,
                    {'eth_type': ETH_ARP, 'in_port': 1, 'arp_tpa': ip},
                    self._out(dp, hport))
                self._add_flow(dp, 200,
                    parser.OFPMatch(eth_type=ETH_IP, in_port=1,
                                    ipv4_dst=ip),
                    [self._set_dst(dp, hmac), parser.OFPActionOutput(hport)])
                self._add_static(dp, 200,
                    {'eth_type': ETH_ARP, 'in_port': hport},
                    self._out(dp, 1))
                self._add_static(dp, 200,
                    {'eth_type': ETH_IP, 'in_port': hport},
                    self._out(dp, 1))
            LOG.info("✅ TREE flows installed on s3")

    # ─────────────────────────────────────────────────────────────────────
    # MESH topology: s1-s2-s3-s4 fully connected, h1=s1p5, h2=s2p5, h3=s3p5, h4=s4p5
    # L2 learning เพียงพอสำหรับ mesh เพราะ STP จัดการ loop แล้ว
    # แต่ยังต้องการ LOCAL flows บน s1 สำหรับ Kali routing
    # ─────────────────────────────────────────────────────────────────────
    def _install_mesh(self, dp):
        ofp, parser = dp.ofproto, dp.ofproto_parser
        ETH_ARP, ETH_IP = 0x0806, 0x0800

        if dp.id == 1:
            LOG.info("📡 Installing MESH flows on s1 (LOCAL only)...")
            self._install_local_monitoring(dp)
            s1_mac = self._get_s1_mac()

            # สำหรับ mesh เราไม่รู้ port ของแต่ละ host ล่วงหน้า (STP อาจเปลี่ยน)
            # ใส่แค่ LOCAL flows สำหรับ Kali → Mininet
            # L2 learning จะจัดการ h→h เอง
            HOSTS = {
                1: '00:00:00:00:00:01', 2: '00:00:00:00:00:02',
                3: '00:00:00:00:00:03', 4: '00:00:00:00:00:04',
            }
            # h1 เชื่อม s1 โดยตรง ใช้ FLOOD สำหรับ hosts อื่น (ผ่าน mesh)
            for hid, hmac in HOSTS.items():
                self._add_static(dp, 200,
                    {'eth_type': ETH_ARP, 'in_port': LOCAL_PORT,
                     'arp_tpa': f'10.0.0.{hid}'},
                    [parser.OFPActionOutput(ofp.OFPP_FLOOD)])
                self._add_flow(dp, 200,
                    parser.OFPMatch(eth_type=ETH_IP, in_port=LOCAL_PORT,
                                    ipv4_dst=f'10.0.0.{hid}'),
                    [self._set_src(dp, s1_mac), self._set_dst(dp, hmac),
                     parser.OFPActionOutput(ofp.OFPP_FLOOD)])

            # hosts → LOCAL (reply กลับ Ubuntu/Kali)
            for port in range(1, 6):
                self._add_static(dp, 200,
                    {'eth_type': ETH_IP, 'in_port': port,
                     'ipv4_dst': '10.0.0.254'},
                    [parser.OFPActionOutput(ofp.OFPP_LOCAL)])
                self._add_static(dp, 200,
                    {'eth_type': ETH_IP, 'in_port': port,
                     'ipv4_dst': ('192.168.56.0', '255.255.255.0')},
                    [parser.OFPActionOutput(ofp.OFPP_LOCAL)])
                self._add_static(dp, 200,
                    {'eth_type': ETH_ARP, 'in_port': port,
                     'arp_tpa': '10.0.0.254'},
                    [parser.OFPActionOutput(ofp.OFPP_LOCAL)])
            LOG.info("✅ MESH flows installed on s1 (LOCAL+FLOOD)")

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
            if port > 10: continue # กรองพอร์ตเสมือน

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

                peak_pps = max(rx_pps, tx_pps)
                peak_bps = max(rx_bps, tx_bps)

                # ถ้าพอร์ตถูกบล็อกอยู่ ให้แสดงผลกราฟเป็น 0 เพื่อให้เห็นชัดเจนว่าส่งข้อมูลไม่ผ่าน
                display_pps = 0 if self._is_blocked(port) else peak_pps
                display_bps = 0 if self._is_blocked(port) else peak_bps

                # --- ส่วนที่ส่งข้อมูลไปหน้าเว็บ ---
                dash('/api/traffic', {
                    'port': port,
                    'pps': round(display_pps, 1),
                    'bps': round(display_bps / 1024, 1) # หน่วย KB
                })

                if HAS_DB and int(now) % 5 == 0:
                    db.log_traffic(port, display_pps, display_bps / 1024)
                # ------------------------------------

                # ตรวจสอบการโจมตี (เฉพาะเมื่อมีทราฟฟิกสูงระดับหนึ่งเพื่อกัน AI ตรวจจับผิดพลาดในทราฟฟิกต่ำ)
                if not self._is_blocked(port) and peak_pps > 100:
                    ctx = self.port_context.get(port, {'dst_port': 0, 'proto': 6})
                    self._lstm_check(
                        ev.msg.datapath, port, peak_pps, peak_bps, dt,
                        int(stat.rx_packets - prev['rx_pkts']), 
                        int(stat.rx_bytes - prev['rx_bytes']),
                        ctx['dst_port'], ctx['proto']
                    )

            self.prev_stats[key] = {
                'time': now, 'rx_pkts': stat.rx_packets, 'rx_bytes': stat.rx_bytes,
                'tx_pkts': stat.tx_packets, 'tx_bytes': stat.tx_bytes
            }

    def _lstm_check(self, dp, port, pps, bps, duration, pkt_count, byte_count, dst_port, protocol):
        if not self.model:
            if pps > FALLBACK_PPS_THRESHOLD:
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

            LOG.info(f"[LSTM] port={port} label='{label}' conf={conf:.4f} pps={pps:.1f}")

            # ส่ง ML stat ไปยัง Dashboard ทุกรอบที่คำนวณ
            dash('/api/ml', {
                'port': port,
                'pred': label,
                'conf': conf
            })

            # บล็อคถ้าเป็น Attack และมั่นใจ หรือถ้า Traffic สูงผิดปกติระดับ DDoS ทะลุ (Hard limit)
            if conf >= BLOCK_THRESHOLD and label.lower() != 'benign':
                self._take_action(dp, port, label, conf, pps, bps)
            elif pps > 10000:
                LOG.warning(f"🚨 HARD LIMIT REACHED on port {port} (pps={pps})")
                self._take_action(dp, port, 'DDoS-Anomaly', 0.99, pps, bps)
                
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
        dash('/api/attack', {
            'port': port, 
            'ip': f'port-{port}', 
            'label': label, 
            'conf': round(conf, 2),
            'pps': round(pps, 1)
        })

    def _block_port(self, dp, port, conf):
        parser = dp.ofproto_parser
        match = parser.OFPMatch(in_port=port)
        self._add_flow(dp, 100, match, [], idle_timeout=BLOCK_DURATION, hard_timeout=BLOCK_DURATION)
        self.blocked_ports[port] = {'time': time.time(), 'dpid': dp.id}
        LOG.warning(f"🚫 BLOCK port {port} | Attack: {conf:.2%}")

    def _rate_limit_port(self, dp, port, conf):
        parser = dp.ofproto_parser
        match = parser.OFPMatch(in_port=port)
        # ส่งเข้า Queue 1 (สมมติว่าตั้งค่า OVS QoS ไว้แล้ว)
        actions = [parser.OFPActionSetQueue(1), parser.OFPActionOutput(dp.ofproto.OFPP_FLOOD)]
        self._add_flow(dp, 90, match, actions, idle_timeout=BLOCK_DURATION, hard_timeout=BLOCK_DURATION)
        self.blocked_ports[port] = {'time': time.time(), 'dpid': dp.id}
        LOG.warning(f"🐌 RATE-LIMIT port {port} (UDPLag)")

    def _unblock_port(self, port, reason='expired'):
        if port not in self.blocked_ports: return
        dp = self.datapaths.get(self.blocked_ports[port]['dpid'])
        if dp:
            ofp, parser = dp.ofproto, dp.ofproto_parser
            match = parser.OFPMatch(in_port=port)
            # ลบกฎที่เคยสั่งบล็อกไว้
            for p in [100, 90]:
                dp.send_msg(parser.OFPFlowMod(dp, command=ofp.OFPFC_DELETE, 
                                              out_port=ofp.OFPP_ANY, out_group=ofp.OFPG_ANY, 
                                              match=match, priority=p))
        
        del self.blocked_ports[port]
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
# import os, time, logging, threading, urllib.request, json
# import numpy as np
# import tensorflow as tf
# import joblib
# import warnings
# warnings.filterwarnings("ignore")

# from ryu.base import app_manager
# from ryu.controller import ofp_event
# from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
# from ryu.ofproto import ofproto_v1_3
# from ryu.lib.packet import packet, ethernet, ipv4, tcp, udp
# from ryu.lib import hub

# LOG = logging.getLogger('sdn.lstm')

# # Path ของไฟล์ Model
# BASE        = os.path.dirname(os.path.abspath(__file__))
# MODEL_PATH  = os.path.join(BASE, '../ml/model/lstm_sdn_model.h5')
# SCALER_PATH = os.path.join(BASE, '../ml/model/scaler.pkl')
# LE_PATH     = os.path.join(BASE, '../ml/model/label_encoder.pkl')

# # ipc_path = '/tmp/unblock_requests.txt'
# # ipc_path = '/home/beepbeep-kun/unblock_requests.txt'

# BLOCK_THRESHOLD  = 0.90
# BLOCK_DURATION   = 120
# STATS_INTERVAL   = 2
# DASH_URL         = 'http://localhost:5000'
# WARMUP_SECONDS   = 60
# MIN_PPS_CHECK    = 500
# CONSECUTIVE_HITS = 2

# LOCAL_PORT       = 0xfffffffe
# WHITELIST_IPS    = set()
# WHITELIST_PORTS  = set()

# # Fallback กรณี Model โหลดไม่ได้
# FALLBACK_PPS_THRESHOLD = 1000
# FALLBACK_BPS_THRESHOLD = 1_000_000

# # ─── Topology: host_id → (s1_port, mac, ip) ───
# # h1=port1, h2=port2, h3=port3, h4=port4, h_server=port5
# HOSTS = {
#     1:   (1, '00:00:00:00:00:01', '10.0.0.1'),
#     2:   (2, '00:00:00:00:00:02', '10.0.0.2'),
#     3:   (3, '00:00:00:00:00:03', '10.0.0.3'),
#     4:   (4, '00:00:00:00:00:04', '10.0.0.4'),
#     100: (5, '00:00:00:00:00:64', '10.0.0.100'),  # web server
# }

# # เชื่อมต่อ Database และ Notifier
# try:
#     import sys
#     sys.path.insert(0, os.path.join(BASE, '..'))
#     import db_manager as db
#     db.init_db()
#     HAS_DB = True
#     LOG.info("✅ Database connected successfully")
# except Exception as e:
#     HAS_DB = False
#     LOG.error(f"❌ Database connection failed: {e} — จะไม่บันทึกข้อมูลลง DB")

# try:
#     from notifier import notify_attack, notify_unblock
#     HAS_NOTIFY = True
# except:
#     HAS_NOTIFY = False

# def _post(path, data):
#     try:
#         body = json.dumps(data).encode()
#         req  = urllib.request.Request(
#             DASH_URL + path, data=body,
#             headers={'Content-Type': 'application/json'}, method='POST')
#         urllib.request.urlopen(req, timeout=1)
#     except:
#         pass

# def dash(path, data):
#     threading.Thread(target=_post, args=(path, data), daemon=True).start()

# class IntelligentController(app_manager.RyuApp):
#     OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

#     def __init__(self, *args, **kwargs):
#         super().__init__(*args, **kwargs)
#         self.datapaths     = {}
#         self.mac_to_port   = {}
#         # ─── ACL: IP-based blocking แทน port-based ───
#         self.blocked_ips   = {}   # {ip: {time, dpid, port, label}}
#         self.prev_stats    = {}
#         self.port_context  = {}
#         self.port_ip_map   = {}   # port → last seen src IP
#         for hid, (hport, hmac, hip) in HOSTS.items():
#             self.port_ip_map[hport] = hip
#         self.alert_counts  = {}   # port → consecutive hit count
#         self.startup_time  = time.time()

#         self.active_model_id = None
#         self._load_active_model()

#         self.monitor_thread = hub.spawn(self._monitor_loop)
#         self.unblock_thread = hub.spawn(self._unblock_loop)
#         self.model_check_thread = hub.spawn(self._model_check_loop)

#     @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
#     def switch_features_handler(self, ev):
#         dp = ev.msg.datapath
#         ofp, parser = dp.ofproto, dp.ofproto_parser
#         self.datapaths[dp.id] = dp

#         # Default Rule: ส่ง Packet ที่ไม่รู้จักเข้า Controller
#         self._add_flow(dp, 0, parser.OFPMatch(),
#             [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)])

#         if dp.id == 1:
#             self._install_s1_static_flows(dp)

#     # ─────────────────────────────────────────────────────────────────
#     # Static Flow Installer
#     # ─────────────────────────────────────────────────────────────────
#     S1_MAC = None

#     def _add_static(self, dp, priority, match_kwargs, actions):
#         self._add_flow(dp, priority,
#                        dp.ofproto_parser.OFPMatch(**match_kwargs), actions)

#     def _out(self, dp, *ports):
#         return [dp.ofproto_parser.OFPActionOutput(p) for p in ports]

#     def _set_eth_dst(self, dp, mac):
#         return dp.ofproto_parser.OFPActionSetField(eth_dst=mac)

#     def _set_eth_src(self, dp, mac):
#         return dp.ofproto_parser.OFPActionSetField(eth_src=mac)

#     def _install_s1_static_flows(self, dp):
#         ofp, parser = dp.ofproto, dp.ofproto_parser
#         LOG.info("📡 Installing s1 static flows (ACL mode)...")

#         # ── LOCAL port: LSTM monitoring ────────────────────────────────
#         self._add_flow(dp, 8,
#             parser.OFPMatch(in_port=LOCAL_PORT),
#             [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER),
#              parser.OFPActionOutput(ofp.OFPP_NORMAL)])

#         # ── อ่าน s1 LOCAL MAC จาก OVS ─────────────────────────────────
#         import subprocess, re
#         try:
#             out = subprocess.check_output(
#                 ['ovs-ofctl', '-O', 'OpenFlow13', 'show', 's1'],
#                 stderr=subprocess.DEVNULL).decode()
#             m = re.search(r'LOCAL\(s1\).*?addr:([0-9a-f:]+)', out)
#             s1_mac = m.group(1) if m else '00:00:00:00:00:fe'
#         except Exception:
#             s1_mac = '00:00:00:00:00:fe'
#         IntelligentController.S1_MAC = s1_mac
#         LOG.info(f"   s1 LOCAL MAC = {s1_mac}")

#         ETH_ARP, ETH_IP = 0x0806, 0x0800

#         # ── ARP: LOCAL → each host ─────────────────────────────────────
#         for hid, (hport, _, hip) in HOSTS.items():
#             self._add_static(dp, 200,
#                 {'eth_type': ETH_ARP, 'in_port': LOCAL_PORT,
#                  'arp_tpa': hip},
#                 self._out(dp, hport))

#         # ── ARP: hosts → LOCAL ─────────────────────────────────────────
#         for hid, (hport, _, _) in HOSTS.items():
#             self._add_static(dp, 200,
#                 {'eth_type': ETH_ARP, 'in_port': hport,
#                  'arp_tpa': '10.0.0.254'},
#                 [parser.OFPActionOutput(ofp.OFPP_LOCAL)])

#         # ── ARP: h→h ──────────────────────────────────────────────────
#         for src_id, (src_port, _, _) in HOSTS.items():
#             for dst_id, (dst_port, _, dst_ip) in HOSTS.items():
#                 if src_id == dst_id: continue
#                 self._add_static(dp, 200,
#                     {'eth_type': ETH_ARP, 'in_port': src_port,
#                      'arp_tpa': dst_ip},
#                     self._out(dp, dst_port))

#         # ── IP: LOCAL → hosts ──────────────────────────────────────────
#         for hid, (hport, hmac, hip) in HOSTS.items():
#             self._add_flow(dp, 200,
#                 parser.OFPMatch(eth_type=ETH_IP, in_port=LOCAL_PORT,
#                                 ipv4_dst=hip),
#                 [self._set_eth_src(dp, s1_mac),
#                  self._set_eth_dst(dp, hmac),
#                  parser.OFPActionOutput(hport)])

#         # ── IP: hosts → LOCAL ──────────────────────────────────────────
#         for hid, (hport, _, _) in HOSTS.items():
#             self._add_static(dp, 200,
#                 {'eth_type': ETH_IP, 'in_port': hport,
#                  'ipv4_dst': '10.0.0.254'},
#                 [parser.OFPActionOutput(ofp.OFPP_LOCAL)])
#             self._add_static(dp, 200,
#                 {'eth_type': ETH_IP, 'in_port': hport,
#                  'ipv4_dst': ('192.168.56.0', '255.255.255.0')},
#                 [parser.OFPActionOutput(ofp.OFPP_LOCAL)])

#         # ── IP: h→h ───────────────────────────────────────────────────
#         for src_id, (src_port, _, _) in HOSTS.items():
#             for dst_id, (dst_port, dst_mac, dst_ip) in HOSTS.items():
#                 if src_id == dst_id: continue
#                 self._add_flow(dp, 200,
#                     parser.OFPMatch(eth_type=ETH_IP, in_port=src_port,
#                                     ipv4_dst=dst_ip),
#                     [self._set_eth_dst(dp, dst_mac),
#                      parser.OFPActionOutput(dst_port)])

#         LOG.info("✅ s1 static flows installed (ARP + IP + h→h + LOCAL + WebServer)")

#     @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
#     def packet_in_handler(self, ev):
#         msg = ev.msg
#         dp = msg.datapath
#         ofp = dp.ofproto
#         parser = dp.ofproto_parser
#         in_port = msg.match['in_port']

#         pkt = packet.Packet(msg.data)
#         eth = pkt.get_protocol(ethernet.ethernet)
#         if not eth: return

#         # ดึงข้อมูล IP/Port เพื่อเป็น Context ให้ LSTM
#         ip_pkt = pkt.get_protocol(ipv4.ipv4)
#         if ip_pkt:
#             proto_num = ip_pkt.proto
#             dst_p = 0
#             t = pkt.get_protocol(tcp.tcp)
#             u = pkt.get_protocol(udp.udp)
#             if t: dst_p = t.dst_port
#             elif u: dst_p = u.dst_port
#             self.port_context[in_port] = {'dst_port': dst_p, 'proto': proto_num}
#             self.port_ip_map[in_port] = ip_pkt.src

#             # ─── ACL: เช็คว่า src IP ถูก block อยู่หรือไม่ ───
#             if self._is_ip_blocked(ip_pkt.src):
#                 return

#         # L2 Learning
#         self.mac_to_port.setdefault(dp.id, {})
#         self.mac_to_port[dp.id][eth.src] = in_port
#         out_port = self.mac_to_port[dp.id].get(eth.dst, ofp.OFPP_FLOOD)
        
#         actions = [parser.OFPActionOutput(out_port)]
#         if out_port != ofp.OFPP_FLOOD:
#             self._add_flow(dp, 1, parser.OFPMatch(in_port=in_port, eth_dst=eth.dst), actions)
        
#         data = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
#         dp.send_msg(parser.OFPPacketOut(datapath=dp, buffer_id=msg.buffer_id,
#                                         in_port=in_port, actions=actions, data=data))

#     @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
#     def port_stats_reply_handler(self, ev):
#         dpid = ev.msg.datapath.id
#         now  = time.time()

#         for stat in ev.msg.body:
#             port = stat.port_no
#             if port > 10 and port != LOCAL_PORT: continue

#             key = (dpid, port)
#             if key in self.prev_stats:
#                 prev = self.prev_stats[key]
#                 dt = now - prev['time']
#                 if dt <= 0: continue

#                 rx_pps = (stat.rx_packets - prev['rx_pkts']) / dt
#                 rx_bps = (stat.rx_bytes - prev['rx_bytes']) / dt
#                 tx_pps = (stat.tx_packets - prev['tx_pkts']) / dt
#                 tx_bps = (stat.tx_bytes - prev['tx_bytes']) / dt

#                 detect_pps = rx_pps
#                 detect_bps = rx_bps

#                 # ถ้า IP จาก port นี้ถูก block → แสดง 0
#                 src_ip = self.port_ip_map.get(port)
#                 is_blocked = src_ip and src_ip in self.blocked_ips
#                 display_pps = 0 if is_blocked else rx_pps
#                 display_bps = 0 if is_blocked else rx_bps

#                 display_port = 'kali' if port == LOCAL_PORT else port
#                 dash('/api/traffic', {
#                     'port': display_port,
#                     'pps': round(display_pps, 1),
#                     'bps': round(display_bps / 1024, 1)
#                 })

#                 if HAS_DB and int(now) % 3 == 0 and port != LOCAL_PORT:
#                     db.log_traffic(port, display_pps, display_bps / 1024)

#                 if (not is_blocked
#                         and detect_pps > MIN_PPS_CHECK
#                         and self._warmup_done()):
#                     ctx = self.port_context.get(port, {'dst_port': 0, 'proto': 6})
#                     self._lstm_check(
#                         ev.msg.datapath, port, detect_pps, detect_bps, dt,
#                         int(stat.rx_packets - prev['rx_pkts']), 
#                         int(stat.rx_bytes - prev['rx_bytes']),
#                         ctx['dst_port'], ctx['proto']
#                     )
#                 elif not is_blocked:
#                     self.alert_counts.pop(port, None)

#             self.prev_stats[key] = {
#                 'time': now, 'rx_pkts': stat.rx_packets, 'rx_bytes': stat.rx_bytes,
#                 'tx_pkts': stat.tx_packets, 'tx_bytes': stat.tx_bytes
#             }

#     def _lstm_check(self, dp, port, pps, bps, duration, pkt_count, byte_count, dst_port, protocol):
#         if not self.model:
#             if pps > FALLBACK_PPS_THRESHOLD:
#                 self.alert_counts[port] = self.alert_counts.get(port, 0) + 1
#                 if self.alert_counts[port] >= CONSECUTIVE_HITS:
#                     self._take_action(dp, port, 'DDoS-Fallback', 0.99, pps, bps)
#             return

#         try:
#             duration_us = duration * 1_000_000
#             iat_mean = (duration_us / max(pkt_count, 1))
            
#             features = np.array([[
#                 dst_port, protocol, duration_us, pkt_count, 0, 
#                 byte_count, 0, bps, pps, iat_mean
#             ]])

#             scaled = self.scaler.transform(features)
#             lstm_input = np.reshape(scaled, (1, 1, scaled.shape[1]))

#             pred = self.model.predict(lstm_input, verbose=0)
#             idx = np.argmax(pred[0])
#             conf = float(pred[0][idx])
#             label = self.le.inverse_transform([idx])[0]

#             LOG.info(f"[LSTM] port={port} label='{label}' conf={conf:.4f} pps={pps:.1f} hits={self.alert_counts.get(port, 0)}")

#             dash('/api/ml', {
#                 'port': port,
#                 'pred': label,
#                 'conf': conf
#             })

#             is_attack = (conf >= BLOCK_THRESHOLD and label.lower() != 'benign') or pps > 10000

#             if is_attack:
#                 self.alert_counts[port] = self.alert_counts.get(port, 0) + 1
#                 LOG.info(f"[ALERT] port={port} consecutive hit #{self.alert_counts[port]}/{CONSECUTIVE_HITS}")

#                 if self.alert_counts[port] >= CONSECUTIVE_HITS:
#                     if pps > 10000 and (conf < BLOCK_THRESHOLD or label.lower() == 'benign'):
#                         LOG.warning(f"🚨 HARD LIMIT REACHED on port {port} (pps={pps})")
#                         self._take_action(dp, port, 'DDoS-Anomaly', 0.99, pps, bps)
#                     else:
#                         self._take_action(dp, port, label, conf, pps, bps)
#             else:
#                 self.alert_counts.pop(port, None)
                
#         except Exception as e:
#             LOG.error(f"Prediction Error: {e}")

#     def _take_action(self, dp, port, label, conf, pps, bps):
#         src_ip = self.port_ip_map.get(port)
#         if not src_ip:
#             LOG.warning(f"⚠️  Cannot block — no IP mapped for port {port}")
#             return

#         LOG.info(f"AI Prediction: {label} with confidence {conf}")

#         # ─── ACL: block เฉพาะ IP ที่โจมตี ───
#         if label.lower() == 'udplag':
#             self._rate_limit_ip(dp, src_ip, port, conf)
#         else:
#             self._block_ip(dp, src_ip, port, conf, label)

#         # บันทึกและแจ้งเตือน
#         if HAS_NOTIFY: notify_attack(port, pps, conf)
#         if HAS_DB:
#             db.log_attack(port, pps, bps/1024, conf, note=label,
#                           attack_type=label, dpid=dp.id)
#             db.block_port(port, conf, BLOCK_DURATION)
        
#         dash('/api/attack', {
#             'port': port, 
#             'ip': src_ip, 
#             'label': label, 
#             'conf': round(conf, 2),
#             'pps': round(pps, 1)
#         })
#         self.alert_counts.pop(port, None)

#     def _block_ip(self, dp, src_ip, port, conf, label=''):
#         """─── ACL: Block เฉพาะ IP ที่โจมตี (ไม่ block ทั้ง port) ───"""
#         parser = dp.ofproto_parser

#         if src_ip in WHITELIST_IPS:
#             LOG.warning(f"⚠️  SKIP block — IP {src_ip} is whitelisted")
#             return

#         # Drop rule: match by src IP only (priority 500 > static flows 200)
#         match = parser.OFPMatch(eth_type=0x0800, ipv4_src=src_ip)
#         self._add_flow(dp, 500, match, [],
#                        idle_timeout=BLOCK_DURATION, hard_timeout=BLOCK_DURATION)

#         # Drop rule สำหรับ LOCAL port path ด้วย
#         match_local = parser.OFPMatch(
#             eth_type=0x0800, in_port=LOCAL_PORT, ipv4_src=src_ip)
#         self._add_flow(dp, 501, match_local, [],
#                        idle_timeout=BLOCK_DURATION, hard_timeout=BLOCK_DURATION)

#         self.blocked_ips[src_ip] = {
#             'time': time.time(), 'dpid': dp.id,
#             'port': port, 'label': label
#         }
#         LOG.warning(f"🚫 ACL BLOCK IP {src_ip} (from port {port}) | Attack: {label} {conf:.2%}")

#     def _rate_limit_ip(self, dp, src_ip, port, conf):
#         """─── ACL: Rate-limit เฉพาะ IP ───"""
#         parser = dp.ofproto_parser
#         match = parser.OFPMatch(eth_type=0x0800, ipv4_src=src_ip)
#         actions = [parser.OFPActionSetQueue(1),
#                    parser.OFPActionOutput(dp.ofproto.OFPP_FLOOD)]
#         self._add_flow(dp, 490, match, actions,
#                        idle_timeout=BLOCK_DURATION, hard_timeout=BLOCK_DURATION)
#         self.blocked_ips[src_ip] = {
#             'time': time.time(), 'dpid': dp.id,
#             'port': port, 'label': 'UDPLag'
#         }
#         LOG.warning(f"🐌 ACL RATE-LIMIT IP {src_ip} (UDPLag)")

#     def _unblock_ip(self, src_ip, reason='expired'):
#         """─── ACL: Unblock IP ───"""
#         if src_ip not in self.blocked_ips: return
#         info = self.blocked_ips[src_ip]
#         dp = self.datapaths.get(info['dpid'])
#         port = info.get('port', 0)

#         if dp:
#             ofp, parser = dp.ofproto, dp.ofproto_parser
#             # ลบ drop rules ทั้งหมดของ IP นี้
#             for match, pri in [
#                 (parser.OFPMatch(eth_type=0x0800, ipv4_src=src_ip), 500),
#                 (parser.OFPMatch(eth_type=0x0800, in_port=LOCAL_PORT, ipv4_src=src_ip), 501),
#                 (parser.OFPMatch(eth_type=0x0800, ipv4_src=src_ip), 490),
#             ]:
#                 dp.send_msg(parser.OFPFlowMod(dp,
#                     command=ofp.OFPFC_DELETE,
#                     out_port=ofp.OFPP_ANY, out_group=ofp.OFPG_ANY,
#                     match=match, priority=pri))

#         del self.blocked_ips[src_ip]
#         self.alert_counts.pop(port, None)
#         if HAS_DB: db.unblock_port(port, reason)
#         if HAS_NOTIFY: notify_unblock(port, reason)
#         dash('/api/unblock', {'port': port, 'ip': src_ip})
#         LOG.info(f"✅ ACL Unblocked IP {src_ip} (port {port}, {reason})")

#     def _is_ip_blocked(self, src_ip):
#         """เช็คว่า IP ถูก block อยู่หรือไม่"""
#         if src_ip in self.blocked_ips:
#             if time.time() - self.blocked_ips[src_ip]['time'] >= BLOCK_DURATION:
#                 self._unblock_ip(src_ip)
#                 return False
#             return True
#         return False

#     def _warmup_done(self):
#         return (time.time() - self.startup_time) >= WARMUP_SECONDS

#     def _load_active_model(self):
#         m_path = MODEL_PATH
#         s_path = SCALER_PATH
#         l_path = LE_PATH

#         if HAS_DB:
#             try:
#                 active_model = db.get_active_model()
#                 if active_model:
#                     m_path = active_model.get('file_path', m_path)
#                     s_path = active_model.get('scaler_path', s_path)
#                     l_path = active_model.get('le_path', l_path)
#                     self.active_model_id = active_model.get('id')
#             except Exception as e:
#                 LOG.error(f"❌ Failed to fetch active model from DB: {e}")

#         try:
#             self.model  = tf.keras.models.load_model(m_path)
#             self.scaler = joblib.load(s_path) if s_path else None
#             self.le     = joblib.load(l_path) if l_path else None
#             LOG.info(f"✅ LSTM Model & Scaler loaded successfully (Model ID: {self.active_model_id})")
#         except Exception as e:
#             self.model = self.scaler = self.le = None
#             LOG.error(f"❌ Model Load Error: {e}")

#     def _model_check_loop(self):
#         while True:
#             if HAS_DB:
#                 try:
#                     active_model = db.get_active_model()
#                     if active_model:
#                         new_id = active_model.get('id')
#                         if new_id != self.active_model_id:
#                             LOG.info(f"🔄 Active model changed in DB from {self.active_model_id} to {new_id}. Reloading model...")
#                             self._load_active_model()
#                 except Exception as e:
#                     pass
#             hub.sleep(10)

#     def _monitor_loop(self):
#         while True:
#             for dp in self.datapaths.values():
#                 dp.send_msg(dp.ofproto_parser.OFPPortStatsRequest(dp, 0, dp.ofproto.OFPP_ANY))
#             hub.sleep(STATS_INTERVAL)

#     def _unblock_loop(self):
#         """ตรวจ blocked IPs ที่หมดเวลา และรับคำสั่ง unblock จากแอดมิน (IPC)"""
#         while True:
#             # 1. เช็ค IP หมดเวลาบล็อกปกติ
#             for ip in list(self.blocked_ips):
#                 self._is_ip_blocked(ip)

#             # 2. เช็คสัญญาณ unblock จาก Flask API
#             ipc_path = '/tmp/unblock_requests.txt'
#             if os.path.exists(ipc_path):
#                 try:
#                     with open(ipc_path, 'r') as f:
#                         ips = [line.strip() for line in f if line.strip()]
                    
#                     # ลบไฟล์ทิ้งหลังอ่านแล้ว
#                     open(ipc_path, 'w').close()

#                     for ip in ips:
#                         if ip in self.blocked_ips:
#                             LOG.info(f"📬 IPC: Admin requested unblock for IP {ip}")
#                             self._unblock_ip(ip, reason='admin')
#                 except Exception as e:
#                     LOG.error(f"❌ Error processing unblock IPC: {e}")

#             hub.sleep(2)

#     def _add_flow(self, dp, priority, match, actions, idle_timeout=0, hard_timeout=0):
#         ofp, parser = dp.ofproto, dp.ofproto_parser
#         inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
#         dp.send_msg(parser.OFPFlowMod(datapath=dp, priority=priority, match=match,
#                                       instructions=inst, idle_timeout=idle_timeout,
#                                       hard_timeout=hard_timeout))




#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Dynamic SDN Controller
======================

Features
--------
1. Dynamic L2 learning
2. Dynamic host-location discovery
3. Ryu topology discovery
4. Dynamic shortest-path forwarding
5. Star / Tree / Mesh compatible
6. LSTM DDoS detection
7. IP-based ACL
8. Temporary IP blocking
9. Admin unblock via IPC
10. Dashboard API integration
11. Database logging
12. Dynamic active-model reload

IMPORTANT
---------
This controller intentionally DOES NOT use hard-coded host ports.

Old design:
    h1 = s1 port 1
    h2 = s1 port 2
    h3 = s1 port 3
    h4 = s1 port 4

New design:
    host location is learned dynamically:

        host_mac -> (dpid, port)

Therefore:

    Star:
        h1,h2,h3,h4 -> s1

    Tree:
        h1,h2 -> s2
        h3,h4 -> s3

    Mesh:
        h1 -> s1
        h2 -> s2
        h3 -> s3
        h4 -> s4

all work with the same controller.
"""

import os
import time
import json
import logging
import threading
import urllib.request
from collections import defaultdict, deque

import numpy as np
import tensorflow as tf
import joblib
import warnings

warnings.filterwarnings("ignore")


# ---------------------------------------------------------------------
# RYU IMPORTS
# ---------------------------------------------------------------------

from ryu.base import app_manager

from ryu.controller import ofp_event
from ryu.controller.handler import (
    CONFIG_DISPATCHER,
    MAIN_DISPATCHER,
    DEAD_DISPATCHER,
    set_ev_cls,
)

from ryu.ofproto import ofproto_v1_3

from ryu.lib.packet import (
    packet,
    ethernet,
    ipv4,
    arp,
    tcp,
    udp,
)

from ryu.lib import hub

# Dynamic topology discovery
from ryu.topology import event
from ryu.topology.api import get_switch, get_link


# ---------------------------------------------------------------------
# LOGGER
# ---------------------------------------------------------------------

LOG = logging.getLogger("sdn.lstm")


# ---------------------------------------------------------------------
# BASE PATH
# ---------------------------------------------------------------------

BASE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------
# ML MODEL PATH
# ---------------------------------------------------------------------

MODEL_PATH = os.path.join(
    BASE,
    "../ml/model/lstm_sdn_model.h5"
)

SCALER_PATH = os.path.join(
    BASE,
    "../ml/model/scaler.pkl"
)

LE_PATH = os.path.join(
    BASE,
    "../ml/model/label_encoder.pkl"
)


# ---------------------------------------------------------------------
# DDoS SETTINGS
# ---------------------------------------------------------------------

BLOCK_THRESHOLD = 0.90

BLOCK_DURATION = 120

STATS_INTERVAL = 2

DASH_URL = "http://localhost:5000"

WARMUP_SECONDS = 60

MIN_PPS_CHECK = 500

CONSECUTIVE_HITS = 2

FALLBACK_PPS_THRESHOLD = 1000

FALLBACK_BPS_THRESHOLD = 1_000_000


# ---------------------------------------------------------------------
# OPENFLOW
# ---------------------------------------------------------------------

LOCAL_PORT = 0xfffffffe

FLOOD_TOPOLOGY_SETTLE_SECONDS = 5

DATASET_REQUIRED_SWITCHES = 4

DATASET_REQUIRED_DIRECTED_LINKS = 12


# ---------------------------------------------------------------------
# ACL
# ---------------------------------------------------------------------

WHITELIST_IPS = set()

WHITELIST_PORTS = set()


# ---------------------------------------------------------------------
# ETHERTYPES
# ---------------------------------------------------------------------

ETH_IP = 0x0800
ETH_ARP = 0x0806


# ---------------------------------------------------------------------
# DATABASE
# ---------------------------------------------------------------------

try:
    import sys

    sys.path.insert(
        0,
        os.path.join(BASE, "..")
    )

    import db_manager as db

    db.init_db()

    HAS_DB = True

    LOG.info(
        "✅ Database connected successfully"
    )

except Exception as e:

    HAS_DB = False

    LOG.error(
        "❌ Database connection failed: %s",
        e
    )


from collector.sdn_window_recorder import SdnWindowCsvRecorder


# ---------------------------------------------------------------------
# NOTIFIER
# ---------------------------------------------------------------------

try:

    from notifier import (
        notify_attack,
        notify_unblock,
    )

    HAS_NOTIFY = True

except Exception:

    HAS_NOTIFY = False


# =====================================================================
# DASHBOARD API
# =====================================================================

def _post(path, data):

    try:

        body = json.dumps(data).encode()

        req = urllib.request.Request(
            DASH_URL + path,
            data=body,
            headers={
                "Content-Type": "application/json"
            },
            method="POST",
        )

        urllib.request.urlopen(
            req,
            timeout=1
        )

    except Exception:

        pass


def dash(path, data):

    threading.Thread(
        target=_post,
        args=(path, data),
        daemon=True,
    ).start()


# =====================================================================
# CONTROLLER
# =====================================================================

class IntelligentController(app_manager.RyuApp):

    OFP_VERSIONS = [
        ofproto_v1_3.OFP_VERSION
    ]

    # -----------------------------------------------------------------
    # INIT
    # -----------------------------------------------------------------

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

        # =============================================================
        # DATAPATHS
        # =============================================================

        self.datapaths = {}

        # =============================================================
        # L2 MAC LEARNING
        #
        # {
        #     dpid: {
        #         mac: port
        #     }
        # }
        # =============================================================

        self.mac_to_port = defaultdict(dict)

        # =============================================================
        # HOST LOCATION
        #
        # {
        #     mac: {
        #         dpid: switch_id,
        #         port: host_port,
        #         ip: ip
        #     }
        # }
        #
        # This replaces the old hard-coded HOSTS dictionary.
        # =============================================================

        self.host_location = {}

        # =============================================================
        # IP -> HOST LOCATION
        # =============================================================

        self.ip_location = {}

        # =============================================================
        # TOPOLOGY GRAPH
        #
        # graph[dpid][neighbor_dpid] = port_to_neighbor
        # =============================================================

        self.topology = defaultdict(dict)

        # =============================================================
        # REVERSE TOPOLOGY
        #
        # reverse_topology[dpid][neighbor] = port
        # =============================================================

        self.reverse_topology = defaultdict(dict)

        # =============================================================
        # LINK PORT CACHE
        #
        # (src_dpid, dst_dpid) -> src_port
        # =============================================================

        self.link_ports = {}

        # Unknown traffic is held until the discovered topology has
        # stopped changing. This prevents partially discovered switch
        # links from being mistaken for host-facing ports.
        self.topology_last_change = time.monotonic()

        # Dataset recording is opt-in and writes from a bounded background
        # queue. The controller continues normally when it is disabled.
        self.dataset_recorder = SdnWindowCsvRecorder.from_environment(
            logger=LOG
        )

        self.dataset_topology_ready_since = None

        # =============================================================
        # BLOCKED IP
        #
        # {
        #     ip: {
        #         time,
        #         dpid,
        #         port,
        #         label
        #     }
        # }
        # =============================================================

        self.blocked_ips = {}

        # =============================================================
        # PREVIOUS PORT STATS
        # =============================================================

        self.prev_stats = {}

        # =============================================================
        # PORT CONTEXT FOR ML
        # =============================================================

        self.port_context = {}

        # =============================================================
        # PORT -> LAST SEEN IP
        #
        # Key now includes DPID because port numbers repeat
        # between switches.
        #
        # (dpid, port) -> IP
        # =============================================================

        self.port_ip_map = {}

        # =============================================================
        # ALERT COUNTERS
        #
        # (dpid, port) -> count
        # =============================================================

        self.alert_counts = {}

        # =============================================================
        # STARTUP TIME
        # =============================================================

        self.startup_time = time.time()

        # =============================================================
        # MODEL
        # =============================================================

        self.model = None

        self.scaler = None

        self.le = None

        self.active_model_id = None

        self._load_active_model()

        # =============================================================
        # BACKGROUND THREADS
        # =============================================================

        self.monitor_thread = hub.spawn(
            self._monitor_loop
        )

        self.unblock_thread = hub.spawn(
            self._unblock_loop
        )

        self.model_check_thread = hub.spawn(
            self._model_check_loop
        )

        self.topology_thread = hub.spawn(
            self._topology_refresh_loop
        )

        LOG.info(
            "=================================================="
        )

        LOG.info(
            "🚀 Dynamic SDN Controller started"
        )

        LOG.info(
            "🚀 Star / Tree / Mesh supported"
        )

        LOG.info(
            "🚀 Dynamic host discovery enabled"
        )

        LOG.info(
            "🚀 LSTM + DDoS + ACL enabled"
        )

        LOG.info(
            "=================================================="
        )

    # =================================================================
    # SWITCH FEATURES
    # =================================================================

    @set_ev_cls(
        ofp_event.EventOFPSwitchFeatures,
        CONFIG_DISPATCHER
    )
    def switch_features_handler(self, ev):

        dp = ev.msg.datapath

        ofp = dp.ofproto

        parser = dp.ofproto_parser

        dpid = dp.id

        self.datapaths[dpid] = dp

        self.mac_to_port.setdefault(
            dpid,
            {}
        )

        LOG.info(
            "🔌 Switch connected: s%s",
            dpid
        )

        # -------------------------------------------------------------
        # TABLE MISS
        #
        # Unknown traffic goes to controller.
        # -------------------------------------------------------------

        self._add_flow(
            dp,
            priority=0,
            match=parser.OFPMatch(),
            actions=[
                parser.OFPActionOutput(
                    ofp.OFPP_CONTROLLER,
                    ofp.OFPCML_NO_BUFFER
                )
            ],
        )

        # -------------------------------------------------------------
        # LOCAL PORT
        #
        # Used for controller / Kali related traffic.
        # -------------------------------------------------------------

        self._add_flow(
            dp,
            priority=10,
            match=parser.OFPMatch(
                in_port=LOCAL_PORT
            ),
            actions=[
                parser.OFPActionOutput(
                    ofp.OFPP_CONTROLLER,
                    ofp.OFPCML_NO_BUFFER
                ),
                parser.OFPActionOutput(
                    ofp.OFPP_NORMAL
                ),
            ],
        )

    # =================================================================
    # SWITCH DEAD
    # =================================================================

    @set_ev_cls(
        ofp_event.EventOFPStateChange,
        [MAIN_DISPATCHER, DEAD_DISPATCHER]
    )
    def state_change_handler(self, ev):

        dp = ev.datapath

        if ev.state == MAIN_DISPATCHER:

            if dp.id not in self.datapaths:

                self.datapaths[dp.id] = dp

                LOG.info(
                    "🟢 Switch registered: s%s",
                    dp.id
                )

        elif ev.state == DEAD_DISPATCHER:

            if dp.id in self.datapaths:

                del self.datapaths[dp.id]

                LOG.warning(
                    "🔴 Switch disconnected: s%s",
                    dp.id
                )

            self.topology.pop(
                dp.id,
                None
            )

            self.reverse_topology.pop(
                dp.id,
                None
            )

    # =================================================================
    # TOPOLOGY EVENTS
    # =================================================================

    @set_ev_cls(
        event.EventSwitchEnter
    )
    def switch_enter_handler(self, ev):

        LOG.info(
            "🟢 Topology switch enter"
        )

        self._refresh_topology()

    # -----------------------------------------------------------------

    @set_ev_cls(
        event.EventSwitchLeave
    )
    def switch_leave_handler(self, ev):

        LOG.info(
            "🔴 Topology switch leave"
        )

        self._refresh_topology()

    # -----------------------------------------------------------------

    @set_ev_cls(
        event.EventLinkAdd
    )
    def link_add_handler(self, ev):

        link = ev.link

        src = link.src

        dst = link.dst

        if self.topology[src.dpid].get(dst.dpid) != src.port_no:

            self.topology_last_change = time.monotonic()

        self.topology[
            src.dpid
        ][dst.dpid] = src.port_no

        self.link_ports[
            (src.dpid, dst.dpid)
        ] = src.port_no

        self.reverse_topology[
            dst.dpid
        ][src.dpid] = dst.port_no

        LOG.info(
            "🔗 LINK ADD: s%s:%s -> s%s:%s",
            src.dpid,
            src.port_no,
            dst.dpid,
            dst.port_no,
        )

    # -----------------------------------------------------------------

    @set_ev_cls(
        event.EventLinkDelete
    )
    def link_delete_handler(self, ev):

        link = ev.link

        src = link.src

        dst = link.dst

        removed_port = self.topology[
            src.dpid
        ].pop(
            dst.dpid,
            None
        )

        if removed_port is not None:

            self.topology_last_change = time.monotonic()

        self.reverse_topology[
            dst.dpid
        ].pop(
            src.dpid,
            None
        )

        self.link_ports.pop(
            (src.dpid, dst.dpid),
            None
        )

        LOG.warning(
            "🔌 LINK DELETE: s%s -> s%s",
            src.dpid,
            dst.dpid,
        )

    # =================================================================
    # REFRESH TOPOLOGY
    # =================================================================

    def _refresh_topology(self):

        try:

            switches = get_switch(
                self,
                None
            )

            links = get_link(
                self,
                None
            )

            new_topology = defaultdict(dict)

            new_reverse = defaultdict(dict)

            new_link_ports = {}

            # ---------------------------------------------------------
            # REGISTER SWITCHES
            # ---------------------------------------------------------

            for sw in switches:

                dpid = sw.dp.id

                if dpid not in self.datapaths:

                    self.datapaths[dpid] = sw.dp

            # ---------------------------------------------------------
            # REGISTER LINKS
            # ---------------------------------------------------------

            for link in links:

                src = link.src

                dst = link.dst

                new_topology[
                    src.dpid
                ][dst.dpid] = src.port_no

                new_reverse[
                    dst.dpid
                ][src.dpid] = dst.port_no

                new_link_ports[
                    (src.dpid, dst.dpid)
                ] = src.port_no

            if self.topology != new_topology:

                self.topology_last_change = time.monotonic()

            self.topology = new_topology

            self.reverse_topology = new_reverse

            self.link_ports = new_link_ports

            LOG.info(
                "🗺️ Topology refreshed: %d switches / %d links",
                len(switches),
                len(links),
            )

            # Report observed topology only; desired topology remains owned by
            # the backend's persistent topology configuration.
            dash(
                "/api/topology/runtime",
                {
                    "switches": sorted(sw.dp.id for sw in switches),
                    "links": sorted(
                        [link.src.dpid, link.dst.dpid]
                        for link in links
                    ),
                    "stable_seconds": max(
                        0.0,
                        time.monotonic() - self.topology_last_change,
                    ),
                    "reported_at": time.time(),
                },
            )

        except Exception as e:

            LOG.exception(
                "Topology refresh failed: %s",
                e
            )

    # =================================================================
    # PERIODIC TOPOLOGY REFRESH
    # =================================================================

    def _topology_refresh_loop(self):

        while True:

            try:

                self._refresh_topology()

            except Exception:

                LOG.exception(
                    "Unexpected topology refresh loop error"
                )

            hub.sleep(5)

    # =================================================================
    # PACKET IN
    # =================================================================

    @set_ev_cls(
        ofp_event.EventOFPPacketIn,
        MAIN_DISPATCHER
    )
    def packet_in_handler(self, ev):

        msg = ev.msg

        dp = msg.datapath

        ofp = dp.ofproto

        parser = dp.ofproto_parser

        dpid = dp.id

        try:

            in_port = msg.match["in_port"]

        except Exception:

            return

        pkt = packet.Packet(
            msg.data
        )

        eth = pkt.get_protocol(
            ethernet.ethernet
        )

        if not eth:

            return

        # Ignore LLDP from normal host learning.
        if eth.ethertype == 0x88cc:

            return

        src_mac = eth.src

        dst_mac = eth.dst

        # =============================================================
        # IP / ARP INFORMATION
        # =============================================================

        ip_pkt = pkt.get_protocol(
            ipv4.ipv4
        )

        arp_pkt = pkt.get_protocol(
            arp.arp
        )

        # =============================================================
        # LEARN SOURCE MAC
        # =============================================================

        self.mac_to_port[
            dpid
        ][src_mac] = in_port

        # =============================================================
        # LEARN HOST LOCATION
        # =============================================================

        if self._is_host_port(
            dpid,
            in_port
        ):

            host_info = {
                "dpid": dpid,
                "port": in_port,
                "ip": None,
            }

            if ip_pkt:

                host_info["ip"] = ip_pkt.src

                self.ip_location[
                    ip_pkt.src
                ] = (
                    dpid,
                    in_port
                )

                self.port_ip_map[
                    (dpid, in_port)
                ] = ip_pkt.src

            elif arp_pkt:

                host_info["ip"] = arp_pkt.src_ip

                if arp_pkt.src_ip:

                    self.ip_location[
                        arp_pkt.src_ip
                    ] = (
                        dpid,
                        in_port
                    )

                    self.port_ip_map[
                        (dpid, in_port)
                    ] = arp_pkt.src_ip

            self.host_location[
                src_mac
            ] = host_info

            LOG.debug(
                "🏠 Host learned: %s -> s%s:%s ip=%s",
                src_mac,
                dpid,
                in_port,
                host_info["ip"],
            )

        # =============================================================
        # ML CONTEXT
        # =============================================================

        if ip_pkt:

            proto_num = ip_pkt.proto

            dst_p = 0

            tcp_pkt = pkt.get_protocol(
                tcp.tcp
            )

            udp_pkt = pkt.get_protocol(
                udp.udp
            )

            if tcp_pkt:

                dst_p = tcp_pkt.dst_port

            elif udp_pkt:

                dst_p = udp_pkt.dst_port

            key = (
                dpid,
                in_port
            )

            self.port_context[key] = {
                "dst_port": dst_p,
                "proto": proto_num,
            }

            self.port_ip_map[key] = ip_pkt.src

            # ---------------------------------------------------------
            # ACL
            # ---------------------------------------------------------

            if self._is_ip_blocked(
                ip_pkt.src
            ):

                LOG.warning(
                    "🚫 Dropping blocked IP %s at s%s:%s",
                    ip_pkt.src,
                    dpid,
                    in_port,
                )

                return

        # =============================================================
        # DESTINATION BLOCK CHECK
        # =============================================================

        if ip_pkt:

            if self._is_ip_blocked(
                ip_pkt.dst
            ):

                return

        # =============================================================
        # FORWARD PACKET
        # =============================================================

        out_port = self._get_output_port(
            dpid,
            in_port,
            dst_mac
        )

        # =============================================================
        # UNKNOWN DESTINATION
        # =============================================================

        if out_port is None:

            flood_ports = self._get_flood_ports(
                dp,
                in_port
            )

            LOG.debug(
                "Flood s%s:%s -> %s",
                dpid,
                in_port,
                ", ".join(
                    "%s(%s)" % (port, role)
                    for port, role in flood_ports
                ) or "drop(topology-not-ready)",
            )

            actions = [
                parser.OFPActionOutput(port)
                for port, _ in flood_ports
            ]

            if not actions:

                return

        else:

            actions = [
                parser.OFPActionOutput(
                    out_port
                )
            ]

        # =============================================================
        # INSTALL LOCAL LEARNING FLOW
        # =============================================================

        if (
            out_port is not None
            and out_port != ofp.OFPP_ALL
            and out_port != ofp.OFPP_NORMAL
        ):

            match = parser.OFPMatch(
                in_port=in_port,
                eth_dst=dst_mac
            )

            self._add_flow(
                dp,
                priority=100,
                match=match,
                actions=actions,
                idle_timeout=60,
                hard_timeout=0,
            )

        # =============================================================
        # SEND PACKET OUT
        # =============================================================

        data = None

        if msg.buffer_id == ofp.OFP_NO_BUFFER:

            data = msg.data

        packet_out = parser.OFPPacketOut(
            datapath=dp,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=data,
        )

        dp.send_msg(
            packet_out
        )

    # =================================================================
    # DETERMINE HOST PORT
    # =================================================================

    def _is_host_port(
        self,
        dpid,
        port
    ):
        """
        Determine whether a port is a host-facing port.

        We use the topology graph to distinguish switch-to-switch
        ports from host ports.

        If a port is NOT used by a known switch-to-switch link,
        it is considered a possible host port.
        """

        # Local port is not a host port.
        if port == LOCAL_PORT:

            return False

        # Check switch-to-switch links.
        for neighbor, link_port in self.topology.get(
            dpid,
            {}
        ).items():

            if link_port == port:

                return False

        return True

    # =================================================================
    # LOOP-FREE FLOODING
    # =================================================================

    def _get_spanning_tree_edges(self):
        """Return a deterministic BFS tree for a stable topology."""

        if (
            time.monotonic()
            - self.topology_last_change
            < FLOOD_TOPOLOGY_SETTLE_SECONDS
        ):

            return None

        nodes = set(self.datapaths)

        if not nodes:

            return None

        adjacency = defaultdict(set)

        for src in nodes:

            for dst in self.topology.get(src, {}):

                if dst not in nodes:

                    continue

                # Only use links discovered in both directions.
                if src not in self.topology.get(dst, {}):

                    return None

                adjacency[src].add(dst)

                adjacency[dst].add(src)

        root = min(nodes)

        visited = {root}

        queue = deque([root])

        tree_edges = set()

        while queue:

            current = queue.popleft()

            for neighbor in sorted(adjacency[current]):

                if neighbor in visited:

                    continue

                visited.add(neighbor)

                queue.append(neighbor)

                tree_edges.add(
                    (
                        min(current, neighbor),
                        max(current, neighbor),
                    )
                )

        if visited != nodes:

            return None

        return tree_edges

    # -----------------------------------------------------------------

    def _get_flood_ports(self, dp, in_port):
        """Return live host and spanning-tree ports, excluding ingress."""

        tree_edges = self._get_spanning_tree_edges()

        if tree_edges is None:

            return []

        dpid = dp.id

        ofp = dp.ofproto

        link_ports = set(
            self.topology.get(dpid, {}).values()
        )

        selected = {}

        for neighbor, port in self.topology.get(dpid, {}).items():

            edge = (
                min(dpid, neighbor),
                max(dpid, neighbor),
            )

            if edge in tree_edges:

                selected[port] = "spanning-tree"

        invalid_state = (
            ofp.OFPPS_LINK_DOWN
            |
            getattr(ofp, "OFPPS_BLOCKED", 0)
        )

        for port, description in dp.ports.items():

            if port >= ofp.OFPP_MAX or port in link_ports:

                continue

            if description.state & invalid_state:

                continue

            selected[port] = "host"

        return [
            (port, selected[port])
            for port in sorted(selected)
            if port != in_port
            and port in dp.ports
            and not (dp.ports[port].state & invalid_state)
        ]

    # =================================================================
    # GET OUTPUT PORT
    # =================================================================

    def _get_output_port(
        self,
        dpid,
        in_port,
        dst_mac
    ):
        """
        Dynamic forwarding decision.

        Priority:

        1. Destination host location
        2. Existing MAC learning
        3. Flood
        """

        # =============================================================
        # LOCAL MAC
        # =============================================================

        if dst_mac == "00:00:00:00:00:00":

            return None

        # =============================================================
        # DESTINATION HOST KNOWN
        # =============================================================

        destination = self.host_location.get(
            dst_mac
        )

        if destination:

            dst_dpid = destination["dpid"]

            dst_port = destination["port"]

            # ---------------------------------------------------------
            # Same switch
            # ---------------------------------------------------------

            if dst_dpid == dpid:

                if dst_port != in_port:

                    return dst_port

                return None

            # ---------------------------------------------------------
            # Different switch
            # ---------------------------------------------------------

            next_hop = self._get_next_hop(
                dpid,
                dst_dpid
            )

            if next_hop is not None:

                return next_hop

        # =============================================================
        # FALLBACK: LOCAL MAC LEARNING
        # =============================================================

        learned_port = self.mac_to_port.get(
            dpid,
            {}
        ).get(
            dst_mac
        )

        if learned_port is not None:

            if learned_port != in_port:

                return learned_port

        return None

    # =================================================================
    # SHORTEST PATH
    # =================================================================

    def _get_next_hop(
        self,
        src_dpid,
        dst_dpid
    ):
        """
        BFS shortest path.

        Returns the outgoing port from src_dpid
        toward dst_dpid.
        """

        if src_dpid == dst_dpid:

            return None

        queue = deque()

        queue.append(
            (
                src_dpid,
                None
            )
        )

        visited = {
            src_dpid
        }

        parent = {}

        while queue:

            current, _ = queue.popleft()

            neighbors = self.topology.get(
                current,
                {}
            )

            for neighbor, out_port in neighbors.items():

                if neighbor in visited:

                    continue

                visited.add(
                    neighbor
                )

                parent[
                    neighbor
                ] = (
                    current,
                    out_port
                )

                if neighbor == dst_dpid:

                    # -------------------------------------------------
                    # Reconstruct first hop
                    # -------------------------------------------------

                    node = dst_dpid

                    while parent[node][0] != src_dpid:

                        node = parent[node][0]

                    return parent[node][1]

                queue.append(
                    (
                        neighbor,
                        out_port
                    )
                )

        return None

    # =================================================================
    # DATASET TOPOLOGY GATE
    # =================================================================

    def _dataset_window_ready(self, window_start):
        """Return True only for a full polling window after convergence."""

        if not self.dataset_recorder.enabled:

            return False

        directed_links = sum(
            len(neighbors)
            for neighbors in self.topology.values()
        )

        stable_seconds = max(
            0.0,
            time.monotonic() - self.topology_last_change,
        )

        topology_ready = (
            len(self.datapaths) == DATASET_REQUIRED_SWITCHES
            and directed_links == DATASET_REQUIRED_DIRECTED_LINKS
            and stable_seconds >= FLOOD_TOPOLOGY_SETTLE_SECONDS
        )

        if not topology_ready:

            self.dataset_topology_ready_since = None

        elif self.dataset_topology_ready_since is None:

            self.dataset_topology_ready_since = time.time()

            LOG.info(
                "SDN dataset topology gate ready: switches=%s links=%s",
                len(self.datapaths),
                directed_links,
            )

        window_ready = (
            topology_ready
            and self.dataset_topology_ready_since is not None
            and window_start >= self.dataset_topology_ready_since
        )

        self.dataset_recorder.update_topology_status(
            ready=window_ready,
            datapaths=len(self.datapaths),
            directed_links=directed_links,
            stable_seconds=stable_seconds,
        )

        return window_ready

    # =================================================================
    # PORT STATS
    # =================================================================

    @set_ev_cls(
        ofp_event.EventOFPPortStatsReply,
        MAIN_DISPATCHER
    )
    def port_stats_reply_handler(
        self,
        ev
    ):

        dp = ev.msg.datapath

        dpid = dp.id

        now = time.time()

        for stat in ev.msg.body:

            port = stat.port_no

            # ---------------------------------------------------------
            # Ignore invalid / excessive port numbers.
            # ---------------------------------------------------------

            if (
                port > 1000
                and port != LOCAL_PORT
            ):

                continue

            key = (
                dpid,
                port
            )

            if key in self.prev_stats:

                prev = self.prev_stats[key]

                dt = (
                    now -
                    prev["time"]
                )

                if dt <= 0:

                    continue

                rx_packets_delta = (
                    stat.rx_packets -
                    prev["rx_pkts"]
                )

                rx_bytes_delta = (
                    stat.rx_bytes -
                    prev["rx_bytes"]
                )

                tx_packets_delta = (
                    stat.tx_packets -
                    prev["tx_pkts"]
                )

                tx_bytes_delta = (
                    stat.tx_bytes -
                    prev["tx_bytes"]
                )

                rx_pps = rx_packets_delta / dt

                rx_bps = rx_bytes_delta / dt

                tx_pps = tx_packets_delta / dt

                tx_bps = tx_bytes_delta / dt

                # -----------------------------------------------------
                # Source IP associated with this port
                # -----------------------------------------------------

                src_ip = self.port_ip_map.get(
                    key
                )

                if self._dataset_window_ready(
                    prev["time"]
                ):

                    dataset_context = self.port_context.get(
                        key,
                        {}
                    )

                    self.dataset_recorder.enqueue(
                        {
                            "window_start": prev["time"],
                            "window_end": now,
                            "dpid": dpid,
                            "port": port,
                            "interval_seconds": dt,
                            "rx_packets_delta": rx_packets_delta,
                            "tx_packets_delta": tx_packets_delta,
                            "rx_bytes_delta": rx_bytes_delta,
                            "tx_bytes_delta": tx_bytes_delta,
                            "rx_pps": rx_pps,
                            "tx_pps": tx_pps,
                            "rx_bytes_per_sec": rx_bps,
                            "tx_bytes_per_sec": tx_bps,
                            "last_protocol": dataset_context.get(
                                "proto",
                                ""
                            ),
                            "last_dst_port": dataset_context.get(
                                "dst_port",
                                ""
                            ),
                            "last_source_ip": src_ip or "",
                        }
                    )

                is_blocked = (
                    src_ip is not None
                    and src_ip in self.blocked_ips
                )

                display_pps = (
                    0
                    if is_blocked
                    else rx_pps
                )

                display_bps = (
                    0
                    if is_blocked
                    else rx_bps
                )

                display_port = (
                    "kali"
                    if port == LOCAL_PORT
                    else port
                )

                # -----------------------------------------------------
                # DASHBOARD
                # -----------------------------------------------------

                dash(
                    "/api/traffic",
                    {
                        "port": display_port,
                        "pps": round(
                            display_pps,
                            1
                        ),
                        "bps": round(
                            display_bps / 1024,
                            1
                        ),
                    },
                )

                # -----------------------------------------------------
                # DATABASE
                # -----------------------------------------------------

                if (
                    HAS_DB
                    and int(now) % 3 == 0
                    and port != LOCAL_PORT
                ):

                    try:

                        db.log_traffic(
                            port,
                            display_pps,
                            display_bps / 1024
                        )

                    except Exception as e:

                        LOG.debug(
                            "DB traffic error: %s",
                            e
                        )

                # -----------------------------------------------------
                # LSTM DETECTION
                # -----------------------------------------------------

                detect_pps = rx_pps

                if (
                    not is_blocked
                    and detect_pps
                ):

                    if (
                        detect_pps >
                        MIN_PPS_CHECK
                        and self._warmup_done()
                    ):

                        ctx = self.port_context.get(
                            key,
                            {
                                "dst_port": 0,
                                "proto": 6,
                            }
                        )

                        pkt_count = int(
                            stat.rx_packets -
                            prev["rx_pkts"]
                        )

                        byte_count = int(
                            stat.rx_bytes -
                            prev["rx_bytes"]
                        )

                        self._lstm_check(
                            dp,
                            port,
                            detect_pps,
                            rx_bps,
                            dt,
                            pkt_count,
                            byte_count,
                            ctx["dst_port"],
                            ctx["proto"],
                        )

                    else:

                        self.alert_counts.pop(
                            key,
                            None
                        )

            self.prev_stats[key] = {
                "time": now,
                "rx_pkts": stat.rx_packets,
                "rx_bytes": stat.rx_bytes,
                "tx_pkts": stat.tx_packets,
                "tx_bytes": stat.tx_bytes,
            }

    # =================================================================
    # LSTM
    # =================================================================

    def _lstm_check(
        self,
        dp,
        port,
        pps,
        bps,
        duration,
        pkt_count,
        byte_count,
        dst_port,
        protocol,
    ):

        key = (
            dp.id,
            port
        )

        # =============================================================
        # FALLBACK
        # =============================================================

        if not self.model:

            if pps > FALLBACK_PPS_THRESHOLD:

                self.alert_counts[key] = (
                    self.alert_counts.get(
                        key,
                        0
                    ) + 1
                )

                if (
                    self.alert_counts[key]
                    >= CONSECUTIVE_HITS
                ):

                    self._take_action(
                        dp,
                        port,
                        "DDoS-Fallback",
                        0.99,
                        pps,
                        bps,
                    )

            return

        # =============================================================
        # MODEL PREDICTION
        # =============================================================

        try:

            duration_us = (
                duration *
                1_000_000
            )

            iat_mean = (
                duration_us /
                max(
                    pkt_count,
                    1
                )
            )

            features = np.array(
                [[
                    dst_port,
                    protocol,
                    duration_us,
                    pkt_count,
                    0,
                    byte_count,
                    0,
                    bps,
                    pps,
                    iat_mean,
                ]]
            )

            if self.scaler is None:

                LOG.error(
                    "❌ Scaler is not loaded"
                )

                return

            scaled = self.scaler.transform(
                features
            )

            lstm_input = np.reshape(
                scaled,
                (
                    1,
                    1,
                    scaled.shape[1]
                )
            )

            pred = self.model.predict(
                lstm_input,
                verbose=0
            )

            idx = int(
                np.argmax(
                    pred[0]
                )
            )

            conf = float(
                pred[0][idx]
            )

            if self.le is not None:

                label = str(
                    self.le.inverse_transform(
                        [idx]
                    )[0]
                )

            else:

                label = str(
                    idx
                )

            LOG.info(
                "[LSTM] s%s:%s label='%s' conf=%.4f pps=%.1f hits=%s",
                dp.id,
                port,
                label,
                conf,
                pps,
                self.alert_counts.get(
                    key,
                    0
                ),
            )

            # ---------------------------------------------------------
            # DASHBOARD ML
            # ---------------------------------------------------------

            dash(
                "/api/ml",
                {
                    "port": port,
                    "pred": label,
                    "conf": conf,
                },
            )

            # ---------------------------------------------------------
            # ATTACK DECISION
            # ---------------------------------------------------------

            is_attack = (
                (
                    conf >= BLOCK_THRESHOLD
                    and
                    label.lower() != "benign"
                )
                or
                pps > 10000
            )

            if is_attack:

                self.alert_counts[key] = (
                    self.alert_counts.get(
                        key,
                        0
                    ) + 1
                )

                LOG.info(
                    "[ALERT] s%s:%s consecutive hit #%s/%s",
                    dp.id,
                    port,
                    self.alert_counts[key],
                    CONSECUTIVE_HITS,
                )

                if (
                    self.alert_counts[key]
                    >= CONSECUTIVE_HITS
                ):

                    if (
                        pps > 10000
                        and
                        (
                            conf < BLOCK_THRESHOLD
                            or
                            label.lower()
                            == "benign"
                        )
                    ):

                        LOG.warning(
                            "🚨 HARD LIMIT reached on s%s:%s",
                            dp.id,
                            port,
                        )

                        self._take_action(
                            dp,
                            port,
                            "DDoS-Anomaly",
                            0.99,
                            pps,
                            bps,
                        )

                    else:

                        self._take_action(
                            dp,
                            port,
                            label,
                            conf,
                            pps,
                            bps,
                        )

            else:

                self.alert_counts.pop(
                    key,
                    None
                )

        except Exception as e:

            LOG.error(
                "❌ Prediction Error: %s",
                e,
            )

    # =================================================================
    # TAKE ACTION
    # =================================================================

    def _take_action(
        self,
        dp,
        port,
        label,
        conf,
        pps,
        bps,
    ):

        key = (
            dp.id,
            port
        )

        src_ip = self.port_ip_map.get(
            key
        )

        if not src_ip:

            LOG.warning(
                "⚠️ Cannot block s%s:%s - no IP mapped",
                dp.id,
                port,
            )

            return

        LOG.warning(
            "🚨 AI Prediction: %s conf=%.4f src_ip=%s",
            label,
            conf,
            src_ip,
        )

        # =============================================================
        # ACL
        # =============================================================
        normalized_label = label.lower().replace("-", "").replace("_", "")
        if normalized_label == "udplag":
            self._rate_limit_ip(
                src_ip,
                port,
                conf
            )
        else:
            self._block_ip(
                src_ip,
                port,
                conf,
                label
            )

        # =============================================================
        # NOTIFICATION
        # =============================================================

        if HAS_NOTIFY:

            try:

                notify_attack(
                    port,
                    pps,
                    conf
                )

            except Exception:

                pass

        # =============================================================
        # DATABASE
        # =============================================================

        if HAS_DB:

            try:

                db.log_attack(
                    port,
                    pps,
                    bps / 1024,
                    conf,
                    note=label,
                    attack_type=label,
                    dpid=dp.id,
                )

                db.block_port(
                    port,
                    conf,
                    BLOCK_DURATION
                )

            except Exception as e:

                LOG.debug(
                    "DB attack error: %s",
                    e
                )

        # =============================================================
        # DASHBOARD
        # =============================================================

        dash(
            "/api/attack",
            {
                "port": port,
                "ip": src_ip,
                "label": label,
                "conf": round(
                    conf,
                    2
                ),
                "pps": round(
                    pps,
                    1
                ),
            },
        )

        self.alert_counts.pop(
            key,
            None
        )

    # =================================================================
    # BLOCK IP
    # =================================================================

    def _block_ip(
        self,
        src_ip,
        port,
        conf,
        label=""
    ):
        """
        Block source IP dynamically on ALL connected switches.

        This is important because the attacker may be connected
        to s2/s3/s4 in Tree/Mesh topology.

        We therefore don't assume the attacker's traffic is on s1.
        """

        if src_ip in WHITELIST_IPS:

            LOG.warning(
                "⚠️ SKIP block: %s is whitelisted",
                src_ip,
            )

            return

        # -------------------------------------------------------------
        # Avoid duplicate block
        # -------------------------------------------------------------

        if src_ip in self.blocked_ips:

            return

        # -------------------------------------------------------------
        # Install ACL on every datapath
        # -------------------------------------------------------------

        for dpid, dp in list(
            self.datapaths.items()
        ):

            parser = dp.ofproto_parser

            # ---------------------------------------------------------
            # IPv4 source block
            # ---------------------------------------------------------

            match = parser.OFPMatch(
                eth_type=ETH_IP,
                ipv4_src=src_ip
            )

            self._add_flow(
                dp,
                priority=500,
                match=match,
                actions=[],
                idle_timeout=BLOCK_DURATION,
                hard_timeout=BLOCK_DURATION,
            )

        self.blocked_ips[src_ip] = {
            "time": time.time(),
            "dpid": None,
            "port": port,
            "label": label,
        }

        LOG.warning(
            "🚫 ACL BLOCK IP %s | attack=%s conf=%.2f",
            src_ip,
            label,
            conf,
        )

    # =================================================================
    # RATE LIMIT
    # =================================================================

    def _rate_limit_ip(
        self,
        src_ip,
        port,
        conf
    ):
        """
        Keep the original UDPLag behavior but make it topology-safe.

        NOTE:
        Queue 1 must exist in OVS for actual rate limiting.
        If queue 1 is not configured, traffic will still be forwarded
        normally rather than being sent to FLOOD.
        """

        if src_ip in WHITELIST_IPS:

            return

        # -------------------------------------------------------------
        # Mark as temporarily protected.
        # -------------------------------------------------------------

        self.blocked_ips[src_ip] = {
            "time": time.time(),
            "dpid": None,
            "port": port,
            "label": "UDPLag",
        }

        for dpid, dp in list(
            self.datapaths.items()
        ):

            parser = dp.ofproto_parser

            actions = [
                parser.OFPActionSetQueue(1),
                parser.OFPActionOutput(
                    dp.ofproto.OFPP_NORMAL
                ),
            ]

            match = parser.OFPMatch(
                eth_type=ETH_IP,
                ipv4_src=src_ip
            )

            self._add_flow(
                dp,
                priority=490,
                match=match,
                actions=actions,
                idle_timeout=BLOCK_DURATION,
                hard_timeout=BLOCK_DURATION,
            )

        LOG.warning(
            "🐌 ACL RATE-LIMIT IP %s (UDPLag)",
            src_ip
        )

    # =================================================================
    # UNBLOCK
    # =================================================================

    def _unblock_ip(
        self,
        src_ip,
        reason="expired"
    ):

        if src_ip not in self.blocked_ips:

            return

        info = self.blocked_ips[
            src_ip
        ]

        port = info.get(
            "port",
            0
        )

        # -------------------------------------------------------------
        # Delete ACL from ALL switches.
        # -------------------------------------------------------------

        for dpid, dp in list(
            self.datapaths.items()
        ):

            ofp = dp.ofproto

            parser = dp.ofproto_parser

            for priority in [
                490,
                500,
            ]:

                match = parser.OFPMatch(
                    eth_type=ETH_IP,
                    ipv4_src=src_ip
                )

                dp.send_msg(
                    parser.OFPFlowMod(
                        datapath=dp,
                        command=ofp.OFPFC_DELETE,
                        out_port=ofp.OFPP_ANY,
                        out_group=ofp.OFPG_ANY,
                        match=match,
                        priority=priority,
                    )
                )

        del self.blocked_ips[
            src_ip
        ]

        # -------------------------------------------------------------
        # Reset alert counters associated with this IP
        # -------------------------------------------------------------

        for key in list(
            self.alert_counts.keys()
        ):

            dpid, p = key

            mapped_ip = self.port_ip_map.get(
                key
            )

            if mapped_ip == src_ip:

                self.alert_counts.pop(
                    key,
                    None
                )

        # -------------------------------------------------------------
        # DB
        # -------------------------------------------------------------

        if HAS_DB:

            try:

                db.unblock_port(
                    port,
                    reason
                )

            except Exception:

                pass

        # -------------------------------------------------------------
        # Notification
        # -------------------------------------------------------------

        if HAS_NOTIFY:

            try:

                notify_unblock(
                    port,
                    reason
                )

            except Exception:

                pass

        # -------------------------------------------------------------
        # Dashboard
        # -------------------------------------------------------------

        dash(
            "/api/unblock",
            {
                "port": port,
                "ip": src_ip,
            }
        )

        LOG.info(
            "✅ ACL Unblocked IP %s (%s)",
            src_ip,
            reason,
        )

    # =================================================================
    # CHECK BLOCKED IP
    # =================================================================

    def _is_ip_blocked(
        self,
        src_ip
    ):

        if src_ip not in self.blocked_ips:

            return False

        info = self.blocked_ips[
            src_ip
        ]

        elapsed = (
            time.time()
            -
            info["time"]
        )

        if elapsed >= BLOCK_DURATION:

            self._unblock_ip(
                src_ip,
                reason="expired"
            )

            return False

        return True

    # =================================================================
    # WARMUP
    # =================================================================

    def _warmup_done(self):

        return (
            time.time()
            -
            self.startup_time
        ) >= WARMUP_SECONDS

    # =================================================================
    # LOAD ACTIVE MODEL
    # =================================================================

    def _load_active_model(self):

        m_path = MODEL_PATH

        s_path = SCALER_PATH

        l_path = LE_PATH

        # -------------------------------------------------------------
        # Load active model from database
        # -------------------------------------------------------------

        if HAS_DB:

            try:

                active_model = (
                    db.get_active_model()
                )

                if active_model:

                    m_path = active_model.get(
                        "file_path",
                        m_path
                    )

                    s_path = active_model.get(
                        "scaler_path",
                        s_path
                    )

                    l_path = active_model.get(
                        "le_path",
                        l_path
                    )

                    self.active_model_id = (
                        active_model.get(
                            "id"
                        )
                    )

            except Exception as e:

                LOG.error(
                    "❌ Failed to fetch active model: %s",
                    e
                )

        # -------------------------------------------------------------
        # Load model
        # -------------------------------------------------------------

        try:

            self.model = (
                tf.keras.models.load_model(
                    m_path
                )
            )

            self.scaler = (
                joblib.load(
                    s_path
                )
                if s_path
                else None
            )

            self.le = (
                joblib.load(
                    l_path
                )
                if l_path
                else None
            )

            LOG.info(
                "=================================================="
            )

            LOG.info(
                "✅ LSTM model loaded"
            )

            LOG.info(
                "Model ID: %s",
                self.active_model_id
            )

            LOG.info(
                "Model: %s",
                m_path
            )

            LOG.info(
                "Scaler: %s",
                s_path
            )

            LOG.info(
                "Label Encoder: %s",
                l_path
            )

            LOG.info(
                "=================================================="
            )

        except Exception as e:

            self.model = None

            self.scaler = None

            self.le = None

            LOG.error(
                "❌ Model Load Error: %s",
                e
            )

    # =================================================================
    # MODEL CHECK LOOP
    # =================================================================

    def _model_check_loop(self):

        while True:

            if HAS_DB:

                try:

                    active_model = (
                        db.get_active_model()
                    )

                    if active_model:

                        new_id = (
                            active_model.get(
                                "id"
                            )
                        )

                        if (
                            new_id
                            !=
                            self.active_model_id
                        ):

                            LOG.info(
                                "🔄 Active model changed "
                                "%s -> %s",
                                self.active_model_id,
                                new_id,
                            )

                            self._load_active_model()

                except Exception:

                    LOG.exception(
                        "Active-model check failed"
                    )

            hub.sleep(10)

    # =================================================================
    # PORT MONITOR LOOP
    # =================================================================

    def _monitor_loop(self):

        while True:

            try:

                datapaths = list(
                    self.datapaths.values()
                )

            except Exception:

                LOG.exception(
                    "Failed to snapshot datapaths for port monitoring"
                )

                datapaths = []

            for dp in datapaths:

                try:

                    parser = (
                        dp.ofproto_parser
                    )

                    request = (
                        parser.OFPPortStatsRequest(
                            dp,
                            0,
                            dp.ofproto.OFPP_ANY
                        )
                    )

                    dp.send_msg(
                        request
                    )

                except Exception as e:

                    LOG.exception(
                        "Port stats request failed for datapath %s: %s",
                        getattr(dp, "id", "unknown"),
                        e
                    )

            hub.sleep(
                STATS_INTERVAL
            )

    # =================================================================
    # UNBLOCK LOOP
    # =================================================================

    def _unblock_loop(self):

        while True:

            # ---------------------------------------------------------
            # 1. Expired blocks
            # ---------------------------------------------------------

            for ip in list(
                self.blocked_ips
            ):

                try:

                    self._is_ip_blocked(
                        ip
                    )

                except Exception:

                    LOG.exception(
                        "Block-state check failed for IP %s",
                        ip,
                    )

            # ---------------------------------------------------------
            # 2. Admin IPC
            # ---------------------------------------------------------

            ipc_path = (
                "/tmp/unblock_requests.txt"
            )

            if os.path.exists(
                ipc_path
            ):

                try:

                    with open(
                        ipc_path,
                        "r"
                    ) as f:

                        ips = [
                            line.strip()
                            for line in f
                            if line.strip()
                        ]

                    # Clear IPC file

                    open(
                        ipc_path,
                        "w"
                    ).close()

                    for ip in ips:

                        if (
                            ip
                            in
                            self.blocked_ips
                        ):

                            LOG.info(
                                "📬 Admin unblock: %s",
                                ip
                            )

                            self._unblock_ip(
                                ip,
                                reason="admin"
                            )

                except Exception as e:

                    LOG.exception(
                        "❌ Admin unblock IPC error: %s",
                        e
                    )

            hub.sleep(2)

    # =================================================================
    # FLOW INSTALLER
    # =================================================================

    def _add_flow(
        self,
        dp,
        priority,
        match,
        actions,
        idle_timeout=0,
        hard_timeout=0
    ):

        ofp = dp.ofproto

        parser = dp.ofproto_parser

        instructions = [
            parser.OFPInstructionActions(
                ofp.OFPIT_APPLY_ACTIONS,
                actions
            )
        ]

        flow_mod = parser.OFPFlowMod(
            datapath=dp,
            priority=priority,
            match=match,
            instructions=instructions,
            idle_timeout=idle_timeout,
            hard_timeout=hard_timeout,
        )

        dp.send_msg(
            flow_mod
        )


# =====================================================================
# END
# =====================================================================
from flask import Flask, jsonify, request, Response
from flask_cors import CORS
from werkzeug.utils import secure_filename
import threading, time, json, os, subprocess, csv, io
from collections import deque
from datetime import datetime

app = Flask(__name__)
CORS(app)

# ─── Model Uploads Setup ───
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ml', 'model', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# ─── Shared state ───
traffic_history = deque(maxlen=60)
blocked_ips     = {}
attack_log      = deque(maxlen=100)
port_stats      = {}
ml_stats        = {}

topology_status = {'state': 'idle', 'topology': 'default', 'message': ''}

# path ของ Python ที่ใช้รัน Mininet (pyenv)
PYTHON_BIN  = '/home/beepbeep-kun/.pyenv/versions/sdn-env38/bin/python'
TOPO_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'topology', 'network_topology.py')

# ─── Ryu POST endpoints ───
@app.route('/api/traffic', methods=['POST'])
def api_traffic():
    d = request.json
    port, pps, bps = d['port'], d['pps'], d['bps']
    ts = datetime.now().strftime('%H:%M:%S')
    traffic_history.append({'time': ts, 'port': port, 'pps': round(pps,1), 'bps': round(bps,1)})
    port_stats[str(port)] = {'pps': round(pps,1), 'bps': round(bps,1)}
    # บันทึกลง DB ด้วย (fallback กรณี Ryu HAS_DB=False)
    try:
        import db_manager as db
        db.log_traffic(port, pps, bps)
    except Exception:
        pass
    return jsonify({'ok': True})

@app.route('/api/attack', methods=['POST'])
def api_attack():
    d = request.json
    port, ip, conf = d['port'], d['ip'], d['conf']
    ts = datetime.now().strftime('%H:%M:%S')
    blocked_ips[ip] = {'time': ts, 'port': port, 'conf': round(conf*100,1), 'expire': time.time()+60}
    attack_log.appendleft({'time': ts, 'port': port, 'ip': ip, 'conf': round(conf*100,1)})
    ml_stats[str(port)] = {'pred': 1, 'conf': round(conf*100,1)}
    # บันทึกลง DB (fallback กรณี Ryu HAS_DB=False)
    try:
        import db_manager as db
        attack_type = d.get('label', 'Unknown')
        pps_val = d.get('pps', 0)
        bps_val = d.get('bps', 0)
        db.log_attack(port, pps_val, bps_val, conf, note=attack_type, attack_type=attack_type)
        db.block_port(port, conf, 60)
    except Exception:
        pass
    return jsonify({'ok': True})

@app.route('/api/ml', methods=['POST'])
def api_ml():
    d = request.json
    ml_stats[str(d['port'])] = {'pred': d['pred'], 'conf': round(d['conf']*100,1)}
    return jsonify({'ok': True})

# ─── Dashboard polling endpoint ───
@app.route('/api/state')
def api_state():
    now = time.time()
    expired = [ip for ip, v in blocked_ips.items() if now > v['expire']]
    for ip in expired:
        del blocked_ips[ip]
    return jsonify({
        'traffic': list(traffic_history)[-20:],
        'blocked': [{'ip': k, **v} for k, v in blocked_ips.items()],
        'log':     list(attack_log)[:20],
        'ports':   port_stats,
        'ml':      ml_stats,
    })

@app.route('/')
def index():
    return open('dashboard.html').read()

# ── DB endpoints ──
@app.route('/api/db/attacks')
def api_db_attacks():
    try:
        import db_manager as db
        return jsonify(db.get_attack_log(50))
    except:
        return jsonify([])

@app.route('/api/db/blocked')
def api_db_blocked():
    try:
        import db_manager as db
        return jsonify(db.get_blocked_ports())
    except:
        return jsonify([])

@app.route('/api/db/summary')
def api_db_summary():
    try:
        import db_manager as db
        return jsonify(db.get_stats_summary())
    except:
        return jsonify({})

@app.route('/api/db/traffic')
def api_db_traffic():
    try:
        import db_manager as db
        port = request.args.get('port', type=int)
        return jsonify(db.get_traffic_history(port, minutes=10))
    except:
        return jsonify([])

@app.route('/api/unblock', methods=['POST'])
def api_unblock():
    try:
        data = request.get_json(force=True) or {}
        port = int(data.get('port', 0))
        key  = f'port-{port}'
        if key in blocked_ips:
            del blocked_ips[key]
        try:
            import db_manager as db
            db.unblock_port(port, 'manual')
        except:
            pass
        return jsonify({'ok': True, 'port': port})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

@app.route('/api/unblock/<int:port>', methods=['POST'])
def api_unblock_port(port):
    try:
        key = f'port-{port}'
        if key in blocked_ips:
            del blocked_ips[key]
        try:
            import db_manager as db
            db.unblock_port(port, 'manual')
        except:
            pass
        return jsonify({'ok': True, 'port': port})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

@app.route('/api/feature_importance')
def api_feature_importance():
    result = [
        {'feature': 'Flow Packets/s',              'label': 'packet ต่อวินาที',      'importance': 28.5},
        {'feature': 'Flow Bytes/s',                'label': 'byte ต่อวินาที',        'importance': 22.3},
        {'feature': 'Flow IAT Mean',               'label': 'IAT เฉลี่ย',            'importance': 18.7},
        {'feature': 'Total Fwd Packets',           'label': 'packet ขาออกรวม',       'importance': 12.4},
        {'feature': 'Total Length of Fwd Packets', 'label': 'byte ขาออกรวม',         'importance': 8.6},
        {'feature': 'Flow Duration',               'label': 'ระยะเวลา flow',         'importance': 4.8},
        {'feature': 'Protocol',                    'label': 'protocol',              'importance': 2.5},
        {'feature': 'Destination Port',            'label': 'destination port',      'importance': 1.6},
        {'feature': 'Total Backward Packets',      'label': 'packet ขาเข้ารวม',      'importance': 0.6},
    ]
    return jsonify(result)

# ─── Topology Management ───

@app.route('/api/topology/status')
def api_topology_status():
    return jsonify(topology_status)

@app.route('/api/topology/apply', methods=['POST'])
def api_topology_apply():
    global topology_status
    try:
        data = request.json
        topo_type = data.get('topology', 'default')

        if topology_status['state'] == 'restarting':
            return jsonify({'ok': False, 'error': 'Topology change already in progress'}), 409

        # 1. เขียนไฟล์ก่อน (sync)
        write_topology_file(topo_type)

        # บันทึก topology event
        try:
            import db_manager as db
            db.log_topology_event(topo_type, 'apply', f'User applied {topo_type} topology')
        except Exception:
            pass

        # 2. เคลียร์ stats เก่า
        port_stats.clear()
        ml_stats.clear()
        traffic_history.clear()

        # 3. restart Mininet ใน background thread
        #    Ryu watchdog จะ restart Ryu เองอัตโนมัติหลัง mn -c
        threading.Thread(target=_restart_mininet, args=(topo_type,), daemon=True).start()

        return jsonify({'ok': True, 'topology': topo_type})

    except Exception as e:
        topology_status = {'state': 'error', 'topology': '', 'message': str(e)}
        return jsonify({'ok': False, 'error': str(e)}), 500


def _full_cleanup():
    """ลบซาก veth / OVS ให้หมดก่อนสร้าง topology ใหม่"""
    # 1. mn -c มาตรฐาน
    subprocess.run(['sudo', 'mn', '-c'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    # 2. ลบ veth pair ที่ค้างอยู่ (mn -c มักข้ามไป)
    try:
        out = subprocess.check_output(['ip', 'link', 'show'], text=True, stderr=subprocess.DEVNULL)
        for line in out.splitlines():
            if ': ' in line:
                iface = line.split(': ')[1].split('@')[0].strip()
                if (iface.startswith('h') or iface.startswith('s')) and '-eth' in iface:
                    subprocess.run(['sudo', 'ip', 'link', 'delete', iface],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    # 3. ลบ OVS bridge ที่เหลือ
    try:
        brs = subprocess.check_output(['sudo', 'ovs-vsctl', 'list-br'],
                                      text=True, stderr=subprocess.DEVNULL)
        for br in brs.strip().splitlines():
            if br:
                subprocess.run(['sudo', 'ovs-vsctl', 'del-br', br],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    # 4. รีสตาร์ท OVS ให้ clean state
    subprocess.run(['sudo', 'systemctl', 'restart', 'openvswitch-switch'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
    time.sleep(2)  # รอ OVS พร้อม


def _restart_mininet(topo_type):
    global topology_status
    WAIT_RYU_RESTART = 8   # วินาทีที่รอให้ Ryu watchdog restart เสร็จ
    LOG_FILE = '/tmp/mininet_last.log'

    try:
        # ── Step 1: ฆ่า Mininet เดิม ──
        topology_status = {'state': 'restarting', 'topology': topo_type, 'message': 'Stopping old Mininet...'}
        print(f"[Topo] Step1: killing old network_topology.py")

        subprocess.run(['sudo', 'pkill', '-TERM', '-f', 'network_topology.py'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        for _ in range(10):
            r = subprocess.run(['pgrep', '-f', 'network_topology.py'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if r.returncode != 0:
                break
            time.sleep(0.5)
        else:
            subprocess.run(['sudo', 'pkill', '-KILL', '-f', 'network_topology.py'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1)

        # ── Step 2: เคลียร์แบบจัดเต็ม (ไม่ใช่แค่ mn -c) ──
        topology_status['message'] = 'Full cleanup: removing veth pairs & OVS bridges...'
        print(f"[Topo] Step2: full cleanup")
        _full_cleanup()

        # ── Step 3: รอให้ Ryu listen บน port 6653 (OpenFlow) จริงๆ ──
        topology_status['message'] = 'Waiting for Ryu to come back on :6653...'
        print(f"[Topo] Step3: polling for Ryu on :6653 (max 45s)")
        import socket
        ryu_up = False
        for i in range(45):
            try:
                s = socket.create_connection(('127.0.0.1', 6653), timeout=1)
                s.close()
                ryu_up = True
                print(f"[Topo] Ryu is up after {i+1}s")
                break
            except (ConnectionRefusedError, OSError):
                time.sleep(1)

        if not ryu_up:
            topology_status = {'state': 'error', 'topology': topo_type,
                               'message': 'Ryu ไม่กลับมาใน 45 วินาที — ตรวจสอบ ryu_watchdog.sh'}
            print("[Topo] ERROR: Ryu never came back on :6653")
            return

        # ── Step 4: รัน Mininet ใหม่ ──
        topology_status['message'] = f'Starting new {topo_type} topology...'
        print(f"[Topo] Step4: launching new Mininet ({topo_type})")

        # ส่ง TOPO_TYPE ให้ Ryu controller รู้ว่าต้อง install flows แบบไหน
        # Ryu watchdog จะ restart Ryu เองและ Ryu จะอ่าน env var นี้
        env = os.environ.copy()
        env['TOPO_TYPE'] = topo_type

        # pkill ryu-manager เพื่อให้ watchdog restart พร้อม env ใหม่
        subprocess.run(['pkill', '-f', 'ryu-manager'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)  # รอ watchdog restart

        log_f = open(LOG_FILE, 'w')
        proc = subprocess.Popen(
            ['sudo', '-E', PYTHON_BIN, TOPO_SCRIPT, '--background'],
            stdout=log_f,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
        )

        # รอ 10 วินาที แล้วดูว่า process ยังอยู่ไหม
        time.sleep(10)
        if proc.poll() is not None:
            log_f.flush()
            try:
                with open(LOG_FILE) as lf:
                    err_tail = lf.read()[-600:]
            except Exception:
                err_tail = '(ไม่มี log)'
            topology_status = {'state': 'error', 'topology': topo_type,
                               'message': f'Mininet exited. Log: {err_tail}'}
            print(f"[Topo] ERROR: Mininet died. Log:\n{err_tail}")
            return

        topology_status = {'state': 'ready', 'topology': topo_type,
                           'message': f'{topo_type} topology running'}
        print(f"[Topo] ✅ Done — {topo_type} running")

    except subprocess.TimeoutExpired:
        topology_status = {'state': 'error', 'topology': topo_type, 'message': 'Cleanup timed out'}
    except Exception as e:
        topology_status = {'state': 'error', 'topology': topo_type, 'message': str(e)}
        print(f"[Topo] ERROR: {e}")


def write_topology_file(topo_type):
    header = """from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.log import setLogLevel, info
from mininet.link import TCLink
import sys, time

def run():
    setLogLevel('info')

    net = Mininet(controller=RemoteController, switch=OVSSwitch,
                  link=TCLink, autoSetMacs=True)

    info('*** Adding controller\\n')
    c0 = net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6653)

    info('*** Adding switches and hosts\\n')
"""

    footer = """
    info('*** Starting network\\n')
    net.start()

    info('*** Testing connectivity\\n')
    net.pingAll()

    import sys
    if '--background' in sys.argv:
        info('*** Network running in background...\\n')
        import time
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    else:
        info('*** Running CLI\\n')
        from mininet.cli import CLI
        CLI(net)

    info('*** Stopping network\\n')
    net.stop()

if __name__ == '__main__':
    run()
"""

    if topo_type == 'tree':
        body = """    s1 = net.addSwitch('s1', protocols='OpenFlow13', stp=True)
    s2 = net.addSwitch('s2', protocols='OpenFlow13', stp=True)
    s3 = net.addSwitch('s3', protocols='OpenFlow13', stp=True)

    net.addLink(s2, s1)
    net.addLink(s3, s1)

    h1 = net.addHost('h1', ip='10.0.0.1/24')
    h2 = net.addHost('h2', ip='10.0.0.2/24')
    h3 = net.addHost('h3', ip='10.0.0.3/24')
    h4 = net.addHost('h4', ip='10.0.0.4/24')

    net.addLink(h1, s2, bw=100, delay='1ms')
    net.addLink(h2, s2, bw=100, delay='1ms')
    net.addLink(h3, s3, bw=100, delay='1ms')
    net.addLink(h4, s3, bw=100, delay='1ms')
"""
    elif topo_type == 'mesh':
        body = """    s1 = net.addSwitch('s1', protocols='OpenFlow13', stp=True)
    s2 = net.addSwitch('s2', protocols='OpenFlow13', stp=True)
    s3 = net.addSwitch('s3', protocols='OpenFlow13', stp=True)
    s4 = net.addSwitch('s4', protocols='OpenFlow13', stp=True)

    net.addLink(s1, s2)
    net.addLink(s1, s3)
    net.addLink(s1, s4)
    net.addLink(s2, s3)
    net.addLink(s2, s4)
    net.addLink(s3, s4)

    h1 = net.addHost('h1', ip='10.0.0.1/24')
    h2 = net.addHost('h2', ip='10.0.0.2/24')
    h3 = net.addHost('h3', ip='10.0.0.3/24')
    h4 = net.addHost('h4', ip='10.0.0.4/24')

    net.addLink(h1, s1, bw=100, delay='1ms')
    net.addLink(h2, s2, bw=100, delay='1ms')
    net.addLink(h3, s3, bw=100, delay='1ms')
    net.addLink(h4, s4, bw=100, delay='1ms')
"""
    else:
        body = """    s1 = net.addSwitch('s1', protocols='OpenFlow13', stp=True)

    h1 = net.addHost('h1', ip='10.0.0.1/24')
    h2 = net.addHost('h2', ip='10.0.0.2/24')
    h3 = net.addHost('h3', ip='10.0.0.3/24')
    h4 = net.addHost('h4', ip='10.0.0.4/24')

    net.addLink(h1, s1, bw=100, delay='1ms')
    net.addLink(h2, s1, bw=100, delay='1ms')
    net.addLink(h3, s1, bw=100, delay='1ms')
    net.addLink(h4, s1, bw=100, delay='1ms')
"""

    os.makedirs('topology', exist_ok=True)
    with open('topology/network_topology.py', 'w') as f:
        f.write(header + body + footer)


# ─────────────────────────────────────────────────────
# Report API Endpoints
# ─────────────────────────────────────────────────────

@app.route('/api/report/summary')
def api_report_summary():
    """สรุปภาพรวม — รองรับ ?period=7 (วัน)"""
    try:
        import db_manager as db
        days = request.args.get('period', default=7, type=int)
        days = max(1, min(days, 365))
        return jsonify(db.get_report_summary(days))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/report/attacks')
def api_report_attacks():
    """Attack log ตาม date range — ?from=YYYY-MM-DD&to=YYYY-MM-DD"""
    try:
        import db_manager as db
        from_dt = request.args.get('from', f'{datetime.now().date()} 00:00:00')
        to_dt   = request.args.get('to',   str(datetime.now()))
        limit   = request.args.get('limit', default=200, type=int)
        return jsonify(db.get_attack_log_range(from_dt, to_dt, limit))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/report/attack-types')
def api_report_attack_types():
    """สัดส่วนประเภท attack — สำหรับ pie chart"""
    try:
        import db_manager as db
        days = request.args.get('period', default=7, type=int)
        return jsonify(db.get_attack_type_distribution(days))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/report/top-ports')
def api_report_top_ports():
    """Top 5 พอร์ตที่โดนโจมตีมากสุด"""
    try:
        import db_manager as db
        days  = request.args.get('period', default=7, type=int)
        limit = request.args.get('limit',  default=5, type=int)
        return jsonify(db.get_top_attacked_ports(days, limit))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/report/traffic/hourly')
def api_report_traffic_hourly():
    """Traffic รายชั่วโมงย้อนหลัง — ?port=1&days=7"""
    try:
        import db_manager as db
        port = request.args.get('port', type=int)
        days = request.args.get('days', default=7, type=int)
        # ก่อนส่ง ให้ aggregate ชั่วโมงล่าสุดก่อนเสมอ
        try:
            db.aggregate_traffic_hourly()
        except Exception:
            pass
        return jsonify(db.get_traffic_hourly_history(port, days))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/report/daily')
def api_report_daily():
    """Daily summary ย้อนหลัง — ?days=30"""
    try:
        import db_manager as db
        days = request.args.get('days', default=30, type=int)
        return jsonify(db.get_daily_summaries(days))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/report/topology-events')
def api_report_topology_events():
    """ประวัติการเปลี่ยน Topology"""
    try:
        import db_manager as db
        days = request.args.get('days', default=7, type=int)
        return jsonify(db.get_topology_events(days))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/report/export')
def api_report_export():
    """Export attack log เป็น CSV — ?from=YYYY-MM-DD&to=YYYY-MM-DD"""
    try:
        import db_manager as db
        from_dt = request.args.get('from', f'{datetime.now().date()} 00:00:00')
        to_dt   = request.args.get('to',   str(datetime.now()))
        rows    = db.export_attacks_csv(from_dt, to_dt)

        output = io.StringIO()
        if rows:
            writer = csv.DictWriter(output, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        else:
            output.write('No data in range\n')

        filename = f'attack_report_{datetime.now().strftime("%Y%m%d_%H%M")}.csv'
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename={filename}'}
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─────────────────────────────────────────────────────
# ML Models API Endpoints
# ─────────────────────────────────────────────────────

@app.route('/api/models', methods=['GET'])
def api_get_models():
    """ดึงรายการโมเดลทั้งหมด"""
    try:
        import db_manager as db
        return jsonify(db.get_ml_models())
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/models/upload', methods=['POST'])
def api_upload_model():
    """อัปโหลดโมเดลและไฟล์ที่เกี่ยวข้อง"""
    try:
        if 'file' not in request.files:
            return jsonify({'ok': False, 'error': 'No file part'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'ok': False, 'error': 'No selected file'}), 400
        
        if file:
            filename = secure_filename(file.filename)
            # เพิ่ม timestamp เพื่อป้องกันชื่อซ้ำในไฟล์
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_")
            save_name = timestamp + filename
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], save_name)
            file.save(file_path)
            
            scaler_path = None
            le_path = None
            if 'scaler' in request.files:
                scaler_file = request.files['scaler']
                if scaler_file.filename != '':
                    s_name = secure_filename(scaler_file.filename)
                    scaler_path = os.path.join(app.config['UPLOAD_FOLDER'], timestamp + s_name)
                    scaler_file.save(scaler_path)
                    
            if 'le' in request.files:
                le_file = request.files['le']
                if le_file.filename != '':
                    l_name = secure_filename(le_file.filename)
                    le_path = os.path.join(app.config['UPLOAD_FOLDER'], timestamp + l_name)
                    le_file.save(le_path)

            name = request.form.get('name', filename)
            description = request.form.get('description', '')

            import db_manager as db
            try:
                db.add_ml_model(name, file_path, scaler_path, le_path, description)
            except Exception as e:
                return jsonify({'ok': False, 'error': f'Database error: {e}'}), 400

            return jsonify({'ok': True, 'message': 'Model uploaded successfully'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/models/active', methods=['POST'])
def api_set_active_model():
    """เลือกโมเดลที่ต้องการใช้งาน"""
    try:
        data = request.json
        model_id = data.get('id')
        if not model_id:
            return jsonify({'ok': False, 'error': 'Model ID required'}), 400
            
        import db_manager as db
        db.set_active_model(model_id)
        
        # Note: Controller อาจต้องถูกส่ง signal เพื่อโหลดโมเดลใหม่ 
        # ปัจจุบันใช้การบันทึกลง DB เพื่อให้พร้อมเมื่อมีการรีสตาร์ท Controller
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# ─── Scheduled jobs (run in background thread) ───

def _scheduled_jobs():
    """Job วิ่งทุกชั่วโมง: aggregate hourly + daily summary"""
    import db_manager as db
    while True:
        time.sleep(3600)  # ทุก 1 ชั่วโมง
        try:
            db.aggregate_traffic_hourly()
            print("[Job] ✅ traffic_hourly aggregated")
        except Exception as e:
            print(f"[Job] ❌ hourly aggregate error: {e}")
        # ทุกตี 1 ทำ daily summary ของเมื่อวาน
        now = datetime.now()
        if now.hour == 1:
            try:
                db.aggregate_daily_summary()
                print("[Job] ✅ daily_summary done")
            except Exception as e:
                print(f"[Job] ❌ daily summary error: {e}")


if __name__ == '__main__':
    try:
        from notifier import notify_system_start
        notify_system_start()
    except:
        pass
    # เริ่ม scheduled job
    threading.Thread(target=_scheduled_jobs, daemon=True).start()
    print("🌐 Dashboard: http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
from flask import Flask, jsonify, request, Response
from flask_cors import CORS
from werkzeug.utils import secure_filename
import threading, time, json, os, subprocess, csv, io
from collections import deque
from datetime import datetime

from topology.topology_manager import TopologyBusyError, TopologyManager

app = Flask(__name__)
CORS(app)

# ─── Model Uploads Setup ───
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ml', 'model', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# ipc_path = '/tmp/unblock_requests.txt'
# ipc_path = '/home/beepbeep-kun/unblock_requests.txt'

# ─── Shared state ───
traffic_history = deque(maxlen=60)
blocked_ips     = {}
attack_log      = deque(maxlen=100)
port_stats      = {}
ml_stats        = {}

topology_manager = TopologyManager()

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
    label = d.get('label', 'Unknown')
    ts = datetime.now().strftime('%H:%M:%S')
    blocked_ips[ip] = {
        'time': ts, 'port': port,
        'conf': round(conf*100,1),
        'label': label,
        'expire': time.time()+90   # ตรงกับ BLOCK_DURATION=90 ของ controller
    }
    attack_log.appendleft({'time': ts, 'port': port, 'ip': ip, 'conf': round(conf*100,1), 'label': label})
    ml_stats[str(port)] = {'pred': 1, 'conf': round(conf*100,1)}
    # บันทึกลง DB (fallback กรณี Ryu HAS_DB=False)
    try:
        import db_manager as db
        pps_val = d.get('pps', 0)
        bps_val = d.get('bps', 0)
        db.log_attack(port, pps_val, bps_val, conf, note=label, attack_type=label)
        db.block_port(port, conf, 90)
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
        'blocked': [{'ip': k, 'label': v.get('label',''), **v} for k, v in blocked_ips.items()],
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
    """Unblock by IP or port (backward compatible)"""
    try:
        data = request.get_json(force=True) or {}
        ip = data.get('ip')
        port = data.get('port')

        ips_to_unblock = []
        # ลบจาก in-memory blocked_ips
        if ip:
            ips_to_unblock.append(ip)
            if ip in blocked_ips:
                port = blocked_ips[ip].get('port', port)
                del blocked_ips[ip]
        elif port:
            # fallback: ลบ by port (backward compatible)
            to_remove = [k for k, v in blocked_ips.items() if v.get('port') == int(port)]
            for k in to_remove:
                ips_to_unblock.append(k)
                del blocked_ips[k]

        # เขียน IPC file ส่งต่อให้ Ryu เพื่อปลดบล็อกใน OVS flow จริง
        for target_ip in ips_to_unblock:
            try:
                with open('/tmp/unblock_requests.txt', 'a') as f:
                    f.write(f"{target_ip}\n")
            except Exception:
                pass

        # ลบจาก DB
        if port:
            try:
                import db_manager as db
                db.unblock_port(int(port), 'manual')
            except:
                pass

        return jsonify({'ok': True, 'ip': ip, 'port': port})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

@app.route('/api/unblock/ip/<path:ip>', methods=['POST'])
def api_unblock_ip(ip):
    """Unblock by IP address"""
    try:
        port = None
        if ip in blocked_ips:
            port = blocked_ips[ip].get('port')
            del blocked_ips[ip]

        # เขียน IPC file ส่งต่อให้ Ryu เพื่อปลดบล็อกใน OVS flow จริง
        try:
            with open('/tmp/unblock_requests.txt', 'a') as f:
                f.write(f"{ip}\n")
        except Exception:
            pass

        if port:
            try:
                import db_manager as db
                db.unblock_port(int(port), 'manual')
            except:
                pass
        return jsonify({'ok': True, 'ip': ip})
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

@app.route('/api/topology', methods=['GET'])
@app.route('/api/topology/status', methods=['GET'])
def api_topology_status():
    """Return persisted desired topology and the latest Ryu-observed runtime."""
    return jsonify(topology_manager.status())


@app.route('/api/topology', methods=['POST'])
@app.route('/api/topology/apply', methods=['POST'])
def api_topology_apply():
    """Persist a validated selection, then change Mininet asynchronously."""
    data = request.get_json(silent=True) or {}
    if 'topology' not in data:
        return jsonify({'ok': False, 'error': 'topology is required'}), 400
    try:
        result = topology_manager.apply(data['topology'])
        port_stats.clear()
        ml_stats.clear()
        traffic_history.clear()
        try:
            import db_manager as db
            selected = result['selected_topology']
            db.log_topology_event(selected, 'apply', 'User applied %s topology' % selected)
        except Exception:
            pass
        return jsonify({'ok': True, **result}), 202
    except TopologyBusyError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 409
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@app.route('/api/topology/runtime', methods=['POST'])
def api_topology_runtime():
    """Receive observation-only discovery snapshots from the local Ryu app."""
    if request.remote_addr not in {'127.0.0.1', '::1'}:
        return jsonify({'ok': False, 'error': 'runtime reports are local-only'}), 403
    try:
        status = topology_manager.record_runtime(request.get_json(silent=True) or {})
        return jsonify({'ok': True, 'status': status['status'], 'in_sync': status['in_sync']})
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400


@app.route('/api/topology/diagnostics/<command>', methods=['POST'])
def api_topology_diagnostic(command):
    """Run a fixed Mininet connectivity diagnostic for the demo."""
    try:
        return jsonify(topology_manager.run_diagnostic(command))
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except (OSError, RuntimeError) as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 503

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
"""
Database Manager — PostgreSQL
ปรับปรุง: เพิ่มตาราง traffic_hourly, daily_summary, topology_events
         แก้ retention ของ traffic_stats จาก 1h → 24h
         เพิ่ม column attack_type, dpid ใน attack_log
"""
import psycopg2, psycopg2.extras, time
from datetime import datetime, date
from contextlib import contextmanager

DB_CONFIG = {
    'host':     'localhost',
    'port':     5432,
    'dbname':   'sdn_security',
    'user':     'sdn_user',
    'password': 'admin'
}

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            # ─── Step 1: สร้างตารางทั้งหมด ───
            # ตารางศูนย์กลางสำหรับ Port เพื่อใช้เป็น Primary Key อ้างอิง
            cur.execute("""
            CREATE TABLE IF NOT EXISTS network_ports (
                port        INTEGER PRIMARY KEY,
                description TEXT,
                first_seen  TIMESTAMP DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS ml_models (
                id          SERIAL PRIMARY KEY,
                name        TEXT UNIQUE NOT NULL,
                file_path   TEXT NOT NULL,
                scaler_path TEXT,
                le_path     TEXT,
                is_active   BOOLEAN DEFAULT FALSE,
                uploaded_at TIMESTAMP DEFAULT NOW(),
                accuracy    REAL,
                description TEXT
            );

            CREATE TABLE IF NOT EXISTS attack_log (
                id          SERIAL PRIMARY KEY,
                timestamp   TIMESTAMP NOT NULL DEFAULT NOW(),
                port        INTEGER   NOT NULL REFERENCES network_ports(port) ON DELETE CASCADE,
                pps         REAL      DEFAULT 0,
                bps         REAL      DEFAULT 0,
                conf        REAL      DEFAULT 0,
                action      TEXT      DEFAULT 'BLOCK',
                note        TEXT
            );

            CREATE TABLE IF NOT EXISTS blocked_ports (
                port        INTEGER   PRIMARY KEY REFERENCES network_ports(port) ON DELETE CASCADE,
                blocked_at  TIMESTAMP NOT NULL DEFAULT NOW(),
                blocked_ts  REAL      NOT NULL,
                duration    INTEGER   NOT NULL DEFAULT 60,
                conf        REAL      DEFAULT 0,
                unblocked   BOOLEAN   DEFAULT FALSE,
                unblock_at  TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS traffic_stats (
                id          SERIAL PRIMARY KEY,
                timestamp   TIMESTAMP NOT NULL DEFAULT NOW(),
                port        INTEGER   NOT NULL REFERENCES network_ports(port) ON DELETE CASCADE,
                pps         REAL      DEFAULT 0,
                bps         REAL      DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS unblock_log (
                id          SERIAL PRIMARY KEY,
                timestamp   TIMESTAMP NOT NULL DEFAULT NOW(),
                port        INTEGER   NOT NULL REFERENCES network_ports(port) ON DELETE CASCADE,
                reason      TEXT      DEFAULT 'manual'
            );

            CREATE TABLE IF NOT EXISTS traffic_hourly (
                id           SERIAL PRIMARY KEY,
                hour         TIMESTAMP NOT NULL,
                port         INTEGER   NOT NULL REFERENCES network_ports(port) ON DELETE CASCADE,
                avg_pps      REAL      DEFAULT 0,
                max_pps      REAL      DEFAULT 0,
                avg_bps      REAL      DEFAULT 0,
                max_bps      REAL      DEFAULT 0,
                sample_count INTEGER   DEFAULT 0,
                UNIQUE (hour, port)
            );

            CREATE TABLE IF NOT EXISTS daily_summary (
                id                   SERIAL PRIMARY KEY,
                date                 DATE   NOT NULL UNIQUE,
                total_attacks        INTEGER DEFAULT 0,
                total_blocks         INTEGER DEFAULT 0,
                total_unblocks       INTEGER DEFAULT 0,
                peak_pps             REAL    DEFAULT 0,
                peak_bps             REAL    DEFAULT 0,
                most_attacked_port   INTEGER,
                top_attack_type      TEXT
            );

            CREATE TABLE IF NOT EXISTS topology_events (
                id          SERIAL PRIMARY KEY,
                timestamp   TIMESTAMP NOT NULL DEFAULT NOW(),
                topology    TEXT      NOT NULL,
                action      TEXT      DEFAULT 'apply',
                message     TEXT
            );
            """)

            # ─── Step 2: Migration — เพิ่ม column ใหม่ใน attack_log ก่อน index ───
            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name='attack_log' AND column_name='attack_type'
                    ) THEN
                        ALTER TABLE attack_log ADD COLUMN attack_type TEXT DEFAULT 'Unknown';
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name='attack_log' AND column_name='dpid'
                    ) THEN
                        ALTER TABLE attack_log ADD COLUMN dpid BIGINT;
                    END IF;
                END $$;
            """)

            # ─── Step 2.5: Migration — เติมข้อมูลลง network_ports และสร้าง FK Constraints ───
            cur.execute("""
                DO $$
                BEGIN
                    -- รวบรวม port ทั้งหมดจากตารางเดิมเข้า network_ports
                    INSERT INTO network_ports (port)
                    SELECT DISTINCT port FROM attack_log
                    UNION
                    SELECT DISTINCT port FROM blocked_ports
                    UNION
                    SELECT DISTINCT port FROM traffic_stats
                    UNION
                    SELECT DISTINCT port FROM unblock_log
                    UNION
                    SELECT DISTINCT port FROM traffic_hourly
                    ON CONFLICT (port) DO NOTHING;
                    
                    -- เพิ่ม FK Constraints หากยังไม่มี
                    IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints WHERE constraint_name = 'attack_log_port_fkey') THEN
                        ALTER TABLE attack_log ADD CONSTRAINT attack_log_port_fkey FOREIGN KEY (port) REFERENCES network_ports(port) ON DELETE CASCADE;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints WHERE constraint_name = 'blocked_ports_port_fkey') THEN
                        ALTER TABLE blocked_ports ADD CONSTRAINT blocked_ports_port_fkey FOREIGN KEY (port) REFERENCES network_ports(port) ON DELETE CASCADE;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints WHERE constraint_name = 'traffic_stats_port_fkey') THEN
                        ALTER TABLE traffic_stats ADD CONSTRAINT traffic_stats_port_fkey FOREIGN KEY (port) REFERENCES network_ports(port) ON DELETE CASCADE;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints WHERE constraint_name = 'unblock_log_port_fkey') THEN
                        ALTER TABLE unblock_log ADD CONSTRAINT unblock_log_port_fkey FOREIGN KEY (port) REFERENCES network_ports(port) ON DELETE CASCADE;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints WHERE constraint_name = 'traffic_hourly_port_fkey') THEN
                        ALTER TABLE traffic_hourly ADD CONSTRAINT traffic_hourly_port_fkey FOREIGN KEY (port) REFERENCES network_ports(port) ON DELETE CASCADE;
                    END IF;
                EXCEPTION WHEN duplicate_object THEN
                    -- Constraint มีอยู่แล้ว
                END $$;
            """)

            # ─── Step 3: Indexes (หลัง migration) ───
            cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_attack_log_ts      ON attack_log     (timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_attack_log_type    ON attack_log     (attack_type);
            CREATE INDEX IF NOT EXISTS idx_attack_log_port    ON attack_log     (port);
            CREATE INDEX IF NOT EXISTS idx_traffic_port_ts    ON traffic_stats  (port, timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_blocked_active     ON blocked_ports  (unblocked, blocked_ts);
            CREATE INDEX IF NOT EXISTS idx_traffic_hourly     ON traffic_hourly (port, hour DESC);
            CREATE INDEX IF NOT EXISTS idx_daily_summary_date ON daily_summary  (date DESC);
            CREATE INDEX IF NOT EXISTS idx_topology_events_ts ON topology_events(timestamp DESC);
            """)

    print("✅ PostgreSQL tables ready (v2)")


# ─── Connection ───
@contextmanager
def get_conn():
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

# ─── Write functions ───

def ensure_port_exists(cur, port):
    """ฟังก์ชันช่วยตรวจสอบและสร้าง port ใน network_ports เพื่อป้องกัน FK Error"""
    cur.execute("""
        INSERT INTO network_ports (port)
        VALUES (%s)
        ON CONFLICT (port) DO NOTHING
    """, (port,))

def log_attack(port, pps, bps, conf, note="", attack_type="Unknown", dpid=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            ensure_port_exists(cur, port)
            cur.execute("""
                INSERT INTO attack_log (port, pps, bps, conf, note, attack_type, dpid)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (port, round(pps,1), round(bps,1), round(conf*100,1), note, attack_type, dpid))

def block_port(port, conf, duration=60):
    now = time.time()
    with get_conn() as conn:
        with conn.cursor() as cur:
            ensure_port_exists(cur, port)
            cur.execute("""
                INSERT INTO blocked_ports (port, blocked_ts, duration, conf, unblocked)
                VALUES (%s, %s, %s, %s, FALSE)
                ON CONFLICT (port) DO UPDATE SET
                    blocked_at = NOW(),
                    blocked_ts = EXCLUDED.blocked_ts,
                    duration   = EXCLUDED.duration,
                    conf       = EXCLUDED.conf,
                    unblocked  = FALSE,
                    unblock_at = NULL
            """, (port, now, duration, round(conf*100,1)))

def unblock_port(port, reason='manual'):
    with get_conn() as conn:
        with conn.cursor() as cur:
            ensure_port_exists(cur, port)
            cur.execute("""
                UPDATE blocked_ports
                SET unblocked=TRUE, unblock_at=NOW()
                WHERE port=%s
            """, (port,))
            cur.execute("""
                INSERT INTO unblock_log (port, reason)
                VALUES (%s, %s)
            """, (port, reason))

def log_traffic(port, pps, bps):
    with get_conn() as conn:
        with conn.cursor() as cur:
            ensure_port_exists(cur, port)
            cur.execute("""
                INSERT INTO traffic_stats (port, pps, bps)
                VALUES (%s, %s, %s)
            """, (port, round(pps,1), round(bps,1)))
            # เก็บ raw stats ไว้ 24 ชั่วโมง (เพิ่มจาก 1h เพื่อ report)
            cur.execute("""
                DELETE FROM traffic_stats
                WHERE timestamp < NOW() - INTERVAL '24 hours'
            """)

def log_topology_event(topology, action='apply', message=''):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO topology_events (topology, action, message)
                VALUES (%s, %s, %s)
            """, (topology, action, message))

def aggregate_traffic_hourly():
    """
    สรุป traffic_stats เป็นรายชั่วโมง → เก็บใน traffic_hourly
    เรียกทุกชั่วโมง (หรือเรียกจาก scheduled job)
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO traffic_hourly (hour, port, avg_pps, max_pps, avg_bps, max_bps, sample_count)
                SELECT
                    DATE_TRUNC('hour', timestamp) AS hour,
                    port,
                    ROUND(AVG(pps)::numeric, 1)  AS avg_pps,
                    ROUND(MAX(pps)::numeric, 1)  AS max_pps,
                    ROUND(AVG(bps)::numeric, 1)  AS avg_bps,
                    ROUND(MAX(bps)::numeric, 1)  AS max_bps,
                    COUNT(*)                      AS sample_count
                FROM traffic_stats
                WHERE timestamp < DATE_TRUNC('hour', NOW())   -- เฉพาะชั่วโมงที่ผ่านแล้ว
                  AND timestamp > NOW() - INTERVAL '25 hours' -- ไม่ย้อนหลังเกินไป
                GROUP BY hour, port
                ON CONFLICT (hour, port) DO UPDATE SET
                    avg_pps      = EXCLUDED.avg_pps,
                    max_pps      = EXCLUDED.max_pps,
                    avg_bps      = EXCLUDED.avg_bps,
                    max_bps      = EXCLUDED.max_bps,
                    sample_count = EXCLUDED.sample_count
            """)

def aggregate_daily_summary(target_date=None):
    """
    สรุปข้อมูลรายวัน → เก็บใน daily_summary
    target_date: date object (default = เมื่อวาน)
    """
    if target_date is None:
        from datetime import timedelta
        target_date = date.today() - timedelta(days=1)

    d = target_date
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # นับ attacks
            cur.execute("""
                SELECT COUNT(*) AS cnt FROM attack_log
                WHERE DATE(timestamp) = %s
            """, (d,))
            total_attacks = cur.fetchone()['cnt']

            # นับ blocks
            cur.execute("""
                SELECT COUNT(*) AS cnt FROM blocked_ports
                WHERE DATE(blocked_at) = %s
            """, (d,))
            total_blocks = cur.fetchone()['cnt']

            # นับ unblocks
            cur.execute("""
                SELECT COUNT(*) AS cnt FROM unblock_log
                WHERE DATE(timestamp) = %s
            """, (d,))
            total_unblocks = cur.fetchone()['cnt']

            # peak traffic
            cur.execute("""
                SELECT COALESCE(MAX(pps),0) AS peak_pps, COALESCE(MAX(bps),0) AS peak_bps
                FROM traffic_stats WHERE DATE(timestamp) = %s
            """, (d,))
            row = cur.fetchone()
            peak_pps, peak_bps = row['peak_pps'], row['peak_bps']

            # พอร์ตที่โดนโจมตีมากสุด
            cur.execute("""
                SELECT port, COUNT(*) AS cnt FROM attack_log
                WHERE DATE(timestamp) = %s
                GROUP BY port ORDER BY cnt DESC LIMIT 1
            """, (d,))
            most_row = cur.fetchone()
            most_attacked_port = most_row['port'] if most_row else None

            # ประเภท attack ที่พบมากสุด
            cur.execute("""
                SELECT attack_type, COUNT(*) AS cnt FROM attack_log
                WHERE DATE(timestamp) = %s AND attack_type IS NOT NULL
                GROUP BY attack_type ORDER BY cnt DESC LIMIT 1
            """, (d,))
            type_row = cur.fetchone()
            top_attack_type = type_row['attack_type'] if type_row else None

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO daily_summary
                    (date, total_attacks, total_blocks, total_unblocks,
                     peak_pps, peak_bps, most_attacked_port, top_attack_type)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (date) DO UPDATE SET
                    total_attacks      = EXCLUDED.total_attacks,
                    total_blocks       = EXCLUDED.total_blocks,
                    total_unblocks     = EXCLUDED.total_unblocks,
                    peak_pps           = EXCLUDED.peak_pps,
                    peak_bps           = EXCLUDED.peak_bps,
                    most_attacked_port = EXCLUDED.most_attacked_port,
                    top_attack_type    = EXCLUDED.top_attack_type
            """, (d, total_attacks, total_blocks, total_unblocks,
                  round(peak_pps,1), round(peak_bps,1),
                  most_attacked_port, top_attack_type))

# ─── Read functions (existing) ───

def get_blocked_ports():
    now = time.time()
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT port, blocked_at, blocked_ts, duration, conf,
                       GREATEST(0, CAST(blocked_ts + duration - %s AS INTEGER)) AS remaining
                FROM blocked_ports
                WHERE unblocked = FALSE
                  AND blocked_ts + duration > %s
                ORDER BY blocked_at DESC
            """, (now, now))
            return [dict(r) for r in cur.fetchall()]

def get_attack_log(limit=50):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, timestamp::text, port, pps, bps, conf, action, attack_type, note
                FROM attack_log
                ORDER BY id DESC
                LIMIT %s
            """, (limit,))
            return [dict(r) for r in cur.fetchall()]

def get_traffic_history(port=None, minutes=10):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if port:
                cur.execute("""
                    SELECT timestamp::text, port, pps, bps
                    FROM traffic_stats
                    WHERE port = %s
                      AND timestamp > NOW() - INTERVAL '%s minutes'
                    ORDER BY timestamp DESC LIMIT 60
                """, (port, minutes))
            else:
                cur.execute("""
                    SELECT timestamp::text, port, pps, bps
                    FROM traffic_stats
                    WHERE timestamp > NOW() - INTERVAL '%s minutes'
                    ORDER BY timestamp DESC LIMIT 120
                """, (minutes,))
            return [dict(r) for r in cur.fetchall()]

def get_stats_summary():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT COUNT(*) AS total FROM attack_log")
            total_attacks = cur.fetchone()['total']

            cur.execute("SELECT COUNT(*) AS total FROM unblock_log")
            total_unblocks = cur.fetchone()['total']

            cur.execute("""
                SELECT id, timestamp::text, port, conf
                FROM attack_log
                ORDER BY id DESC LIMIT 1
            """)
            last_attack = cur.fetchone()

            active_blocks = len(get_blocked_ports())

            return {
                'total_attacks':  total_attacks,
                'active_blocks':  active_blocks,
                'total_unblocks': total_unblocks,
                'last_attack':    dict(last_attack) if last_attack else None
            }

# ─── Read functions (new — for Report) ───

def get_report_summary(days=7):
    """สรุปภาพรวมย้อนหลัง N วัน"""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    COUNT(*) AS total_attacks,
                    COALESCE(MAX(pps), 0) AS peak_pps,
                    COALESCE(MAX(bps), 0) AS peak_bps
                FROM attack_log
                WHERE timestamp > NOW() - INTERVAL '%s days'
            """, (days,))
            attack_stats = dict(cur.fetchone())

            cur.execute("""
                SELECT COUNT(*) AS total_blocks FROM blocked_ports
                WHERE blocked_at > NOW() - INTERVAL '%s days'
            """, (days,))
            attack_stats['total_blocks'] = cur.fetchone()['total_blocks']

            cur.execute("""
                SELECT COUNT(*) AS total_unblocks FROM unblock_log
                WHERE timestamp > NOW() - INTERVAL '%s days'
            """, (days,))
            attack_stats['total_unblocks'] = cur.fetchone()['total_unblocks']

            # attacks per day
            cur.execute("""
                SELECT DATE(timestamp)::text AS day, COUNT(*) AS count
                FROM attack_log
                WHERE timestamp > NOW() - INTERVAL '%s days'
                GROUP BY day ORDER BY day
            """, (days,))
            attack_stats['attacks_per_day'] = [dict(r) for r in cur.fetchall()]

            return attack_stats

def get_attack_type_distribution(days=7):
    """สัดส่วนประเภท attack (สำหรับ pie chart)"""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    COALESCE(NULLIF(attack_type,''), NULLIF(note,''), 'Unknown') AS type,
                    COUNT(*) AS count
                FROM attack_log
                WHERE timestamp > NOW() - INTERVAL '%s days'
                GROUP BY type ORDER BY count DESC
            """, (days,))
            return [dict(r) for r in cur.fetchall()]

def get_top_attacked_ports(days=7, limit=5):
    """Top N พอร์ตที่โดนโจมตีมากสุด"""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT port, COUNT(*) AS count, ROUND(AVG(conf)::numeric,1) AS avg_conf
                FROM attack_log
                WHERE timestamp > NOW() - INTERVAL '%s days'
                GROUP BY port ORDER BY count DESC LIMIT %s
            """, (days, limit))
            return [dict(r) for r in cur.fetchall()]

def get_traffic_hourly_history(port=None, days=7):
    """ข้อมูล traffic รายชั่วโมงย้อนหลัง N วัน"""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if port:
                cur.execute("""
                    SELECT hour::text, port, avg_pps, max_pps, avg_bps, max_bps
                    FROM traffic_hourly
                    WHERE port = %s AND hour > NOW() - INTERVAL '%s days'
                    ORDER BY hour
                """, (port, days))
            else:
                cur.execute("""
                    SELECT hour::text, port, avg_pps, max_pps, avg_bps, max_bps
                    FROM traffic_hourly
                    WHERE hour > NOW() - INTERVAL '%s days'
                    ORDER BY hour, port
                """, (days,))
            return [dict(r) for r in cur.fetchall()]

def get_attack_log_range(from_dt, to_dt, limit=500):
    """Attack log ตาม date range"""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, timestamp::text, port, pps, bps, conf, action, attack_type, note
                FROM attack_log
                WHERE timestamp BETWEEN %s AND %s
                ORDER BY timestamp DESC LIMIT %s
            """, (from_dt, to_dt, limit))
            return [dict(r) for r in cur.fetchall()]

def get_daily_summaries(days=30):
    """ดึง daily_summary ย้อนหลัง N วัน"""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT date::text, total_attacks, total_blocks, total_unblocks,
                       peak_pps, peak_bps, most_attacked_port, top_attack_type
                FROM daily_summary
                WHERE date > NOW() - INTERVAL '%s days'
                ORDER BY date
            """, (days,))
            return [dict(r) for r in cur.fetchall()]

def get_topology_events(days=7):
    """ประวัติการเปลี่ยน topology"""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, timestamp::text, topology, action, message
                FROM topology_events
                WHERE timestamp > NOW() - INTERVAL '%s days'
                ORDER BY timestamp DESC LIMIT 50
            """, (days,))
            return [dict(r) for r in cur.fetchall()]

def export_attacks_csv(from_dt, to_dt):
    """ส่งคืน list of dicts สำหรับ export CSV"""
    return get_attack_log_range(from_dt, to_dt, limit=10000)

# ─── ML Models functions ───

def add_ml_model(name, file_path, scaler_path=None, le_path=None, description=""):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ml_models (name, file_path, scaler_path, le_path, description)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (name, file_path, scaler_path, le_path, description))
            return cur.fetchone()[0]

def get_ml_models():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, name, file_path, scaler_path, le_path, is_active, uploaded_at::text, accuracy, description
                FROM ml_models
                ORDER BY uploaded_at DESC
            """)
            return [dict(r) for r in cur.fetchall()]

def set_active_model(model_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            # ปิดโมเดลเก่า
            cur.execute("UPDATE ml_models SET is_active = FALSE")
            # เปิดโมเดลใหม่
            cur.execute("UPDATE ml_models SET is_active = TRUE WHERE id = %s", (model_id,))

def get_active_model():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, name, file_path, scaler_path, le_path
                FROM ml_models
                WHERE is_active = TRUE
                LIMIT 1
            """)
            r = cur.fetchone()
            return dict(r) if r else None

if __name__ == '__main__':
    init_db()
    print("Summary:", get_stats_summary())

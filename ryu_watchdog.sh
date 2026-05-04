#!/bin/bash
# ─────────────────────────────────────────────
#  ryu_watchdog.sh
#  รัน Ryu และ restart อัตโนมัติเมื่อ crash
#  ใช้แทนการรัน ryu-manager ตรงๆ
#
#  วิธีใช้:
#    chmod +x ryu_watchdog.sh
#    ./ryu_watchdog.sh
# ─────────────────────────────────────────────

RYU_APP="/home/beepbeep-kun/Anti_sdn/controller/ryu_controller.py"
RYU_BIN="/home/beepbeep-kun/.pyenv/versions/sdn-env38/bin/ryu-manager"
PROJECT_DIR="/home/beepbeep-kun/Anti_sdn"
WAIT_BEFORE_RESTART=3   # วินาทีที่รอก่อน restart
MAX_RESTARTS=20          # ป้องกัน restart loop ไม่สิ้นสุด
RESTART_COUNT=0

echo "🚀 Ryu Watchdog started"
echo "   App : $RYU_APP"
echo "   Auto-restart on crash: YES (max $MAX_RESTARTS times)"
echo "────────────────────────────────────────"

while true; do
    echo "[$(date '+%H:%M:%S')] ▶ Starting Ryu... (restart #$RESTART_COUNT)"

    # cd ไปยัง project directory ก่อนเสมอ
    cd "$PROJECT_DIR" || exit 1

    # รัน Ryu — บรรทัดนี้จะ block จนกว่า Ryu จะตาย
    $RYU_BIN --ofp-tcp-listen-port 6653 --observe-links "$RYU_APP"
    EXIT_CODE=$?

    echo "[$(date '+%H:%M:%S')] ⚠ Ryu exited (code=$EXIT_CODE)"

    RESTART_COUNT=$((RESTART_COUNT + 1))
    if [ $RESTART_COUNT -ge $MAX_RESTARTS ]; then
        echo "❌ Reached max restarts ($MAX_RESTARTS). Stopping watchdog."
        exit 1
    fi

    echo "[$(date '+%H:%M:%S')] 🔄 Restarting in ${WAIT_BEFORE_RESTART}s..."
    sleep $WAIT_BEFORE_RESTART
done

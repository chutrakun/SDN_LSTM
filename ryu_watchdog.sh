#!/bin/bash
# ─────────────────────────────────────────────
#  ryu_watchdog.sh
#  รัน Ryu และ restart อัตโนมัติเมื่อ crash
#  + รัน setup_flows.sh อัตโนมัติหลัง Ryu เริ่มทุกครั้ง
#  + Bring up s1 interface หลัง restart
#
#  วิธีใช้:
#    chmod +x ryu_watchdog.sh
#    ./ryu_watchdog.sh
# ─────────────────────────────────────────────

RYU_APP="/home/beepbeep-kun/Anti_sdn/controller/ryu_controller.py"
RYU_BIN="/home/beepbeep-kun/.pyenv/versions/sdn-env38/bin/ryu-manager"
SETUP_FLOWS="/home/beepbeep-kun/setup_flows.sh"
PROJECT_DIR="/home/beepbeep-kun/Anti_sdn"

WAIT_BEFORE_RESTART=3    # วินาทีที่รอก่อน restart
WAIT_FOR_RYU_READY=5     # รอ Ryu handshake กับ OVS ก่อนลง flows
MAX_RESTARTS=20           # ป้องกัน restart loop ไม่สิ้นสุด
RESTART_COUNT=0

echo "🚀 Ryu Watchdog started"
echo "   App        : $RYU_APP"
echo "   Setup flows: $SETUP_FLOWS"
echo "   Auto-restart on crash: YES (max $MAX_RESTARTS times)"
echo "────────────────────────────────────────"

_install_flows() {
    echo "[$(date '+%H:%M:%S')] ⏳ รอ Ryu handshake กับ OVS ${WAIT_FOR_RYU_READY}s..."
    sleep "$WAIT_FOR_RYU_READY"

    # Bring up s1 LOCAL interface (หายทุกครั้งที่ Mininet restart)
    echo "[$(date '+%H:%M:%S')] 🔧 Bringing up s1 interface..."
    sudo ip link set s1 up 2>/dev/null || true
    sudo ip addr add 10.0.0.254/24 dev s1 2>/dev/null || true
    sudo ip route add 10.0.0.0/24 dev s1 2>/dev/null || true

    # รัน setup_flows.sh
    if [ -f "$SETUP_FLOWS" ]; then
        echo "[$(date '+%H:%M:%S')] 📡 Installing OVS flows..."
        bash "$SETUP_FLOWS"
    else
        echo "[$(date '+%H:%M:%S')] ⚠️  setup_flows.sh ไม่พบที่ $SETUP_FLOWS — ข้ามขั้นตอนนี้"
    fi
}

while true; do
    echo "[$(date '+%H:%M:%S')] ▶ Starting Ryu... (restart #$RESTART_COUNT)"

    cd "$PROJECT_DIR" || exit 1

    # รัน setup_flows ใน background หลังจาก delay
    _install_flows &
    FLOWS_PID=$!

    # รัน Ryu — block จนกว่า Ryu จะตาย
    $RYU_BIN --ofp-tcp-listen-port 6653 --observe-links "$RYU_APP"
    EXIT_CODE=$?

    # Ryu ตายแล้ว — kill flows installer ถ้ายังรันอยู่
    kill "$FLOWS_PID" 2>/dev/null || true

    echo "[$(date '+%H:%M:%S')] ⚠️  Ryu exited (code=$EXIT_CODE)"

    RESTART_COUNT=$((RESTART_COUNT + 1))
    if [ $RESTART_COUNT -ge $MAX_RESTARTS ]; then
        echo "❌ Reached max restarts ($MAX_RESTARTS). Stopping watchdog."
        exit 1
    fi

    echo "[$(date '+%H:%M:%S')] 🔄 Restarting in ${WAIT_BEFORE_RESTART}s..."
    sleep "$WAIT_BEFORE_RESTART"
done

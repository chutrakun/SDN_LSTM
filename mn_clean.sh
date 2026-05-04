#!/bin/bash
# ─────────────────────────────────────────────
#  mn_clean.sh — ล้าง Mininet ให้สะอาดสมบูรณ์
#  ใช้แทน sudo mn -c เมื่อมีซากค้างอยู่
# ─────────────────────────────────────────────

echo "=== [1] ฆ่า process Mininet ที่ค้างอยู่ ==="
pkill -9 -f "network_topology.py" 2>/dev/null
pkill -9 -f "mininet:" 2>/dev/null
echo "done"

echo "=== [2] รัน mn -c มาตรฐาน ==="
mn -c 2>/dev/null
echo "done"

echo "=== [3] บังคับลบ veth ซากที่ mn -c ไม่ลบ ==="
for iface in $(ip link show 2>/dev/null | grep -oE '([-_[:alnum:]]+-eth[[:digit:]]+)' | sort -u); do
    echo "  → deleting $iface"
    ip link delete "$iface" 2>/dev/null
done
echo "done"

echo "=== [4] ลบ OVS bridge ที่เหลือ ==="
for br in $(ovs-vsctl list-br 2>/dev/null); do
    echo "  → del-br $br"
    ovs-vsctl del-br "$br" 2>/dev/null
done
echo "done"

echo "=== [5] รีสตาร์ท OVS ==="
systemctl restart openvswitch-switch 2>/dev/null
echo "done"

echo ""
echo "✅ Cleanup complete!"
echo ""

echo "--- ตรวจสอบ interface ที่เหลือ ---"
ip link show | grep -E 'eth[0-9]+' || echo "(ไม่มีซากค้างแล้ว)"
echo ""
echo "--- ตรวจสอบ OVS bridge ---"
ovs-vsctl list-br 2>/dev/null || echo "(ไม่มี bridge แล้ว)"

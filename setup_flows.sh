#!/bin/bash
# setup_flows.sh — setup Ubuntu host interface + Kali routing
#
# topology (network_topology.py):
#   s1: port1=h1, port2=h2, port3=h3, port4=h4, LOCAL=10.0.0.254
#
# หมายเหตุ: flows ทั้งหมดถูก install โดย ryu_controller.py อัตโนมัติ
#           script นี้ทำแค่ setup interface และ Kali routing เท่านั้น
#
# วิธีใช้: bash ~/setup_flows.sh

set -e

# ─────────────────────────────────────────────
# 1. Bring up s1 LOCAL interface
# ─────────────────────────────────────────────
echo "🔧 Setup s1 interface..."
sudo ip link set s1 up
sudo ip addr add 10.0.0.254/24 dev s1 2>/dev/null || true
sudo ip route replace 10.0.0.0/24 dev s1 src 10.0.0.254
sudo sysctl -w net.ipv4.ip_forward=1 >/dev/null

# ตรวจว่า s1 พร้อมแล้ว
S1_MAC=$(sudo ovs-ofctl -O OpenFlow13 show s1 2>/dev/null \
         | grep "LOCAL(s1)" \
         | grep -oP "(?<=addr:)[0-9a-f:]+")

if [ -z "$S1_MAC" ]; then
    echo "❌ ไม่สามารถอ่าน MAC ของ s1 LOCAL ได้"
    echo "   ตรวจสอบว่า Mininet และ Ryu รันอยู่ก่อน"
    exit 1
fi
echo "   s1 LOCAL MAC = $S1_MAC"

# ─────────────────────────────────────────────
# 2. Kali → Mininet routing
# ─────────────────────────────────────────────
echo "🔧 Kali routing config..."

# MASQUERADE: แปลง src IP ของ Kali (192.168.56.x) เป็น 10.0.0.254 ก่อนเข้า s1
sudo iptables -t nat -C POSTROUTING -s 192.168.56.0/24 -o s1 -j MASQUERADE 2>/dev/null \
    || sudo iptables -t nat -A POSTROUTING -s 192.168.56.0/24 -o s1 -j MASQUERADE

# Policy routing: packet จาก vboxnet0 ให้ forward เข้า s1
sudo ip rule show | grep -q "iif vboxnet0" \
    || sudo ip rule add iif vboxnet0 lookup main

# Static ARP: Ubuntu รู้จัก Kali MAC โดยไม่ต้อง ARP
sudo arp -s 192.168.56.100 08:00:27:76:1e:78 -i vboxnet0 2>/dev/null || true

# ─────────────────────────────────────────────
# 3. ตรวจสอบ flows จาก Ryu
# ─────────────────────────────────────────────
FLOW_COUNT=$(sudo ovs-ofctl -O OpenFlow13 dump-flows s1 2>/dev/null \
             | grep "priority=200" | wc -l)

echo ""
echo "✅ Setup เสร็จแล้ว! (s1 MAC=$S1_MAC)"
echo "   flows priority=200 บน s1: $FLOW_COUNT"
echo ""

if [ "$FLOW_COUNT" -lt 20 ]; then
    echo "⚠️  flows น้อยกว่าที่คาดไว้ (ควรได้ ~44)"
    echo "   รอ Ryu install flows เสร็จ แล้วรัน script นี้ใหม่"
else
    echo "ทดสอบ:"
    echo "  ping 10.0.0.1              (Ubuntu → h1)"
    echo "  ping 10.0.0.1 (Kali)      (Kali → h1)"
    echo "  mininet> h1 ping -c3 h2   (h1 → h2)"
fi

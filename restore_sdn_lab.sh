#!/bin/bash
# =============================================================
# SDN Lab Full Restore Script
# Kali (192.168.56.100) → Ubuntu (192.168.56.1) → Mininet
# Topology: s1 (LOCAL=10.0.0.254) → h1(port4), s2→h2(port4), s3→h3(port4), s4→h4(port4)
# =============================================================
# รัน script นี้บน Ubuntu host หลัง mininet เริ่มทำงานแล้ว
# Usage: sudo bash restore_sdn_lab.sh
# =============================================================

set -e
echo "=== [1/4] Ubuntu Host Config ==="

# Kernel routing & ARP settings
sysctl -w net.ipv4.ip_forward=1
sysctl -w net.ipv4.conf.all.rp_filter=0
sysctl -w net.ipv4.conf.default.rp_filter=0

# ปิด rp_filter ทุก interface
for iface in $(ls /proc/sys/net/ipv4/conf/); do
    sysctl -w net.ipv4.conf.${iface}.rp_filter=0 2>/dev/null || true
done

# Lock MAC ของ Kali ไม่ให้ conflict
arp -s 192.168.56.100 08:00:27:76:1e:78 -i vboxnet0

echo "Host config done."

# =============================================================
echo ""
echo "=== [2/4] ตรวจสอบ Port Mapping (สำคัญมาก!) ==="
# *** ต้อง verify port จริงก่อน apply flows ***
# ดู veth peer ของแต่ละ interface เพื่อหา port number จริง
echo "--- s1 ports ---"
ovs-ofctl -O OpenFlow13 show s1 2>/dev/null | grep -E "addr|LOCAL" || echo "s1 ไม่พบ"
echo ""
echo "--- ip link (ดู @ifN เพื่อ map port) ---"
ip link show | grep -E "s[1-4]-eth|veth" | head -30
echo ""
echo "IMPORTANT: ตรวจ port ด้านบนก่อน แล้ว edit ตัวแปร PORT_* ใน script นี้ตรงๆ"
echo "ค่าด้านล่างเป็น default จาก session เดิม (อาจเปลี่ยนได้ถ้า mininet restart)"
echo ""

# =============================================================
# *** แก้ค่าเหล่านี้ถ้า port mapping เปลี่ยน ***
S1_PORT_H1=4       # s1: port ที่เชื่อมไป h1
S1_PORT_S2=1       # s1: port ที่เชื่อมไป s2
S1_PORT_S3=2       # s1: port ที่เชื่อมไป s3
S1_PORT_S4=3       # s1: port ที่เชื่อมไป s4

S2_PORT_H2=4       # s2: port ที่เชื่อมไป h2
S2_PORT_S1=1       # s2: port ที่เชื่อมไป s1 (uplink)

S3_PORT_H3=4       # s3: port ที่เชื่อมไป h3
S3_PORT_S1=1       # s3: port ที่เชื่อมไป s1 (uplink)

S4_PORT_H4=4       # s4: port ที่เชื่อมไป h4
S4_PORT_S1=1       # s4: port ที่เชื่อมไป s1 (uplink)

GW_MAC="fe:fd:00:00:00:01"   # MAC ของ s1 LOCAL (OVS gateway) - อาจเปลี่ยนได้
H1_MAC=""   # จะ auto-detect จาก mininet ด้านล่าง
H2_MAC=""
H3_MAC=""
H4_MAC=""

# =============================================================
echo "=== [3/4] OVS Flows ==="

# ---- ล้าง flows เก่าทั้งหมดก่อน ----
for sw in s1 s2 s3 s4; do
    echo "Flushing $sw ..."
    ovs-ofctl -O OpenFlow13 del-flows $sw 2>/dev/null || echo "  (skip $sw - ไม่มีใน OVS)"
done

# ---- s1 flows ----
echo "--- Installing s1 flows ---"

# Table-miss: drop (ไม่ส่ง controller)
ovs-ofctl -O OpenFlow13 add-flow s1 "priority=0,actions=drop"

# ARP: จาก LOCAL → ตอบ ARP request ให้ h1 (unicast ไป port h1)
ovs-ofctl -O OpenFlow13 add-flow s1 \
  "priority=200,arp,in_port=LOCAL,arp_tpa=10.0.0.1,actions=output:${S1_PORT_H1}"
ovs-ofctl -O OpenFlow13 add-flow s1 \
  "priority=200,arp,in_port=LOCAL,arp_tpa=10.0.0.2,actions=output:${S1_PORT_S2}"
ovs-ofctl -O OpenFlow13 add-flow s1 \
  "priority=200,arp,in_port=LOCAL,arp_tpa=10.0.0.3,actions=output:${S1_PORT_S3}"
ovs-ofctl -O OpenFlow13 add-flow s1 \
  "priority=200,arp,in_port=LOCAL,arp_tpa=10.0.0.4,actions=output:${S1_PORT_S4}"

# ARP: จาก h1/s2/s3/s4 กลับ LOCAL
ovs-ofctl -O OpenFlow13 add-flow s1 \
  "priority=200,arp,in_port=${S1_PORT_H1},actions=LOCAL"
ovs-ofctl -O OpenFlow13 add-flow s1 \
  "priority=200,arp,in_port=${S1_PORT_S2},actions=LOCAL"
ovs-ofctl -O OpenFlow13 add-flow s1 \
  "priority=200,arp,in_port=${S1_PORT_S3},actions=LOCAL"
ovs-ofctl -O OpenFlow13 add-flow s1 \
  "priority=200,arp,in_port=${S1_PORT_S4},actions=LOCAL"

# IP: Kali/Ubuntu → h1 (rewrite dst MAC เป็น h1's MAC)
# ใช้ load_group หรือ set_field — ดึง MAC h1 จาก mininet
echo "กำลัง detect MAC จาก mininet..."
H1_MAC=$(mnexec -a h1 cat /sys/class/net/h1-eth0/address 2>/dev/null || \
         ip neigh show 10.0.0.1 2>/dev/null | awk '{print $5}' | head -1)
H2_MAC=$(mnexec -a h2 cat /sys/class/net/h2-eth0/address 2>/dev/null || true)
H3_MAC=$(mnexec -a h3 cat /sys/class/net/h3-eth0/address 2>/dev/null || true)
H4_MAC=$(mnexec -a h4 cat /sys/class/net/h4-eth0/address 2>/dev/null || true)
GW_MAC=$(ovs-vsctl get Interface s1 mac_in_use 2>/dev/null | tr -d '"' || echo "fe:fd:00:00:00:01")

echo "  h1 MAC: ${H1_MAC:-ไม่พบ}"
echo "  h2 MAC: ${H2_MAC:-ไม่พบ}"
echo "  h3 MAC: ${H3_MAC:-ไม่พบ}"
echo "  h4 MAC: ${H4_MAC:-ไม่พบ}"
echo "  GW MAC: ${GW_MAC}"

if [ -z "$H1_MAC" ]; then
    echo ""
    echo "WARNING: ไม่สามารถ auto-detect MAC ได้"
    echo "กรุณา ping จาก mininet ก่อน: h1 ping -c1 10.0.0.254"
    echo "แล้วรัน script ใหม่ หรือ set H1_MAC/H2_MAC/H3_MAC/H4_MAC ด้วยตัวเอง"
    echo ""
    echo "ข้าม flow install ส่วน IP rewrite..."
else
    # IP forward LOCAL → h1 (set dst MAC = h1, src MAC = GW)
    ovs-ofctl -O OpenFlow13 add-flow s1 \
      "priority=200,ip,in_port=LOCAL,nw_dst=10.0.0.1,actions=set_field:${H1_MAC}->eth_dst,set_field:${GW_MAC}->eth_src,output:${S1_PORT_H1}"
    ovs-ofctl -O OpenFlow13 add-flow s1 \
      "priority=200,ip,in_port=LOCAL,nw_dst=10.0.0.2,actions=set_field:${H2_MAC:-ff:ff:ff:ff:ff:ff}->eth_dst,set_field:${GW_MAC}->eth_src,output:${S1_PORT_S2}"
    ovs-ofctl -O OpenFlow13 add-flow s1 \
      "priority=200,ip,in_port=LOCAL,nw_dst=10.0.0.3,actions=set_field:${H3_MAC:-ff:ff:ff:ff:ff:ff}->eth_dst,set_field:${GW_MAC}->eth_src,output:${S1_PORT_S3}"
    ovs-ofctl -O OpenFlow13 add-flow s1 \
      "priority=200,ip,in_port=LOCAL,nw_dst=10.0.0.4,actions=set_field:${H4_MAC:-ff:ff:ff:ff:ff:ff}->eth_dst,set_field:${GW_MAC}->eth_src,output:${S1_PORT_S4}"

    # IP return path: h1/s2/s3/s4 → LOCAL (reply กลับ Ubuntu/Kali)
    ovs-ofctl -O OpenFlow13 add-flow s1 \
      "priority=200,ip,in_port=${S1_PORT_H1},actions=LOCAL"
    ovs-ofctl -O OpenFlow13 add-flow s1 \
      "priority=200,ip,in_port=${S1_PORT_S2},actions=LOCAL"
    ovs-ofctl -O OpenFlow13 add-flow s1 \
      "priority=200,ip,in_port=${S1_PORT_S3},actions=LOCAL"
    ovs-ofctl -O OpenFlow13 add-flow s1 \
      "priority=200,ip,in_port=${S1_PORT_S4},actions=LOCAL"
fi

# ---- s2 flows (h2 อยู่ port 4) ----
echo "--- Installing s2 flows ---"
ovs-ofctl -O OpenFlow13 add-flow s2 "priority=0,actions=drop"
# ARP
ovs-ofctl -O OpenFlow13 add-flow s2 \
  "priority=200,arp,in_port=${S2_PORT_S1},arp_tpa=10.0.0.2,actions=output:${S2_PORT_H2}"
ovs-ofctl -O OpenFlow13 add-flow s2 \
  "priority=200,arp,in_port=${S2_PORT_H2},actions=output:${S2_PORT_S1}"
# IP
ovs-ofctl -O OpenFlow13 add-flow s2 \
  "priority=200,ip,in_port=${S2_PORT_S1},nw_dst=10.0.0.2,actions=output:${S2_PORT_H2}"
ovs-ofctl -O OpenFlow13 add-flow s2 \
  "priority=200,ip,in_port=${S2_PORT_H2},actions=output:${S2_PORT_S1}"

# ---- s3 flows (h3 อยู่ port 4) ----
echo "--- Installing s3 flows ---"
ovs-ofctl -O OpenFlow13 add-flow s3 "priority=0,actions=drop"
ovs-ofctl -O OpenFlow13 add-flow s3 \
  "priority=200,arp,in_port=${S3_PORT_S1},arp_tpa=10.0.0.3,actions=output:${S3_PORT_H3}"
ovs-ofctl -O OpenFlow13 add-flow s3 \
  "priority=200,arp,in_port=${S3_PORT_H3},actions=output:${S3_PORT_S1}"
ovs-ofctl -O OpenFlow13 add-flow s3 \
  "priority=200,ip,in_port=${S3_PORT_S1},nw_dst=10.0.0.3,actions=output:${S3_PORT_H3}"
ovs-ofctl -O OpenFlow13 add-flow s3 \
  "priority=200,ip,in_port=${S3_PORT_H3},actions=output:${S3_PORT_S1}"

# ---- s4 flows (h4 อยู่ port 4) ----
echo "--- Installing s4 flows ---"
ovs-ofctl -O OpenFlow13 add-flow s4 "priority=0,actions=drop"
ovs-ofctl -O OpenFlow13 add-flow s4 \
  "priority=200,arp,in_port=${S4_PORT_S1},arp_tpa=10.0.0.4,actions=output:${S4_PORT_H4}"
ovs-ofctl -O OpenFlow13 add-flow s4 \
  "priority=200,arp,in_port=${S4_PORT_H4},actions=output:${S4_PORT_S1}"
ovs-ofctl -O OpenFlow13 add-flow s4 \
  "priority=200,ip,in_port=${S4_PORT_S1},nw_dst=10.0.0.4,actions=output:${S4_PORT_H4}"
ovs-ofctl -O OpenFlow13 add-flow s4 \
  "priority=200,ip,in_port=${S4_PORT_H4},actions=output:${S4_PORT_S1}"

echo "OVS flows installed."

# =============================================================
echo ""
echo "=== [4/4] ตรวจสอบ Flows ที่ install แล้ว ==="
for sw in s1 s2 s3 s4; do
    echo "--- $sw ---"
    ovs-ofctl -O OpenFlow13 dump-flows $sw 2>/dev/null | grep -v "OFPST_FLOW" || echo "  (ไม่พบ)"
done

echo ""
echo "=== DONE ==="
echo ""
echo "ขั้นตอนต่อไปบน Kali (รันครั้งเดียว ถ้ายังไม่มี route):"
echo "  sudo ip route add 10.0.0.0/24 via 192.168.56.1"
echo ""
echo "ทดสอบ:"
echo "  ping -c3 10.0.0.1   # จาก Kali"
echo "  ping -c3 10.0.0.2"
echo "  ping -c3 10.0.0.3"
echo "  ping -c3 10.0.0.4"
echo ""
echo "ถ้า ping ไม่ผ่าน ให้รัน:"
echo "  sudo ovs-ofctl -O OpenFlow13 show s1   # ดู port mapping จริง"
echo "  ip link show | grep s1-eth             # ดู @ifN"
echo "แล้วแก้ตัวแปร S1_PORT_H1 ฯลฯ ในไฟล์นี้แล้วรัน restore ใหม่"

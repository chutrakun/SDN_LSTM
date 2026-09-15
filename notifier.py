"""
Notification Module — Telegram Bot
"""
import os
from pathlib import Path
import urllib.request, urllib.parse, json
import smtplib, threading
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / '.env')

# ── Telegram config ──
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

# ── Email config (optional) ──
EMAIL_SENDER = os.environ.get('EMAIL_SENDER', '')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD', '')
EMAIL_RECEIVER = os.environ.get('EMAIL_RECEIVER', '')

DEFAULT_MODEL_LABEL = "LSTM"


def _active_model_label():
    """Return a display label for the model the controller will load."""
    try:
        import os
        import db_manager as db

        active_model = db.get_active_model()
        if not active_model:
            return DEFAULT_MODEL_LABEL

        name = str(active_model.get('name') or '').strip()
        file_path = str(active_model.get('file_path') or '').strip()
        identity = f"{name} {os.path.basename(file_path)}".lower()
        if 'lstm' in identity:
            return 'LSTM'
        if (
            'random forest' in identity
            or 'random_forest' in identity
            or 'randomforest' in identity
        ):
            return 'Random Forest'
        return name or os.path.basename(file_path) or DEFAULT_MODEL_LABEL
    except Exception:
        return DEFAULT_MODEL_LABEL

def send_telegram(message: str):
    """ส่งแจ้งเตือนผ่าน Telegram Bot API"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[TELEGRAM] ยังไม่ได้ตั้งค่า token/chat_id")
        return
    try:
        data = json.dumps({
            'chat_id':    TELEGRAM_CHAT_ID,
            'text':       message,
            'parse_mode': 'HTML'
        }).encode()
        req = urllib.request.Request(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            data=data,
            headers={'Content-Type': 'application/json'}
        )
        urllib.request.urlopen(req, timeout=5)
        print(f"[TELEGRAM] ส่งสำเร็จ")
    except Exception as e:
        print(f"[TELEGRAM] Error: {e}")

def send_email(subject: str, body: str):
    """ส่งแจ้งเตือนผ่าน Email (optional)"""
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        return
    try:
        from email.mime.text import MIMEText
        msg = MIMEText(body, 'plain', 'utf-8')
        msg['Subject'] = subject
        msg['From']    = EMAIL_SENDER
        msg['To']      = EMAIL_RECEIVER
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(EMAIL_SENDER, EMAIL_PASSWORD)
            smtp.send_message(msg)
        print(f"[EMAIL] ส่งสำเร็จ")
    except Exception as e:
        print(f"[EMAIL] Error: {e}")

def notify_attack(port: int, pps: float, conf: float):
    """แจ้งเตือนเมื่อตรวจพบการโจมตี"""
    ts  = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    msg = (
        f"🔴 <b>SDN Security Alert</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🕐 เวลา: {ts}\n"
        f"⚠️ ตรวจพบ DDoS Attack!\n"
        f"📡 Port: <b>{port}</b>\n"
        f"📊 Traffic: <b>{pps:.1f} pkt/s</b>\n"
        f"🤖 ML Confidence: <b>{conf*100:.1f}%</b>\n"
        f"🚫 สถานะ: <b>BLOCKED อัตโนมัติ</b>"
    )
    threading.Thread(target=send_telegram, args=(msg,), daemon=True).start()
    threading.Thread(target=send_email,
        args=(f"[SDN Alert] Attack on port {port}", msg),
        daemon=True).start()

def notify_unblock(port: int, reason: str):
    """แจ้งเตือนเมื่อ unblock port"""
    ts      = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    reason_th = 'หมดเวลาอัตโนมัติ' if reason == 'expired' else 'ปลดบล็อคด้วยตัวเอง'
    msg = (
        f"✅ <b>SDN Security</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🕐 เวลา: {ts}\n"
        f"🔓 Port <b>{port}</b> ถูก Unblock แล้ว\n"
        f"📝 สาเหตุ: {reason_th}"
    )
    threading.Thread(target=send_telegram, args=(msg,), daemon=True).start()

def notify_system_start(model_name=None):
    """แจ้งเมื่อระบบเริ่มต้น"""
    ts  = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    model_label = model_name or _active_model_label()
    msg = (
        f"🟢 <b>SDN Security System</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🕐 เวลา: {ts}\n"
        f"✅ ระบบเริ่มทำงานแล้ว\n"
        f"🤖 ML Model: {model_label}\n"
        f"🌐 Dashboard: http://localhost:5000"
    )
    threading.Thread(target=send_telegram, args=(msg,), daemon=True).start()

if __name__ == '__main__':
    print("ทดสอบ Telegram Notification...")
    send_telegram(
        "🔔 <b>Test Message</b>\n"
        "ระบบ SDN Security พร้อมทำงานแล้วครับ ✅"
    )

#!/bin/bash
# start_webserver.sh — สร้าง web content สำหรับ SDN Web Server test
# ใช้กรณีต้องการสร้าง web content ล่วงหน้า (topology script จะสร้างให้อัตโนมัติ)

WEBROOT="/tmp/webroot"
mkdir -p "$WEBROOT"

cat > "$WEBROOT/index.html" << 'HTMLEOF'
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SDN Web Server</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #0d1520 0%, #1a2332 50%, #0d1520 100%);
            color: #e0e0e0; min-height: 100vh;
            display: flex; align-items: center; justify-content: center;
        }
        .container {
            text-align: center; padding: 40px;
            background: rgba(255,255,255,0.05);
            border-radius: 16px; border: 1px solid rgba(255,255,255,0.1);
            backdrop-filter: blur(10px); max-width: 600px;
        }
        .status { color: #00e5a0; font-size: 48px; margin-bottom: 16px; }
        h1 { font-size: 28px; margin-bottom: 8px; color: #4da6ff; }
        .info { color: #8899aa; font-size: 14px; margin-top: 12px; }
        .badge {
            display: inline-block; padding: 4px 12px; border-radius: 12px;
            background: rgba(0,229,160,0.15); color: #00e5a0;
            font-size: 12px; margin-top: 8px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="status">&#x2705;</div>
        <h1>SDN Web Server</h1>
        <p>Server is running and accessible</p>
        <div class="info">
            <p>Host: h_server | IP: 10.0.0.100</p>
            <p>Protected by SDN Intelligent Security (LSTM)</p>
        </div>
        <div class="badge">ACL-Based Protection Active</div>
    </div>
</body>
</html>
HTMLEOF

echo "✅ Web content created at $WEBROOT"
echo "   To start server manually in Mininet CLI:"
echo "   h_server python3 -m http.server 80 --directory /tmp/webroot &"

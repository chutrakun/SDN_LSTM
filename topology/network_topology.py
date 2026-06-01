from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.log import setLogLevel, info
from mininet.link import TCLink
import sys, time, os

def create_webroot():
    """สร้าง web content สำหรับ web server"""
    webroot = '/tmp/webroot'
    os.makedirs(webroot, exist_ok=True)
    html = """<!DOCTYPE html>
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
</html>"""
    with open(os.path.join(webroot, 'index.html'), 'w') as f:
        f.write(html)
    info(f'*** Web content created at {webroot}\n')

def run():
    setLogLevel('info')

    net = Mininet(controller=RemoteController, switch=OVSSwitch,
                  link=TCLink, autoSetMacs=True)

    info('*** Adding controller\n')
    c0 = net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6653)

    info('*** Adding switches and hosts\n')
    s1 = net.addSwitch('s1', protocols='OpenFlow13')

    # PCs
    h1 = net.addHost('h1', ip='10.0.0.1/24')
    h2 = net.addHost('h2', ip='10.0.0.2/24')
    h3 = net.addHost('h3', ip='10.0.0.3/24')
    h4 = net.addHost('h4', ip='10.0.0.4/24')

    # Web Server
    h_server = net.addHost('h_server', ip='10.0.0.100/24',
                           mac='00:00:00:00:00:64')

    net.addLink(h1, s1, bw=100, delay='1ms')
    net.addLink(h2, s1, bw=100, delay='1ms')
    net.addLink(h3, s1, bw=100, delay='1ms')
    net.addLink(h4, s1, bw=100, delay='1ms')
    net.addLink(h_server, s1, bw=100, delay='1ms')

    info('*** Starting network\n')
    net.start()

    # สร้าง web content และเริ่ม web server
    create_webroot()
    info('*** Starting web server on h_server (port 80)\n')
    h_server.cmd('python3 -m http.server 80 --directory /tmp/webroot &')

    info('*** Testing connectivity\n')
    net.pingAll()

    import sys
    if '--background' in sys.argv:
        info('*** Network running in background...\n')
        import time
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    else:
        info('*** Running CLI\n')
        from mininet.cli import CLI
        CLI(net)

    info('*** Stopping network\n')
    net.stop()

if __name__ == '__main__':
    run()

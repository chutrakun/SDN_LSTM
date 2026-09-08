from mininet.link import TCLink
from mininet.log import info, setLogLevel
from mininet.net import Mininet
from mininet.node import OVSSwitch, RemoteController

import argparse
import json
import os
import signal
import socket

from topology_config import DEFAULT_CONFIG_PATH, load_topology_config, profile_for


HOSTS = {
    "h1": {"ip": "10.0.0.1/24"},
    "h2": {"ip": "10.0.0.2/24"},
    "h3": {"ip": "10.0.0.3/24"},
    "h4": {"ip": "10.0.0.4/24"},
    "h_server": {"ip": "10.0.0.100/24", "mac": "00:00:00:00:00:64"},
}


def create_webroot():
    webroot = "/tmp/webroot"
    os.makedirs(webroot, exist_ok=True)
    html = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>SDN Web Server</title>
<style>body{font-family:sans-serif;background:#0d1520;color:#e0e0e0;
display:flex;align-items:center;justify-content:center;min-height:100vh;}
.c{text-align:center;padding:40px;background:rgba(255,255,255,0.05);
border-radius:16px;border:1px solid rgba(255,255,255,0.1);}
h1{color:#4da6ff}.s{color:#00e5a0;font-size:48px}</style>
</head><body><div class="c"><div class="s">&#x2705;</div>
<h1>SDN Web Server</h1><p>Server is running</p>
<p style="color:#8899aa">IP: 10.0.0.100 | ACL Protection Active</p>
</div></body></html>"""
    with open(os.path.join(webroot, "index.html"), "w") as handle:
        handle.write(html)
    info("*** Web content created\n")


def build_network(topology_id):
    profile = profile_for(topology_id)
    net = Mininet(
        controller=RemoteController,
        switch=OVSSwitch,
        link=TCLink,
        autoSetMacs=True,
    )
    info("*** Adding controller\n")
    net.addController("c0", controller=RemoteController, ip="127.0.0.1", port=6653)

    info("*** Adding %s switches and hosts\n" % topology_id)
    switches = {}
    multi_switch = len(profile["switches"]) > 1
    for name in profile["switches"]:
        options = {"protocols": "OpenFlow13"}
        if multi_switch:
            options["stp"] = True
        switches[name] = net.addSwitch(name, **options)

    # Inter-switch links are added first so the validated full-mesh port map
    # remains s1-s4 port 4 host-facing and s1 port 5 server-facing.
    for left, right in profile["edges"]:
        net.addLink(switches[left], switches[right])

    hosts = {}
    for name, options in HOSTS.items():
        hosts[name] = net.addHost(name, **options)
    for host_name, switch_name in profile["host_attachments"].items():
        net.addLink(hosts[host_name], switches[switch_name], bw=100, delay="1ms")
    return net, hosts


def _serve_control(net, hosts, socket_path, stop_requested):
    try:
        os.unlink(socket_path)
    except OSError:
        pass
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(socket_path)
    os.chmod(socket_path, 0o666)
    server.listen(2)
    server.settimeout(1.0)
    info("*** Topology control socket: %s\n" % socket_path)
    try:
        while not stop_requested[0]:
            try:
                connection, _ = server.accept()
            except socket.timeout:
                continue
            with connection:
                try:
                    request = json.loads(connection.recv(4096).decode())
                    command = request.get("command")
                    if command == "pingall":
                        loss = net.pingAll(timeout="1")
                        response = {"ok": True, "command": command, "packet_loss_percent": loss}
                    elif command == "ping_server":
                        output = hosts["h1"].cmd("ping -c 3 -W 1 10.0.0.100")
                        response = {"ok": "0% packet loss" in output, "command": command, "output": output}
                    elif command == "http_server":
                        code = hosts["h1"].cmd(
                            "curl -sS --max-time 5 -o /dev/null -w '%{http_code}' http://10.0.0.100/"
                        ).strip()
                        response = {"ok": code == "200", "command": command, "http_status": code}
                    else:
                        response = {"ok": False, "error": "unsupported command"}
                except Exception as exc:
                    response = {"ok": False, "error": str(exc)}
                connection.sendall((json.dumps(response) + "\n").encode())
    finally:
        server.close()
        try:
            os.unlink(socket_path)
        except OSError:
            pass


def run(config_path=DEFAULT_CONFIG_PATH, background=False, control_socket=None):
    setLogLevel("info")
    config, fallback = load_topology_config(config_path)
    if fallback:
        info("*** %s\n" % fallback)
    topology_id = config["topology"]
    info("*** Persisted topology: %s\n" % topology_id)
    net, hosts = build_network(topology_id)
    stop_requested = [False]

    def request_stop(_signum, _frame):
        stop_requested[0] = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    try:
        info("*** Starting network\n")
        net.start()
        create_webroot()
        info("*** Starting web server on h_server (port 80)\n")
        hosts["h_server"].cmd("python3 -m http.server 80 --directory /tmp/webroot >/tmp/h_server_http.log 2>&1 &")
        if background:
            _serve_control(net, hosts, control_socket or "/tmp/anti_sdn_topology.sock", stop_requested)
        else:
            info("*** Running CLI\n")
            from mininet.cli import CLI
            CLI(net)
    finally:
        info("*** Stopping network\n")
        net.stop()


def parse_args():
    parser = argparse.ArgumentParser(description="Start the persisted SDN topology")
    parser.add_argument("--background", action="store_true")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--control-socket", default="/tmp/anti_sdn_topology.sock")
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    run(arguments.config, arguments.background, arguments.control_socket)

from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.log import setLogLevel, info
from mininet.link import TCLink
import sys, time

def run():
    setLogLevel('info')

    net = Mininet(controller=RemoteController, switch=OVSSwitch,
                  link=TCLink, autoSetMacs=True)

    info('*** Adding controller\n')
    c0 = net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6653)

    info('*** Adding switches and hosts\n')
    s1 = net.addSwitch('s1', protocols='OpenFlow13', stp=True)

    h1 = net.addHost('h1', ip='10.0.0.1/24')
    h2 = net.addHost('h2', ip='10.0.0.2/24')
    h3 = net.addHost('h3', ip='10.0.0.3/24')
    h4 = net.addHost('h4', ip='10.0.0.4/24')

    net.addLink(h1, s1, bw=100, delay='1ms')
    net.addLink(h2, s1, bw=100, delay='1ms')
    net.addLink(h3, s1, bw=100, delay='1ms')
    net.addLink(h4, s1, bw=100, delay='1ms')

    info('*** Starting network\n')
    net.start()

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

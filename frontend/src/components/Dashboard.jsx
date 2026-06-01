import React from 'react';
import TrafficChart from './TrafficChart';
import TopologyView from './TopologyView';

const StatCard = ({ label, value, sub, color, glowColor }) => (
  <div className="stat-card">
    <div className="stat-glow" style={{ background: glowColor || color }}></div>
    <div className="stat-label">{label}</div>
    <div className="stat-value" style={{ color }}>{value}</div>
    <div className="stat-sub">{sub}</div>
  </div>
);

const Dashboard = ({ state, topologyType, unblockIP }) => {
  const { ports, blocked, log, ml, traffic } = state;
  const attackCount = log.length;
  const maxPps = Object.values(ports).reduce((m, p) => Math.max(m, p.pps || 0), 0);

  return (
    <div>
      {/* Stat cards */}
      <div className="stats-row" style={{ marginTop: '20px' }}>
        <StatCard label="Active Ports" value={Object.keys(ports).length} sub="monitored" color="var(--blue)" />
        <StatCard label="Blocked IPs" value={blocked.length} sub="ACL active" color="var(--red)" />
        <StatCard label="Attacks" value={attackCount} sub="total detected" color="var(--amber)" />
        <StatCard label="Peak pkt/s" value={maxPps.toFixed(0)} sub="current max" color="var(--green)" />
      </div>

      {/* Main grid */}
      <div className="grid">

        {/* Traffic */}
        <div className="card col-2">
          <div className="card-title">
            <span className="dot" style={{ background: 'var(--blue)', boxShadow: '0 0 6px var(--blue)' }}></span>
            Real-time Traffic
          </div>
          <div className="chart-wrap">
            <TrafficChart trafficData={traffic} />
          </div>
        </div>

        {/* Topology */}
        <div className="card">
          <div className="card-title">
            <span className="dot" style={{ background: 'var(--purple)', boxShadow: '0 0 6px var(--purple)' }}></span>
            Network Topology
          </div>
          <div className="topo-wrap">
            <TopologyView topologyType={topologyType} blockedIPs={blocked} />
          </div>
        </div>

        {/* Blocked IPs (ACL) */}
        <div className="card">
          <div className="card-title">
            <span className="dot" style={{ background: 'var(--red)', boxShadow: '0 0 6px var(--red)' }}></span>
            ACL Blocked IPs
            {blocked.length > 0 && (
              <span className="badge badge-red" style={{ marginLeft: 'auto' }}>{blocked.length}</span>
            )}
          </div>
          <div className="ip-list">
            {blocked.length === 0 ? (
              <div className="empty">No blocked IPs — all traffic allowed</div>
            ) : (
              blocked.map((b, i) => (
                <div className="ip-row" key={i}>
                  <span className="ip-addr">{b.ip}</span>
                  <span className="badge badge-amber" style={{fontSize:'9px', padding:'2px 6px'}}>
                    {b.label || 'Unknown'}
                  </span>
                  <span className="badge badge-red">{b.conf}%</span>
                  <span className="ip-meta">{b.time}</span>
                  <button className="unblock-btn" onClick={() => unblockIP(b.ip)}>
                    Unblock
                  </button>
                </div>
              ))
            )}
          </div>
        </div>

        {/* ML Confidence */}
        <div className="card">
          <div className="card-title">
            <span className="dot" style={{ background: 'var(--amber)', boxShadow: '0 0 6px var(--amber)' }}></span>
            ML Confidence
          </div>
          <div className="meter-grid">
            {Object.keys(ml).length === 0 ? (
              <div className="empty" style={{ gridColumn: 'span 2' }}>Waiting for data…</div>
            ) : (
              Object.keys(ml).map((p) => {
                const v = ml[p];
                const conf = v.conf || 0;
                const isAttack = v.pred === 1;
                const color = isAttack ? (conf >= 90 ? 'var(--red)' : 'var(--amber)') : 'var(--green)';
                return (
                  <div key={p}>
                    <div className="meter-label">
                      <span>Port {p}</span>
                      <span style={{ color, fontWeight: 700, fontSize: '10px', fontFamily: 'var(--font-mono)' }}>
                        {isAttack ? 'ATTACK' : 'NORMAL'}
                      </span>
                    </div>
                    <div className="meter-bar-bg">
                      <div className="meter-bar" style={{ width: `${conf}%`, background: color }}></div>
                    </div>
                    <div className="meter-val" style={{ color }}>{conf}%</div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Attack log */}
        <div className="card col-3">
          <div className="card-title">
            <span className="dot" style={{ background: 'var(--amber)', boxShadow: '0 0 6px var(--amber)' }}></span>
            Attack Log
            {log.length > 0 && (
              <span className="badge badge-amber" style={{ marginLeft: 'auto' }}>{log.length} events</span>
            )}
          </div>
          <div className="log-list">
            {log.length === 0 ? (
              <div className="empty">No events</div>
            ) : (
              log.map((l, i) => {
                const conf = l.conf || 0;
                const color = conf >= 90 ? 'var(--red)' : conf >= 70 ? 'var(--amber)' : 'var(--blue)';
                return (
                  <div className="log-row threat" key={i}>
                    <span className="log-time">{l.time}</span>
                    <span className="log-msg">
                      {l.label || 'Attack'} from <strong>{l.ip}</strong>
                      <span style={{opacity:.6, fontSize:'10px'}}> (port {l.port})</span>
                    </span>
                    <span className="log-conf" style={{ color }}>{conf}%</span>
                    <span className="badge badge-red">ACL BLOCKED</span>
                  </div>
                );
              })
            )}
          </div>
        </div>

      </div>
    </div>
  );
};

export default Dashboard;

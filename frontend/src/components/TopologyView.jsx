import React from 'react';

// IP → host mapping for blocked IP detection
const IP_HOST_MAP = {
  '10.0.0.1': 'h1',
  '10.0.0.2': 'h2',
  '10.0.0.3': 'h3',
  '10.0.0.4': 'h4',
  '10.0.0.100': 'server',
};

const TopologyView = ({ topologyType, blockedIPs = [] }) => {
  // ตรวจว่า IP ไหนถูก block อยู่
  const blockedHostSet = new Set(
    blockedIPs.map((b) => IP_HOST_MAP[b.ip]).filter(Boolean)
  );

  const isBlocked = (hostKey) => blockedHostSet.has(hostKey);

  // Shared SVG style helpers
  const sw = (label, x, y, color = '#a57eff') => (
    <g key={label}>
      <rect
        x={x - 34} y={y - 13} width={68} height={26} rx={5}
        fill="rgba(13,21,32,.9)" stroke={color} strokeWidth={1.2}
      />
      <text x={x} y={y + 4.5} textAnchor="middle" fontSize={10} fill={color} fontWeight={600}
        fontFamily="'Space Mono', monospace">
        {label}
      </text>
    </g>
  );

  const host = (label, cx, cy, hostKey, forceColor) => {
    const blocked = isBlocked(hostKey);
    const color = forceColor || (blocked ? '#ff4d6a' : '#00e5a0');
    const fill = blocked ? 'rgba(255,77,106,.15)' : 'rgba(0,229,160,.08)';
    return (
      <g key={label}>
        <circle cx={cx} cy={cy} r={16} fill={fill} stroke={color} strokeWidth={1.3}
          style={blocked ? { filter: 'drop-shadow(0 0 5px rgba(255,77,106,.4))' } : {}} />
        <text x={cx} y={cy + 4} textAnchor="middle" fontSize={10} fill={color} fontWeight={600}
          fontFamily="'Space Mono', monospace">
          {label}
        </text>
        {blocked && (
          <text x={cx} y={cy + 28} textAnchor="middle" fontSize={8} fill="#ff4d6a"
            fontFamily="'Space Mono', monospace" opacity={.8}>
            BLOCKED
          </text>
        )}
      </g>
    );
  };

  const server = (x, y) => {
    const blocked = isBlocked('server');
    const color = blocked ? '#ff4d6a' : '#4da6ff';
    return (
      <g key="server">
        {/* Server icon (rectangle with lines) */}
        <rect x={x - 22} y={y - 16} width={44} height={32} rx={4}
          fill="rgba(13,21,32,.9)" stroke={color} strokeWidth={1.3}
          style={{ filter: `drop-shadow(0 0 6px ${color}44)` }} />
        <line x1={x - 14} y1={y - 6} x2={x + 14} y2={y - 6} stroke={color} strokeWidth={0.8} opacity={0.5} />
        <line x1={x - 14} y1={y + 2} x2={x + 14} y2={y + 2} stroke={color} strokeWidth={0.8} opacity={0.5} />
        <circle cx={x + 10} cy={y + 10} r={2} fill={color} opacity={0.8} />
        <text x={x} y={y + 30} textAnchor="middle" fontSize={9} fill={color}
          fontFamily="'Space Mono', monospace" fontWeight={600}>
          WEB SRV
        </text>
        <text x={x} y={y + 40} textAnchor="middle" fontSize={7} fill={color}
          fontFamily="'Space Mono', monospace" opacity={0.6}>
          10.0.0.100
        </text>
      </g>
    );
  };

  const ctrl = (x, y) => (
    <g key="ctrl">
      <rect x={x - 44} y={y - 14} width={88} height={28} rx={6}
        fill="rgba(13,21,32,.9)" stroke="#4da6ff" strokeWidth={1.3}
        style={{ filter: 'drop-shadow(0 0 8px rgba(77,166,255,.3))' }} />
      <text x={x} y={y + 4.5} textAnchor="middle" fontSize={10} fill="#4da6ff" fontWeight={700}
        fontFamily="'Space Mono', monospace">
        CONTROLLER
      </text>
    </g>
  );

  const line = (x1, y1, x2, y2, hostKey = null) => {
    const blocked = hostKey && isBlocked(hostKey);
    const stroke = blocked ? '#ff4d6a' : '#1e2d42';
    const dash = blocked ? '5 3' : 'none';
    return (
      <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={stroke} strokeWidth={1}
        strokeDasharray={dash} />
    );
  };

  const dottedLine = (x1, y1, x2, y2) => (
    <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="#1e2d42" strokeWidth={1}
      strokeDasharray="4 3" />
  );

  // ── DEFAULT / STAR ──
  if (!topologyType || topologyType === 'default') {
    return (
      <svg viewBox="0 0 260 240" width={260} height={240}>
        {/* Controller */}
        {ctrl(130, 18)}
        {dottedLine(130, 32, 130, 56)}
        {/* Server */}
        {server(210, 50)}
        {/* Switch */}
        {sw('SW s1', 130, 70, '#a57eff')}
        {/* Server → Switch link */}
        {line(188, 50, 164, 66)}
        {/* Switch → hosts */}
        {line(114, 83, 40, 150, 'h1')}
        {line(118, 83, 100, 150, 'h2')}
        {line(142, 83, 160, 150, 'h3')}
        {line(146, 83, 220, 150, 'h4')}
        {/* Hosts */}
        {host('h1', 40, 166, 'h1')}
        {host('h2', 100, 166, 'h2')}
        {host('h3', 160, 166, 'h3')}
        {host('h4', 220, 166, 'h4')}
      </svg>
    );
  }

  // ── TREE ──
  if (topologyType === 'tree') {
    return (
      <svg viewBox="0 0 260 240" width={260} height={240}>
        {ctrl(130, 16)}
        {dottedLine(130, 30, 130, 48)}
        {server(220, 45)}
        {sw('CORE', 130, 60, '#a57eff')}
        {line(188, 50, 164, 56)}
        {line(106, 73, 68, 97)}
        {line(154, 73, 192, 97)}
        {sw('EDGE 1', 68, 110, '#a57eff')}
        {sw('EDGE 2', 192, 110, '#a57eff')}
        {line(52, 123, 38, 147, 'h1')}
        {line(68, 123, 82, 147, 'h2')}
        {line(176, 123, 162, 147, 'h3')}
        {line(206, 123, 220, 147, 'h4')}
        {host('h1', 38, 163, 'h1')}
        {host('h2', 82, 163, 'h2')}
        {host('h3', 162, 163, 'h3')}
        {host('h4', 220, 163, 'h4')}
      </svg>
    );
  }

  // ── MESH ──
  return (
    <svg viewBox="0 0 260 240" width={260} height={240}>
      {ctrl(130, 14)}
      {dottedLine(108, 28, 76, 50)}
      {dottedLine(152, 28, 184, 50)}
      {server(130, 50)}
      {sw('SW1', 64, 63)}
      {sw('SW2', 196, 63)}
      {sw('SW3', 64, 123)}
      {sw('SW4', 196, 123)}
      {/* mesh links */}
      <line x1={98} y1={63} x2={162} y2={63} stroke="#243547" strokeWidth={1} />
      <line x1={98} y1={123} x2={162} y2={123} stroke="#243547" strokeWidth={1} />
      <line x1={64} y1={76} x2={64} y2={110} stroke="#243547" strokeWidth={1} />
      <line x1={196} y1={76} x2={196} y2={110} stroke="#243547" strokeWidth={1} />
      <line x1={98} y1={76} x2={162} y2={110} stroke="#243547" strokeWidth={1} />
      <line x1={162} y1={76} x2={98} y2={110} stroke="#243547" strokeWidth={1} />
      {/* hosts */}
      {line(50, 136, 38, 158, 'h1')}
      {line(80, 136, 86, 158, 'h2')}
      {line(182, 136, 174, 158, 'h3')}
      {line(210, 136, 222, 158, 'h4')}
      {host('h1', 38, 174, 'h1')}
      {host('h2', 86, 174, 'h2')}
      {host('h3', 174, 174, 'h3')}
      {host('h4', 222, 174, 'h4')}
    </svg>
  );
};

export default TopologyView;

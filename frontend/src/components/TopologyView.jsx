import React from 'react';

const TopologyView = ({ topologyType, blockedPorts = [] }) => {
  const isAttackerBlocked = blockedPorts.some((p) => p.port === 4 || p.port === '4');
  const attackStroke = isAttackerBlocked ? '#ff4d6a' : '#1e2d42';
  const attackDash = isAttackerBlocked ? '5 3' : 'none';
  const attackFill = isAttackerBlocked ? 'rgba(255,77,106,.15)' : 'rgba(255,77,106,.08)';

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

  const host = (label, cx, cy, color = '#00e5a0', fill = 'rgba(0,229,160,.08)', isAttacker = false) => (
    <g key={label}>
      <circle cx={cx} cy={cy} r={16} fill={fill} stroke={color} strokeWidth={1.3}
        style={isAttacker ? { filter: 'drop-shadow(0 0 5px rgba(255,77,106,.4))' } : {}} />
      <text x={cx} y={cy + 4} textAnchor="middle" fontSize={10} fill={color} fontWeight={600}
        fontFamily="'Space Mono', monospace">
        {label}
      </text>
    </g>
  );

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

  const line = (x1, y1, x2, y2, stroke = '#1e2d42', dash = 'none', width = 1) => (
    <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={stroke} strokeWidth={width}
      strokeDasharray={dash} />
  );

  // ── DEFAULT / STAR ──
  if (!topologyType || topologyType === 'default') {
    return (
      <svg viewBox="0 0 240 210" width={240} height={210}>
        {ctrl(120, 22)}
        {line(120, 36, 120, 74, '#1e2d42', '4 3')}
        {sw('SW s1', 120, 87, '#a57eff')}
        {line(104, 100, 40, 150)}
        {line(108, 100, 90, 150)}
        {line(132, 100, 150, 150)}
        {line(136, 100, 200, 150, attackStroke, attackDash)}
        {host('h1', 40, 166, '#00e5a0', 'rgba(0,229,160,.08)')}
        {host('h2', 90, 166, '#00e5a0', 'rgba(0,229,160,.08)')}
        {host('h3', 150, 166, '#00e5a0', 'rgba(0,229,160,.08)')}
        {host('h4', 200, 166, '#ff4d6a', attackFill, true)}
        <text x={200} y={190} textAnchor="middle" fontSize={9} fill="#ff4d6a"
          fontFamily="'Space Mono', monospace" opacity={.8}>
          ATTACKER
        </text>
      </svg>
    );
  }

  // ── TREE ──
  if (topologyType === 'tree') {
    return (
      <svg viewBox="0 0 240 210" width={240} height={210}>
        {ctrl(120, 20)}
        {line(120, 34, 120, 52, '#1e2d42', '4 3')}
        {sw('CORE', 120, 65, '#a57eff')}
        {line(96, 78, 58, 102)}
        {line(144, 78, 182, 102)}
        {sw('EDGE 1', 58, 115, '#a57eff')}
        {sw('EDGE 2', 182, 115, '#a57eff')}
        {line(42, 128, 28, 152)}
        {line(58, 128, 72, 152)}
        {line(166, 128, 152, 152)}
        {line(196, 128, 210, 152, attackStroke, attackDash)}
        {host('h1', 28, 168, '#00e5a0', 'rgba(0,229,160,.08)')}
        {host('h2', 72, 168, '#00e5a0', 'rgba(0,229,160,.08)')}
        {host('h3', 152, 168, '#00e5a0', 'rgba(0,229,160,.08)')}
        {host('h4', 210, 168, '#ff4d6a', attackFill, true)}
      </svg>
    );
  }

  // ── MESH ──
  return (
    <svg viewBox="0 0 240 210" width={240} height={210}>
      {ctrl(120, 18)}
      {line(98, 32, 66, 54, '#1e2d42', '3 3')}
      {line(142, 32, 174, 54, '#1e2d42', '3 3')}
      {sw('SW1', 54, 67)}
      {sw('SW2', 186, 67)}
      {sw('SW3', 54, 127)}
      {sw('SW4', 186, 127)}
      {/* mesh links */}
      {line(88, 67, 152, 67, '#243547')}
      {line(88, 127, 152, 127, '#243547')}
      {line(54, 80, 54, 114, '#243547')}
      {line(186, 80, 186, 114, '#243547')}
      {line(88, 80, 152, 114, '#243547')}
      {line(152, 80, 88, 114, '#243547')}
      {/* hosts */}
      {line(40, 140, 28, 162)}
      {line(70, 140, 76, 162)}
      {line(172, 140, 164, 162)}
      {line(200, 140, 212, 162, attackStroke, attackDash)}
      {host('h1', 28, 178, '#00e5a0', 'rgba(0,229,160,.08)')}
      {host('h2', 76, 178, '#00e5a0', 'rgba(0,229,160,.08)')}
      {host('h3', 164, 178, '#00e5a0', 'rgba(0,229,160,.08)')}
      {host('h4', 212, 178, '#ff4d6a', attackFill, true)}
    </svg>
  );
};

export default TopologyView;

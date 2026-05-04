// import React, { useState, useEffect, useRef } from 'react';

// const API_BASE = 'http://localhost:5000';

// const STEPS = [
//   { label: 'Stop existing Mininet' },
//   { label: 'Clear OVS + wait for Ryu restart' },
//   { label: 'Launch new Mininet' },
//   { label: 'Connection established' },
// ];

// const TOPOLOGY_OPTIONS = [
//   { id: 'default', name: 'Star', desc: '1 Switch · 4 Hosts', icon: '⭐' },
//   { id: 'tree',    name: 'Tree',  desc: '3 Switches · 4 Hosts', icon: '🌲' },
//   { id: 'mesh',    name: 'Mesh',  desc: '4 Switches · 4 Hosts', icon: '🕸️' },
// ];

// const TopologySelector = ({ topologyType, setTopologyType }) => {
//   const [pending,  setPending]  = useState(topologyType);
//   const [uiState,  setUiState]  = useState('idle');
//   const [srvState, setSrvState] = useState({ state: 'idle', message: '' });
//   const [stepIdx,  setStepIdx]  = useState(0);
//   const pollRef = useRef(null);

//   const stopPoll = () => {
//     if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
//   };

//   const startPoll = () => {
//     stopPoll();
//     let idx = 0;
//     pollRef.current = setInterval(async () => {
//       try {
//         const res  = await fetch(`${API_BASE}/api/topology/status`);
//         const data = await res.json();
//         setSrvState(data);
//         if (data.state === 'restarting') { idx = Math.min(idx + 1, 2); setStepIdx(idx); }
//         if (data.state === 'ready')  { setStepIdx(3); setUiState('done'); setTopologyType(data.topology); stopPoll(); }
//         if (data.state === 'error')  { setUiState('error'); stopPoll(); }
//       } catch { /* network blip during restart */ }
//     }, 1500);
//   };

//   useEffect(() => () => stopPoll(), []);

//   const handleApply = async () => {
//     if (uiState === 'applying') return;
//     if (!window.confirm(`Deploy ${pending} topology and restart Mininet?`)) return;

//     setUiState('applying');
//     setStepIdx(0);
//     setSrvState({ state: 'restarting', message: 'Sending command…' });

//     try {
//       const res  = await fetch(`${API_BASE}/api/topology/apply`, {
//         method: 'POST',
//         headers: { 'Content-Type': 'application/json' },
//         body: JSON.stringify({ topology: pending }),
//       });
//       const data = await res.json();
//       if (!data.ok) { setUiState('error'); setSrvState({ state: 'error', message: data.error }); return; }
//       startPoll();
//     } catch (err) {
//       setUiState('error');
//       setSrvState({ state: 'error', message: `Cannot connect to API: ${err.message}` });
//     }
//   };

//   const isApplying = uiState === 'applying';

//   return (
//     <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>

//       {/* Topology cards */}
//       <div className="topo-options">
//         {TOPOLOGY_OPTIONS.map((opt) => (
//           <div
//             key={opt.id}
//             className={`topo-option${pending === opt.id ? ' selected' : ''}${isApplying ? ' disabled' : ''}`}
//             onClick={() => { if (!isApplying) { setPending(opt.id); setUiState('idle'); } }}
//           >
//             <div className="topo-icon">{opt.icon}</div>
//             <div className="topo-name">{opt.name}</div>
//             <div className="topo-desc">{opt.desc}</div>
//           </div>
//         ))}
//       </div>

//       {/* Deploy button */}
//       <button
//         className="deploy-btn"
//         onClick={handleApply}
//         disabled={isApplying || (pending === topologyType && uiState === 'done')}
//       >
//         {isApplying ? '⏳ Deploying…' : '🚀 Deploy Topology'}
//       </button>

//       {/* Step progress */}
//       {(isApplying || uiState === 'done') && (
//         <div className="card" style={{ gap: '0' }}>
//           <div className="card-title" style={{ marginBottom: '14px' }}>Deployment Progress</div>
//           <div className="step-list">
//             {STEPS.map((s, i) => {
//               const done    = i < stepIdx || uiState === 'done';
//               const current = i === stepIdx && isApplying;
//               return (
//                 <div className="step-item" key={i}>
//                   <span className="step-icon">{done ? '✅' : current ? '⏳' : '⬜'}</span>
//                   <span className={`step-label${done ? ' done' : current ? ' active' : ''}`}>
//                     {s.label}
//                   </span>
//                 </div>
//               );
//             })}
//           </div>
//         </div>
//       )}

//       {/* Server message */}
//       {srvState.message && (
//         <div
//           className="status-banner"
//           style={{
//             borderLeftColor: uiState === 'error' ? 'var(--red)' : uiState === 'done' ? 'var(--green)' : 'var(--amber)',
//             background: uiState === 'error' ? 'var(--red-dim)' : 'var(--bg3)',
//           }}
//         >
//           {srvState.message}
//         </div>
//       )}

//       {uiState === 'error' && (
//         <button
//           className="deploy-btn"
//           style={{ background: 'var(--bg3)', color: 'var(--text)', border: '1px solid var(--border)' }}
//           onClick={() => { setUiState('idle'); setSrvState({ state: 'idle', message: '' }); }}
//         >
//           Try Again
//         </button>
//       )}
//     </div>
//   );
// };

// export default TopologySelector;

import React, { useState, useEffect, useRef } from 'react';

const API_BASE = 'http://localhost:5000';

const STEPS = [
  { label: 'Stop existing Mininet' },
  { label: 'Clear OVS + wait for Ryu restart' },
  { label: 'Launch new Mininet' },
  { label: 'Connection established' },
];

// ─── SVG Topology Diagrams ───
const StarDiagram = ({ active }) => (
  <svg width="52" height="52" viewBox="0 0 48 48" fill="none">
    <circle cx="24" cy="24" r="7"
      fill={active ? 'rgba(88,166,255,0.15)' : 'rgba(255,255,255,0.04)'}
      stroke={active ? '#58a6ff' : '#484f58'} strokeWidth="1.5"/>
    {[[24,8],[38,32],[10,32],[38,14],[10,14]].map(([cx,cy],i) => (
      <circle key={i} cx={cx} cy={cy} r="4" fill="#21262d" stroke={active ? 'rgba(88,166,255,0.4)' : '#30363d'} strokeWidth="1.5"/>
    ))}
    {[[24,17,24,12],[29,21,35,17],[29,27,35,30],[19,27,13,30],[19,21,13,17]].map(([x1,y1,x2,y2],i) => (
      <line key={i} x1={x1} y1={y1} x2={x2} y2={y2}
        stroke={active ? '#58a6ff' : '#484f58'}
        strokeWidth="1" strokeDasharray={active ? '2 1' : undefined} opacity={active ? 0.8 : 0.5}/>
    ))}
  </svg>
);

const TreeDiagram = ({ active }) => (
  <svg width="52" height="52" viewBox="0 0 48 48" fill="none">
    <rect x="20" y="4" width="8" height="8" rx="2" fill="#21262d"
      stroke={active ? '#58a6ff' : '#484f58'} strokeWidth="1.5"/>
    <rect x="8"  y="20" width="8" height="8" rx="2" fill="#21262d" stroke={active ? 'rgba(88,166,255,0.4)' : '#30363d'} strokeWidth="1.5"/>
    <rect x="32" y="20" width="8" height="8" rx="2" fill="#21262d" stroke={active ? 'rgba(88,166,255,0.4)' : '#30363d'} strokeWidth="1.5"/>
    {[[6,40],[16,40],[32,40],[42,40]].map(([cx,cy],i) => (
      <circle key={i} cx={cx} cy={cy} r="3.5" fill="#21262d" stroke={active ? 'rgba(88,166,255,0.3)' : '#30363d'} strokeWidth="1.5"/>
    ))}
    {[[24,12,12,20],[24,12,36,20],[12,28,6,36],[12,28,16,36],[36,28,32,36],[36,28,42,36]].map(([x1,y1,x2,y2],i) => (
      <line key={i} x1={x1} y1={y1} x2={x2} y2={y2}
        stroke={active ? '#58a6ff' : '#484f58'} strokeWidth="1" opacity={active ? 0.7 : 0.5}/>
    ))}
  </svg>
);

const MeshDiagram = ({ active }) => (
  <svg width="52" height="52" viewBox="0 0 48 48" fill="none">
    {[[12,12],[36,12],[12,36],[36,36]].map(([cx,cy],i) => (
      <circle key={i} cx={cx} cy={cy} r="5" fill="#21262d"
        stroke={i===0 && active ? '#58a6ff' : active ? 'rgba(88,166,255,0.4)' : '#30363d'} strokeWidth="1.5"/>
    ))}
    {[[17,12,31,12],[12,17,12,31],[36,17,36,31],[17,36,31,36]].map(([x1,y1,x2,y2],i) => (
      <line key={i} x1={x1} y1={y1} x2={x2} y2={y2}
        stroke={active ? '#58a6ff' : '#484f58'} strokeWidth="1" opacity={active ? 0.7 : 0.5}/>
    ))}
    <line x1="15.5" y1="15.5" x2="32.5" y2="32.5" stroke={active ? '#58a6ff' : '#484f58'} strokeWidth="1" opacity={active ? 0.4 : 0.3}/>
    <line x1="32.5" y1="15.5" x2="15.5" y2="32.5" stroke={active ? '#58a6ff' : '#484f58'} strokeWidth="1" opacity={active ? 0.4 : 0.3}/>
  </svg>
);

const TOPOLOGY_OPTIONS = [
  {
    id: 'default',
    name: 'Star',
    description: 'Single central switch connecting all hosts — minimal latency, single point of failure.',
    switches: 1,
    hosts: 4,
    Diagram: StarDiagram,
  },
  {
    id: 'tree',
    name: 'Tree',
    description: 'Hierarchical switch arrangement for scalable segmentation and traffic isolation.',
    switches: 3,
    hosts: 4,
    Diagram: TreeDiagram,
  },
  {
    id: 'mesh',
    name: 'Mesh',
    description: 'Fully-connected switches offering redundant paths and high fault tolerance.',
    switches: 4,
    hosts: 4,
    Diagram: MeshDiagram,
  },
];

// ─── Confirm Modal ───
const ConfirmModal = ({ topoName, onConfirm, onCancel }) => (
  <div style={{
    position: 'fixed', inset: 0, zIndex: 50,
    background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(2px)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
  }}>
    <div style={{
      background: 'var(--bg2, #161b22)',
      border: '1px solid var(--border, #30363d)',
      borderRadius: '10px', padding: '28px 24px',
      width: '360px', textAlign: 'center',
    }}>
      <div style={{ fontSize: '15px', fontWeight: 600, marginBottom: '10px' }}>
        Deploy {topoName} topology?
      </div>
      <div style={{ fontSize: '12px', color: 'var(--muted, #7d8590)', lineHeight: '1.7', marginBottom: '22px' }}>
        This will modify{' '}
        <code style={{
          fontSize: '11px', background: 'var(--bg3, #21262d)',
          padding: '1px 5px', borderRadius: '4px',
        }}>network_topology.py</code>{' '}
        and restart Mininet and the Ryu controller. The process takes 10–20 seconds.
      </div>
      <div style={{ display: 'flex', gap: '8px', justifyContent: 'center' }}>
        <button onClick={onCancel} style={{
          padding: '8px 20px', borderRadius: '6px',
          border: '1px solid var(--border, #30363d)',
          background: 'transparent', color: 'var(--muted, #7d8590)',
          cursor: 'pointer', fontSize: '13px', transition: 'all 0.15s',
        }}>Cancel</button>
        <button onClick={onConfirm} style={{
          padding: '8px 20px', borderRadius: '6px', border: 'none',
          background: 'var(--blue, #58a6ff)', color: '#0d1117',
          cursor: 'pointer', fontSize: '13px', fontWeight: 600, transition: 'all 0.15s',
        }}>Deploy</button>
      </div>
    </div>
  </div>
);

// ─── Step Progress Card ───
const StepProgress = ({ stepIdx, isDone }) => (
  <div style={{
    background: 'var(--bg2, #161b22)',
    border: '1px solid var(--border, #30363d)',
    borderRadius: '10px', padding: '16px 18px',
  }}>
    <div style={{
      fontSize: '11px', fontWeight: 600, letterSpacing: '1px',
      textTransform: 'uppercase', color: 'var(--muted, #7d8590)',
      marginBottom: '14px',
    }}>Deployment Progress</div>
    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
      {STEPS.map((s, i) => {
        const done    = i < stepIdx || isDone;
        const current = i === stepIdx && !isDone;
        return (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div style={{
              width: '20px', height: '20px', borderRadius: '50%', flexShrink: 0,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              background: done
                ? 'rgba(63,185,80,0.15)'
                : current
                  ? 'rgba(88,166,255,0.15)'
                  : 'var(--bg3, #21262d)',
              border: `1px solid ${done ? 'var(--green, #3fb950)' : current ? 'var(--blue, #58a6ff)' : 'var(--border, #30363d)'}`,
              transition: 'all 0.3s',
            }}>
              {done ? (
                <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                  <path d="M2 5l2.5 2.5L8 3" stroke="#3fb950" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              ) : current ? (
                <div style={{
                  width: '6px', height: '6px', borderRadius: '50%',
                  background: 'var(--blue, #58a6ff)',
                  animation: 'topoFade 1.2s ease-in-out infinite',
                }}/>
              ) : (
                <div style={{ width: '6px', height: '6px', borderRadius: '50%', background: 'var(--border, #30363d)' }}/>
              )}
            </div>
            <span style={{
              fontSize: '12px',
              color: done ? 'var(--green, #3fb950)' : current ? 'var(--text, #e6edf3)' : 'var(--muted, #7d8590)',
              fontWeight: current ? 500 : 400,
              transition: 'color 0.3s',
            }}>
              {s.label}
            </span>
          </div>
        );
      })}
    </div>
  </div>
);

// ─── Main Component ───
const TopologySelector = ({ topologyType, setTopologyType }) => {
  const [pending,   setPending]   = useState(topologyType);
  const [uiState,   setUiState]   = useState('idle');
  const [srvState,  setSrvState]  = useState({ state: 'idle', message: '' });
  const [stepIdx,   setStepIdx]   = useState(0);
  const [showModal, setShowModal] = useState(false);
  const [progress,  setProgress]  = useState(0);
  const pollRef    = useRef(null);
  const progressRef = useRef(null);

  const stopPoll = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  };
  const stopProgress = () => {
    if (progressRef.current) { clearInterval(progressRef.current); progressRef.current = null; }
  };

  const startProgressBar = () => {
    setProgress(0);
    stopProgress();
    progressRef.current = setInterval(() => {
      setProgress(prev => {
        if (prev >= 90) { stopProgress(); return prev; }
        return prev + Math.random() * 8;
      });
    }, 800);
  };

  const startPoll = () => {
    stopPoll();
    let idx = 0;
    pollRef.current = setInterval(async () => {
      try {
        const res  = await fetch(`${API_BASE}/api/topology/status`);
        const data = await res.json();
        setSrvState(data);
        if (data.state === 'restarting') { idx = Math.min(idx + 1, 2); setStepIdx(idx); }
        if (data.state === 'ready') {
          setStepIdx(3);
          setUiState('done');
          setTopologyType(data.topology);
          stopPoll();
          stopProgress();
          setProgress(100);
        }
        if (data.state === 'error') { setUiState('error'); stopPoll(); stopProgress(); }
      } catch { /* network blip during restart */ }
    }, 1500);
  };

  useEffect(() => () => { stopPoll(); stopProgress(); }, []);

  const handleDeployClick = () => {
    if (uiState === 'applying') return;
    setShowModal(true);
  };

  const handleConfirm = async () => {
    setShowModal(false);
    setUiState('applying');
    setStepIdx(0);
    setSrvState({ state: 'restarting', message: 'Sending command…' });
    startProgressBar();

    try {
      const res  = await fetch(`${API_BASE}/api/topology/apply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topology: pending }),
      });
      const data = await res.json();
      if (!data.ok) {
        setUiState('error');
        setSrvState({ state: 'error', message: data.error });
        stopProgress();
        return;
      }
      startPoll();
    } catch (err) {
      setUiState('error');
      setSrvState({ state: 'error', message: `Cannot connect to API: ${err.message}` });
      stopProgress();
    }
  };

  const isApplying = uiState === 'applying';
  const isDone     = uiState === 'done';
  const isError    = uiState === 'error';
  const deployDisabled = isApplying || (pending === topologyType && isDone);

  return (
    <>
      <style>{`
        @keyframes topoFade {
          0%,100% { opacity:1; transform:scale(1); }
          50% { opacity:0.4; transform:scale(0.7); }
        }
        .topo-card-new {
          background: var(--bg2, #161b22);
          border: 1px solid var(--border, #30363d);
          border-radius: 10px;
          padding: 18px 16px;
          cursor: pointer;
          transition: background 0.2s, border-color 0.2s, transform 0.15s;
          position: relative;
          user-select: none;
        }
        .topo-card-new:hover:not(.disabled) {
          background: var(--bg3, #21262d);
          transform: translateY(-1px);
        }
        .topo-card-new.active {
          background: rgba(88,166,255,0.06);
          border-color: rgba(88,166,255,0.35);
          box-shadow: inset 0 0 0 1px rgba(88,166,255,0.25);
        }
        .topo-card-new.disabled { cursor: not-allowed; opacity: 0.6; }
        .deploy-btn-new {
          width: 100%;
          padding: 13px;
          border-radius: 8px;
          border: none;
          cursor: pointer;
          background: var(--blue, #58a6ff);
          color: #0d1117;
          font-size: 14px;
          font-weight: 700;
          letter-spacing: 0.3px;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          transition: opacity 0.15s, transform 0.15s;
        }
        .deploy-btn-new:hover:not(:disabled) { opacity: 0.88; transform: translateY(-1px); }
        .deploy-btn-new:active:not(:disabled) { transform: translateY(0); }
        .deploy-btn-new:disabled { opacity: 0.42; cursor: not-allowed; }
      `}</style>

      {showModal && (
        <ConfirmModal
          topoName={TOPOLOGY_OPTIONS.find(o => o.id === pending)?.name || pending}
          onConfirm={handleConfirm}
          onCancel={() => setShowModal(false)}
        />
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>

        {/* ── Topology Cards ── */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: '12px' }}>
          {TOPOLOGY_OPTIONS.map((opt) => {
            const isActive = pending === opt.id;
            return (
              <div
                key={opt.id}
                className={`topo-card-new${isActive ? ' active' : ''}${isApplying ? ' disabled' : ''}`}
                onClick={() => { if (!isApplying) { setPending(opt.id); if (!isDone) setUiState('idle'); } }}
              >
                {/* Active badge */}
                {opt.id === topologyType && (
                  <span style={{
                    position: 'absolute', top: '10px', right: '10px',
                    fontSize: '9px', fontWeight: 700, letterSpacing: '0.8px',
                    textTransform: 'uppercase', padding: '2px 7px', borderRadius: '20px',
                    background: 'rgba(88,166,255,0.12)', color: 'var(--blue, #58a6ff)',
                    border: '1px solid rgba(88,166,255,0.25)',
                  }}>Active</span>
                )}
                <opt.Diagram active={isActive} />
                <div style={{ fontSize: '14px', fontWeight: 600, marginTop: '12px', marginBottom: '5px' }}>
                  {opt.name}
                </div>
                <div style={{
                  fontSize: '11px', color: 'var(--muted, #7d8590)',
                  lineHeight: '1.55', marginBottom: '12px',
                }}>
                  {opt.description}
                </div>
                <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                  {[`${opt.switches} Switch${opt.switches > 1 ? 'es' : ''}`, `${opt.hosts} Hosts`].map(label => (
                    <span key={label} style={{
                      fontSize: '10px', fontWeight: 600, padding: '2px 8px',
                      borderRadius: '20px', letterSpacing: '0.3px',
                      background: isActive ? 'rgba(88,166,255,0.1)' : 'var(--bg3, #21262d)',
                      color: isActive ? 'var(--blue, #58a6ff)' : 'var(--muted, #7d8590)',
                      border: `1px solid ${isActive ? 'rgba(88,166,255,0.25)' : 'var(--border, #30363d)'}`,
                      transition: 'all 0.2s',
                    }}>{label}</span>
                  ))}
                </div>
              </div>
            );
          })}
        </div>

        {/* ── Deploy Button ── */}
        <button
          className="deploy-btn-new"
          onClick={handleDeployClick}
          disabled={deployDisabled}
        >
          {isApplying ? (
            <>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                style={{ animation: 'spin 1s linear infinite' }}>
                <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
              </svg>
              Deploying…
            </>
          ) : (
            <>
              Deploy Topology
            </>
          )}
        </button>

        {/* ── Progress Bar (during deploy) ── */}
        {(isApplying || isDone) && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: '12px',
            background: 'var(--bg2, #161b22)',
            border: '1px solid var(--border, #30363d)',
            borderRadius: '8px', padding: '12px 16px',
          }}>
            <div style={{
              width: '8px', height: '8px', borderRadius: '50%', flexShrink: 0,
              background: isDone ? 'var(--green, #3fb950)' : 'var(--blue, #58a6ff)',
              animation: isDone ? 'none' : 'topoFade 1.2s ease-in-out infinite',
            }}/>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: '12px', marginBottom: '7px' }}>
                <strong style={{ color: isDone ? 'var(--green, #3fb950)' : 'var(--blue, #58a6ff)' }}>
                  {isDone
                    ? `${TOPOLOGY_OPTIONS.find(o => o.id === pending)?.name} topology deployed successfully`
                    : `Deploying ${TOPOLOGY_OPTIONS.find(o => o.id === pending)?.name} topology…`}
                </strong>
                {!isDone && (
                  <span style={{ color: 'var(--muted, #7d8590)' }}> — restarting Mininet and Ryu controller</span>
                )}
              </div>
              <div style={{
                height: '3px', background: 'var(--bg3, #21262d)',
                borderRadius: '99px', overflow: 'hidden',
              }}>
                <div style={{
                  height: '100%', borderRadius: '99px',
                  background: isDone ? 'var(--green, #3fb950)' : 'var(--blue, #58a6ff)',
                  width: `${Math.min(progress, 100)}%`,
                  transition: 'width 0.5s ease',
                }}/>
              </div>
            </div>
          </div>
        )}

        {/* ── Step Progress ── */}
        {(isApplying || isDone) && (
          <StepProgress stepIdx={stepIdx} isDone={isDone} />
        )}

        {/* ── Error / Server Message ── */}
        {isError && srvState.message && (
          <div style={{
            background: 'rgba(248,81,73,0.08)',
            border: '1px solid rgba(248,81,73,0.25)',
            borderLeft: '3px solid var(--red, #f85149)',
            borderRadius: '0 8px 8px 0',
            padding: '10px 14px',
            fontSize: '12px',
            color: 'var(--muted, #7d8590)',
          }}>
            <strong style={{ color: 'var(--red, #f85149)' }}>Error: </strong>
            {srvState.message}
          </div>
        )}

        {isError && (
          <button
            className="deploy-btn-new"
            style={{ background: 'var(--bg3, #21262d)', color: 'var(--text, #e6edf3)', border: '1px solid var(--border, #30363d)' }}
            onClick={() => { setUiState('idle'); setSrvState({ state: 'idle', message: '' }); setProgress(0); }}
          >
            Try Again
          </button>
        )}
      </div>
    </>
  );
};

export default TopologySelector;
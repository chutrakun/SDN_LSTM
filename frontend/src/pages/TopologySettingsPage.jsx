// import React from 'react';
// import TopologySelector from '../components/TopologySelector';

// const TopologySettingsPage = ({ topologyType, setTopologyType }) => {
//   return (
//     <div
//       className="page-container"
//       style={{ padding: '32px 24px', maxWidth: '960px', margin: '0 auto' }}
//     >
//       {/* ── Page Header ── */}
//       <div style={{
//         marginBottom: '32px',
//         paddingBottom: '20px',
//         borderBottom: '1px solid var(--border)',
//       }}>
//         <div style={{
//           fontSize: '11px',
//           fontWeight: 600,
//           letterSpacing: '1px',
//           textTransform: 'uppercase',
//           color: 'var(--muted)',
//           marginBottom: '10px',
//           display: 'flex',
//           alignItems: 'center',
//           gap: '6px',
//         }}>
//           <span style={{ color: 'var(--blue)' }}>SDN·SEC</span>
//           <span style={{ opacity: 0.4 }}>/</span>
//           Network Topology
//         </div>
//         <h2 style={{ fontSize: '26px', fontWeight: 600, marginBottom: '6px' }}>
//           Network Topology
//         </h2>
//         <p style={{ color: 'var(--muted)', fontSize: '15px', lineHeight: '1.65', maxWidth: '620px' }}>
//           Configure the underlying Mininet SDN structure. The backend persists the selected topology, restarts Mininet, and waits for Ryu to verify the live graph.
//         </p>
//       </div>

//       {/* ── Topology Selector Component ── */}
//       <div style={{ marginBottom: '8px' }}>
//         <div style={{
//           fontSize: '11px',
//           fontWeight: 600,
//           letterSpacing: '1.2px',
//           textTransform: 'uppercase',
//           color: 'var(--muted)',
//           marginBottom: '14px',
//         }}>
//           Select topology
//         </div>
//         <TopologySelector
//           topologyType={topologyType}
//           setTopologyType={setTopologyType}
//         />
//       </div>

//       {/* ── Warning Box ── */}
//       <div style={{
//         marginTop: '16px',
//         background: 'rgba(210, 153, 34, 0.07)',
//         border: '1px solid rgba(210, 153, 34, 0.25)',
//         borderLeft: '3px solid var(--amber)',
//         borderRadius: '0 8px 8px 0',
//         padding: '12px 16px',
//         display: 'flex',
//         gap: '12px',
//         alignItems: 'flex-start',
//       }}>
//         <svg
//           width="14" height="14" viewBox="0 0 16 16"
//           fill="var(--amber)"
//           style={{ flexShrink: 0, marginTop: '1px' }}
//         >
//           <path d="M8.982 1.566a1.13 1.13 0 0 0-1.96 0L.165 13.233c-.457.778.091 1.767.98 1.767h13.713c.889 0 1.438-.99.98-1.767L8.982 1.566zM8 5c.535 0 .954.462.9.995l-.35 3.507a.552.552 0 0 1-1.1 0L7.1 5.995A.905.905 0 0 1 8 5zm.002 6a1 1 0 1 1 0 2 1 1 0 0 1 0-2z"/>
//         </svg>
//         <div style={{ fontSize: '14px', color: 'var(--muted)', lineHeight: '1.65' }}>
//           <strong style={{ color: 'var(--amber)', fontWeight: 600 }}>Warning: </strong>
//           Confirming will modify{' '}
//           <code style={{
//             fontSize: '11px',
//             background: 'rgba(255,255,255,0.06)',
//             padding: '1px 5px',
//             borderRadius: '4px',
//           }}>
//             network_topology.py
//           </code>{' '}
//           on the server and clear the existing Mininet environment (removes veth interfaces and OVS bridges)
//           before relaunching automatically. This process may take 10–20 seconds.
//         </div>
//       </div>
//     </div>
//   );
// };

// export default TopologySettingsPage;
import React from 'react';
import TopologySelector from '../components/TopologySelector';

const TopologySettingsPage = ({ topologyType, setTopologyType }) => {
  return (
    <div
      className="page-container"
      style={{ padding: '32px 24px', maxWidth: '960px', margin: '0 auto' }}
    >
      {/* ── Page Header ── */}
      <div style={{
        marginBottom: '32px',
        paddingBottom: '20px',
        borderBottom: '1px solid var(--border)',
      }}>
        <h2 style={{ fontSize: '22px', fontWeight: 600, marginBottom: '6px' }}>
          Network Topology
        </h2>
        <p style={{ color: 'var(--muted)', fontSize: '13px', lineHeight: '1.6', maxWidth: '540px' }}>
          Configure the underlying Mininet SDN structure. Deploying a new topology restarts only Mininet; the Ryu controller stays running.
        </p>
      </div>

      {/* ── Topology Selector Component ── */}
      <div style={{ marginBottom: '8px' }}>
        <div style={{
          fontSize: '13px',
          fontWeight: 600,
          letterSpacing: '1.2px',
          textTransform: 'uppercase',
          color: 'var(--muted)',
          marginBottom: '14px',
        }}>
          Select topology
        </div>
        <TopologySelector
          topologyType={topologyType}
          setTopologyType={setTopologyType}
        />
      </div>

      {/* ── Warning Box ── */}
      <div style={{
        marginTop: '16px',
        background: 'rgba(210, 153, 34, 0.07)',
        border: '1px solid rgba(210, 153, 34, 0.25)',
        borderLeft: '3px solid var(--amber)',
        borderRadius: '0 8px 8px 0',
        padding: '12px 16px',
        display: 'flex',
        gap: '12px',
        alignItems: 'flex-start',
      }}>
        <svg
          width="14" height="14" viewBox="0 0 16 16"
          fill="var(--amber)"
          style={{ flexShrink: 0, marginTop: '1px' }}
        >
          <path d="M8.982 1.566a1.13 1.13 0 0 0-1.96 0L.165 13.233c-.457.778.091 1.767.98 1.767h13.713c.889 0 1.438-.99.98-1.767L8.982 1.566zM8 5c.535 0 .954.462.9.995l-.35 3.507a.552.552 0 0 1-1.1 0L7.1 5.995A.905.905 0 0 1 8 5zm.002 6a1 1 0 1 1 0 2 1 1 0 0 1 0-2z"/>
        </svg>
        <div style={{ fontSize: '12px', color: 'var(--muted)', lineHeight: '1.6' }}>
          <strong style={{ color: 'var(--amber)', fontWeight: 600 }}>Warning: </strong>
          The selected profile is saved on the backend before Mininet changes. Keep Ryu running while the page shows Changing, and wait for Ready before testing connectivity.
        </div>
      </div>
    </div>
  );
};

export default TopologySettingsPage;
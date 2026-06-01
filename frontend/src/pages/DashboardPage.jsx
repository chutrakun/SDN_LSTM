import React, { useState, useEffect } from 'react';
import Dashboard from '../components/Dashboard';

const DashboardPage = ({ topologyType }) => {
  const [state, setState] = useState({ traffic: [], blocked: [], log: [], ports: {}, ml: {} });
  const [lastUpdate, setLastUpdate] = useState('Connecting…');
  const [isConnected, setIsConnected] = useState(false);

  useEffect(() => {
    const poll = async () => {
      try {
        const res = await fetch('/api/state');
        if (!res.ok) throw new Error('Network error');
        const data = await res.json();
        setState(data);
        setLastUpdate(new Date().toLocaleTimeString());
        setIsConnected(true);
      } catch {
        setIsConnected(false);
        setLastUpdate('Connection lost');
      }
    };

    poll();
    const id = setInterval(poll, 1000);
    return () => clearInterval(id);
  }, []);

  const handleUnblockIP = async (ip) => {
    if (!window.confirm(`Unblock IP ${ip}?`)) return;
    try {
      const res = await fetch(`/api/unblock/ip/${encodeURIComponent(ip)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const d = await res.json();
      if (!d.ok) alert('Failed: ' + (d.error || 'unknown'));
    } catch (e) {
      alert('Error: ' + e.message);
    }
  };

  return (
    <div className="page-container">
      <div className="header">
        <div className={`status-dot${!isConnected ? ' offline' : ''}`}></div>
        <h1>SDN Intelligent Security Dashboard</h1>
        <span className="badge badge-blue">Ryu 4.34</span>
        <span className="badge badge-purple">LSTM</span>
        <span className="badge badge-green" style={{fontSize:'10px'}}>ACL Mode</span>
        <div className="header-right">{lastUpdate}</div>
      </div>

      <Dashboard
        state={state}
        topologyType={topologyType}
        unblockIP={handleUnblockIP}
      />
    </div>
  );
};

export default DashboardPage;

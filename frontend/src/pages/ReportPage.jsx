import React, { useState, useEffect, useCallback } from 'react';
import {
  Chart as ChartJS,
  CategoryScale, LinearScale, BarElement, PointElement,
  LineElement, ArcElement, Title, Tooltip, Legend, Filler,
} from 'chart.js';
import { Bar, Line, Doughnut } from 'react-chartjs-2';
import { FileDown, RefreshCw, Shield, AlertTriangle, Unlock, Activity, Server, Clock } from 'lucide-react';

ChartJS.register(
  CategoryScale, LinearScale, BarElement, PointElement,
  LineElement, ArcElement, Title, Tooltip, Legend, Filler
);

const API_BASE = 'http://localhost:5000';

// ─── Color Palette ───
const COLORS = {
  red:    '#f85149',
  amber:  '#d29922',
  green:  '#3fb950',
  blue:   '#58a6ff',
  purple: '#bc8cff',
  cyan:   '#39d353',
};

const PIE_PALETTE = [
  '#f85149','#58a6ff','#bc8cff','#d29922','#3fb950','#39d353','#e78a4e',
];

// ─── Helper: Chart default options ───
const chartDefaults = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: { labels: { color: '#7d8590', font: { size: 11 } } },
    tooltip: {
      backgroundColor: '#161b22',
      borderColor: '#30363d',
      borderWidth: 1,
      titleColor: '#e6edf3',
      bodyColor: '#7d8590',
    },
  },
  scales: {
    x: { ticks: { color: '#7d8590', font: { size: 10 } }, grid: { color: '#21262d' } },
    y: { ticks: { color: '#7d8590', font: { size: 10 } }, grid: { color: '#21262d' } },
  },
};

// ─── Stat Card ───
const StatCard = ({ icon: Icon, label, value, color, sub }) => (
  <div className="stat-card" style={{ position: 'relative', overflow: 'hidden' }}>
    <div style={{
      position: 'absolute', top: 12, right: 14,
      opacity: 0.12, fontSize: 40,
    }}>
      <Icon size={40} color={color} />
    </div>
    <div className="stat-label">{label}</div>
    <div className="stat-value" style={{ color }}>{value}</div>
    {sub && <div className="stat-sub">{sub}</div>}
  </div>
);

// ─── Period selector ───
const PERIODS = [
  { label: '24h', value: 1 },
  { label: '7 วัน', value: 7 },
  { label: '30 วัน', value: 30 },
];

// ─── Main Page ───
const ReportPage = () => {
  const [period, setPeriod]           = useState(7);
  const [loading, setLoading]         = useState(true);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [error, setError]             = useState(null);

  const [summary, setSummary]         = useState(null);
  const [attackTypes, setAttackTypes] = useState([]);
  const [topPorts, setTopPorts]       = useState([]);
  const [hourlyData, setHourlyData]   = useState([]);
  const [attackLog, setAttackLog]     = useState([]);
  const [topoEvents, setTopoEvents]  = useState([]);

  // ─── Date range for export ───
  const today = new Date().toISOString().slice(0, 10);
  const weekAgo = new Date(Date.now() - period * 86400000).toISOString().slice(0, 10);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [sum, types, ports, hourly, attacks, topo] = await Promise.all([
        fetch(`${API_BASE}/api/report/summary?period=${period}`).then(r => r.json()),
        fetch(`${API_BASE}/api/report/attack-types?period=${period}`).then(r => r.json()),
        fetch(`${API_BASE}/api/report/top-ports?period=${period}`).then(r => r.json()),
        fetch(`${API_BASE}/api/report/traffic/hourly?days=${period}`).then(r => r.json()),
        fetch(`${API_BASE}/api/report/attacks?from=${weekAgo}&to=${today}T23:59:59&limit=100`).then(r => r.json()),
        fetch(`${API_BASE}/api/report/topology-events?days=${period}`).then(r => r.json()),
      ]);

      // ตรวจสอบ error จาก API
      if (sum?.error) {
        setError(`API Error: ${sum.error}`);
      }

      setSummary(sum);
      setAttackTypes(Array.isArray(types) ? types : []);
      setTopPorts(Array.isArray(ports) ? ports : []);
      setHourlyData(Array.isArray(hourly) ? hourly : []);
      setAttackLog(Array.isArray(attacks) ? attacks : []);
      setTopoEvents(Array.isArray(topo) ? topo : []);
      setLastUpdated(new Date().toLocaleTimeString('th-TH'));
    } catch (e) {
      console.error('Report fetch error:', e);
      setError(`เชื่อมต่อ API ไม่ได้ — ตรวจสอบว่า Dashboard API กำลังรันอยู่ (port 5000)`);
    } finally {
      setLoading(false);
    }
  }, [period]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  // ─── Derived chart data ───
  const attacksPerDayChart = {
    labels: (summary?.attacks_per_day || []).map(r => r.day?.slice(5) || ''),
    datasets: [{
      label: 'Attacks',
      data: (summary?.attacks_per_day || []).map(r => r.count),
      backgroundColor: 'rgba(248,81,73,0.25)',
      borderColor: COLORS.red,
      borderWidth: 2,
      borderRadius: 4,
    }],
  };

  const typeChartData = (() => {
    const labels = attackTypes.map(t => t.type || 'Unknown');
    const data   = attackTypes.map(t => t.count);
    return {
      labels,
      datasets: [{
        data,
        backgroundColor: PIE_PALETTE.slice(0, labels.length),
        borderColor: '#0d1117',
        borderWidth: 2,
      }],
    };
  })();

  const topPortsChart = {
    labels: topPorts.map(p => `Port ${p.port}`),
    datasets: [{
      label: 'Attack count',
      data:  topPorts.map(p => p.count),
      backgroundColor: topPorts.map((_, i) => `${COLORS.purple}${['ff','cc','99','66','44'][i] || 'ff'}`),
      borderRadius: 6,
    }],
  };

  // hourly traffic — group by port
  const hourlyChart = (() => {
    const ports = [...new Set(hourlyData.map(r => r.port))].sort();
    const labels = [...new Set(hourlyData.map(r => r.hour?.slice(5, 16) || ''))];
    const portColors = [COLORS.blue, COLORS.green, COLORS.amber, COLORS.purple];
    const datasets = ports.map((port, i) => {
      const portRows = hourlyData.filter(r => r.port === port);
      const dataMap  = Object.fromEntries(portRows.map(r => [r.hour?.slice(5,16), r.avg_pps]));
      return {
        label: `Port ${port}`,
        data:  labels.map(l => dataMap[l] ?? null),
        borderColor: portColors[i % portColors.length],
        backgroundColor: `${portColors[i % portColors.length]}22`,
        fill: false,
        tension: 0.3,
        pointRadius: 2,
      };
    });
    return { labels, datasets };
  })();

  const handleExport = () => {
    const url = `${API_BASE}/api/report/export?from=${weekAgo}&to=${today}T23:59:59`;
    window.open(url, '_blank');
  };

  const confColor = (conf) => {
    if (conf >= 90) return COLORS.red;
    if (conf >= 70) return COLORS.amber;
    return COLORS.blue;
  };

  return (
    <div className="page-container" id="report-page">
      {/* ── Header Bar ── */}
      <div className="header">
        <span style={{ fontSize: 16, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 8 }}>
          <Shield size={18} color={COLORS.blue} /> Security Report
        </span>

        {/* Period Tabs */}
        <div style={{ display: 'flex', gap: 4, marginLeft: 24 }}>
          {PERIODS.map(p => (
            <button
              key={p.value}
              id={`period-${p.value}d`}
              onClick={() => setPeriod(p.value)}
              style={{
                padding: '4px 14px', borderRadius: 20, border: 'none', cursor: 'pointer',
                fontSize: 12, fontWeight: 600,
                background: period === p.value ? COLORS.blue : 'var(--bg3)',
                color:      period === p.value ? '#0d1117' : 'var(--muted)',
                transition: 'all 0.2s',
              }}
            >
              {p.label}
            </button>
          ))}
        </div>

        <div className="header-right" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {lastUpdated && (
            <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11 }}>
              <Clock size={11} /> อัปเดต {lastUpdated}
            </span>
          )}
          <button
            id="btn-refresh-report"
            onClick={fetchAll}
            disabled={loading}
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '5px 12px', borderRadius: 6, border: '1px solid var(--border)',
              background: 'transparent', color: 'var(--muted)', cursor: 'pointer', fontSize: 12,
            }}
          >
            <RefreshCw size={12} style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
            Refresh
          </button>
          <button
            id="btn-export-csv"
            onClick={handleExport}
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '5px 12px', borderRadius: 6, border: 'none',
              background: COLORS.green, color: '#0d1117', cursor: 'pointer',
              fontSize: 12, fontWeight: 600,
            }}
          >
            <FileDown size={12} /> Export CSV
          </button>
        </div>
      </div>

      {loading && (
        <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--muted)' }}>
          <div style={{ fontSize: 32, marginBottom: 12, animation: 'spin 1.2s linear infinite', display: 'inline-block' }}>⟳</div>
          <div>กำลังโหลดข้อมูล...</div>
        </div>
      )}

      {error && (
        <div style={{
          margin: '16px 0', padding: '12px 16px', borderRadius: 8,
          background: 'rgba(248,81,73,0.1)', border: '1px solid rgba(248,81,73,0.3)',
          color: '#f85149', fontSize: 13, display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <AlertTriangle size={16} />
          {error}
        </div>
      )}

      {!loading && (
        <>
          {/* ── Stat Cards ── */}
          <div className="stats-row" style={{ marginTop: 20 }}>
            <StatCard icon={AlertTriangle} label="Total Attacks" color={COLORS.red}
              value={summary?.total_attacks ?? '—'}
              sub={`ใน ${period} วันที่ผ่านมา`} />
            <StatCard icon={Shield} label="Total Blocks" color={COLORS.amber}
              value={summary?.total_blocks ?? '—'}
              sub="พอร์ตที่ถูกบล็อก" />
            <StatCard icon={Unlock} label="Total Unblocks" color={COLORS.green}
              value={summary?.total_unblocks ?? '—'}
              sub="ปลดบล็อกแล้ว" />
            <StatCard icon={Activity} label="Peak pkt/s" color={COLORS.blue}
              value={summary?.peak_pps != null ? summary.peak_pps.toFixed(0) : '—'}
              sub="สูงสุดในช่วงเวลา" />
          </div>

          {/* ── Row 1: Attacks per day + Attack types ── */}
          <div className="grid" style={{ marginTop: 0 }}>
            <div className="card col-2">
              <div className="card-title">
                <span className="dot" style={{ background: COLORS.red }} />
                Attacks per Day
              </div>
              <div style={{ height: 200 }}>
                {attacksPerDayChart.labels.length > 0 ? (
                  <Bar data={attacksPerDayChart} options={{
                    ...chartDefaults,
                    plugins: { ...chartDefaults.plugins, legend: { display: false } },
                  }} />
                ) : (
                  <div className="empty" style={{ paddingTop: 80 }}>ยังไม่มีข้อมูลในช่วงนี้</div>
                )}
              </div>
            </div>

            <div className="card">
              <div className="card-title">
                <span className="dot" style={{ background: COLORS.purple }} />
                Attack Types
              </div>
              <div style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                {attackTypes.length > 0 ? (
                  <Doughnut data={typeChartData} options={{
                    ...chartDefaults,
                    scales: undefined,
                    cutout: '60%',
                    plugins: {
                      ...chartDefaults.plugins,
                      legend: {
                        position: 'right',
                        labels: { color: '#7d8590', font: { size: 10 }, boxWidth: 12, padding: 8 },
                      },
                    },
                  }} />
                ) : (
                  <div className="empty">ยังไม่มีข้อมูล</div>
                )}
              </div>
            </div>

            {/* ── Top Attacked Ports ── */}
            <div className="card">
              <div className="card-title">
                <span className="dot" style={{ background: COLORS.amber }} />
                Top Attacked Ports
              </div>
              <div style={{ height: 200 }}>
                {topPorts.length > 0 ? (
                  <Bar data={topPortsChart} options={{
                    ...chartDefaults,
                    indexAxis: 'y',
                    plugins: { ...chartDefaults.plugins, legend: { display: false } },
                  }} />
                ) : (
                  <div className="empty" style={{ paddingTop: 80 }}>ยังไม่มีข้อมูล</div>
                )}
              </div>
            </div>

            {/* ── Topology Events ── */}
            <div className="card col-2">
              <div className="card-title">
                <span className="dot" style={{ background: COLORS.green }} />
                Topology Change History
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 200, overflowY: 'auto' }}>
                {topoEvents.length === 0 ? (
                  <div className="empty">ไม่มีการเปลี่ยน Topology ในช่วงนี้</div>
                ) : topoEvents.map((e, i) => (
                  <div key={i} style={{
                    display: 'flex', alignItems: 'center', gap: 10,
                    padding: '7px 10px', borderRadius: 6, background: 'var(--bg3)',
                    fontSize: 12,
                  }}>
                    <Server size={12} color={COLORS.green} style={{ flexShrink: 0 }} />
                    <span style={{ color: 'var(--muted)', minWidth: 140, fontFamily: 'monospace', fontSize: 11 }}>
                      {e.timestamp?.slice(0,16).replace('T',' ')}
                    </span>
                    <span style={{ color: COLORS.blue, fontWeight: 600, minWidth: 60 }}>{e.topology}</span>
                    <span style={{ color: 'var(--muted)', flex: 1, fontSize: 11 }}>{e.message}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* ── Hourly Traffic Chart ── */}
            <div className="card col-3">
              <div className="card-title">
                <span className="dot" style={{ background: COLORS.blue }} />
                Hourly Traffic (avg pkt/s per port)
              </div>
              <div style={{ height: 220 }}>
                {hourlyChart.labels.length > 0 ? (
                  <Line data={hourlyChart} options={{
                    ...chartDefaults,
                    interaction: { mode: 'index', intersect: false },
                    plugins: { ...chartDefaults.plugins, legend: { display: true, labels: { color: '#7d8590', font: { size: 10 } } } },
                  }} />
                ) : (
                  <div className="empty" style={{ paddingTop: 90 }}>
                    ยังไม่มีข้อมูล hourly — ระบบจะเริ่ม aggregate หลังจากผ่านไป 1 ชั่วโมง
                  </div>
                )}
              </div>
            </div>

            {/* ── Attack Log Table ── */}
            <div className="card col-3">
              <div className="card-title" style={{ justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span className="dot" style={{ background: COLORS.red }} />
                  Attack Log — {period} วันล่าสุด
                </div>
                <span style={{ color: 'var(--muted)', fontSize: 11 }}>
                  {attackLog.length} รายการ
                </span>
              </div>
              <div style={{ overflowX: 'auto' }}>
                <table id="report-attack-table" style={{
                  width: '100%', borderCollapse: 'collapse', fontSize: 12,
                }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--border)' }}>
                      {['Timestamp', 'Port', 'Attack Type', 'pkt/s', 'kB/s', 'Conf %', 'Action'].map(h => (
                        <th key={h} style={{
                          textAlign: 'left', padding: '6px 10px', color: 'var(--muted)',
                          fontWeight: 600, fontSize: 10, textTransform: 'uppercase', letterSpacing: '.5px',
                          whiteSpace: 'nowrap',
                        }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {attackLog.length === 0 ? (
                      <tr><td colSpan={7} style={{ textAlign: 'center', padding: 30, color: 'var(--muted)' }}>ยังไม่มีข้อมูล</td></tr>
                    ) : attackLog.map((row, i) => (
                      <tr key={i} style={{
                        borderBottom: '1px solid var(--bg3)',
                        background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.015)',
                        transition: 'background 0.15s',
                      }}>
                        <td style={{ padding: '6px 10px', color: 'var(--muted)', fontFamily: 'monospace', fontSize: 11, whiteSpace: 'nowrap' }}>
                          {row.timestamp?.slice(0,19).replace('T',' ')}
                        </td>
                        <td style={{ padding: '6px 10px', fontWeight: 600 }}>
                          <span style={{
                            display: 'inline-block', padding: '1px 8px', borderRadius: 10,
                            background: 'var(--bg3)', color: COLORS.blue, fontSize: 11,
                          }}>Port {row.port}</span>
                        </td>
                        <td style={{ padding: '6px 10px' }}>
                          <span style={{
                            display: 'inline-block', padding: '1px 8px', borderRadius: 10,
                            background: 'rgba(248,81,73,0.12)', color: COLORS.red, fontSize: 11, fontWeight: 600,
                          }}>
                            {row.attack_type || row.note || 'Unknown'}
                          </span>
                        </td>
                        <td style={{ padding: '6px 10px', fontFamily: 'monospace' }}>{row.pps?.toFixed(1)}</td>
                        <td style={{ padding: '6px 10px', fontFamily: 'monospace' }}>{row.bps?.toFixed(1)}</td>
                        <td style={{ padding: '6px 10px', fontFamily: 'monospace', color: confColor(row.conf), fontWeight: 700 }}>
                          {row.conf?.toFixed(1)}%
                        </td>
                        <td style={{ padding: '6px 10px' }}>
                          <span className="badge badge-red">{row.action || 'BLOCK'}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

          </div>
        </>
      )}

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        #report-attack-table tbody tr:hover { background: rgba(88,166,255,0.05) !important; }
      `}</style>
    </div>
  );
};

export default ReportPage;

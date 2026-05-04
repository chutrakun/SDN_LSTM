import React from 'react';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js';
import { Line } from 'react-chartjs-2';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend, Filler);

const PORT_COLORS = {
  1: { line: '#4da6ff', bg: 'rgba(77,166,255,.06)' },
  2: { line: '#00e5a0', bg: 'rgba(0,229,160,.06)' },
  3: { line: '#a57eff', bg: 'rgba(165,126,255,.06)' },
  4: { line: '#ff4d6a', bg: 'rgba(255,77,106,.06)' },
};

const TrafficChart = ({ trafficData = [] }) => {
  const labels = [];
  const portData = { 1: [], 2: [], 3: [], 4: [] };

  trafficData.forEach((t) => {
    if (!labels.includes(t.time)) labels.push(t.time);
  });

  labels.forEach((timeLabel) => {
    const pts = trafficData.filter((t) => t.time === timeLabel);
    [1, 2, 3, 4].forEach((port) => {
      const pt = pts.find((p) => p.port == port);
      portData[port].push(pt ? pt.pps : 0);
    });
  });

  const data = {
    labels,
    datasets: [1, 2, 3, 4].map((port) => ({
      label: `Port ${port}`,
      data: portData[port],
      borderColor: PORT_COLORS[port].line,
      backgroundColor: PORT_COLORS[port].bg,
      tension: 0.4,
      fill: true,
      pointRadius: 0,
      borderWidth: 1.5,
    })),
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: {
        labels: {
          color: '#4d6278',
          font: { size: 11, family: "'Space Mono', monospace" },
          boxWidth: 10,
          boxHeight: 2,
          padding: 16,
        },
      },
      tooltip: {
        backgroundColor: 'rgba(13,21,32,.95)',
        borderColor: '#1e2d42',
        borderWidth: 1,
        titleColor: '#a8b8cc',
        bodyColor: '#e2eaf4',
        titleFont: { family: "'Space Mono', monospace", size: 11 },
        bodyFont: { family: "'Space Mono', monospace", size: 11 },
        padding: 10,
      },
    },
    scales: {
      x: {
        ticks: { color: '#4d6278', maxTicksLimit: 8, font: { size: 10, family: "'Space Mono', monospace" } },
        grid: { color: 'rgba(30,45,66,.6)' },
        border: { color: 'rgba(30,45,66,.8)' },
      },
      y: {
        ticks: { color: '#4d6278', font: { size: 10, family: "'Space Mono', monospace" } },
        grid: { color: 'rgba(30,45,66,.6)' },
        border: { color: 'rgba(30,45,66,.8)' },
        min: 0,
      },
    },
  };

  return <Line data={data} options={options} />;
};

export default TrafficChart;

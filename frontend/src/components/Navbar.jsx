import React from 'react';
import { NavLink } from 'react-router-dom';

const Navbar = ({ theme, toggleTheme }) => {
  return (
    <nav className="navbar">
      <div className="navbar-brand">
        <span className="brand-dot"></span>
        SDN·SEC
      </div>

      <div style={{ display: 'flex', gap: '2px', height: '100%', flex: 1 }}>
        <NavLink
          to="/"
          end
          className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}
        >
          Dashboard
        </NavLink>
        <NavLink
          to="/settings"
          className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}
        >
          Topology
        </NavLink>
        <NavLink
          to="/report"
          className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}
        >
          Report
        </NavLink>
        <NavLink
          to="/models"
          className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}
        >
          ML Models
        </NavLink>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        <button
          onClick={() => {
            localStorage.removeItem("auth_token");
            window.location.reload();
          }}
          className="theme-toggle"
          title="Logout"
        >
          🚪
        </button>
        <button
          onClick={toggleTheme}
          className="theme-toggle"
          title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
        >
          {theme === 'dark' ? '☀️' : '🌙'}
        </button>
      </div>
    </nav>
  );
};

export default Navbar;

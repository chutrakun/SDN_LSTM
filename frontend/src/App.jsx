// import React, { useState, useEffect } from 'react';
// import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
// import Navbar from './components/Navbar';
// import DashboardPage from './pages/DashboardPage';
// import TopologySettingsPage from './pages/TopologySettingsPage';
// import ReportPage from './pages/ReportPage';
// import ModelUploadPage from './pages/ModelUploadPage';
// import LoginPage from './pages/LoginPage';

// function App() {
//   const [topologyType, setTopologyType] = useState('default');

//   const [theme, setTheme] = useState(() => localStorage.getItem('theme') || 'dark');

//   useEffect(() => {
//     if (theme === 'light') {
//       document.body.classList.add('light-mode');
//     } else {
//       document.body.classList.remove('light-mode');
//     }
//     localStorage.setItem('theme', theme);
//   }, [theme]);

//   const toggleTheme = () => setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'));

//   return (
//     <Router>
//       <div>
//         <Navbar theme={theme} toggleTheme={toggleTheme} />
//         <Routes>
//           <Route path="/"        element={<DashboardPage topologyType={topologyType} />} />
//           <Route path="/settings" element={<TopologySettingsPage topologyType={topologyType} setTopologyType={setTopologyType} />} />
//           <Route path="/report"  element={<ReportPage />} />
//           <Route path="/models"  element={<ModelUploadPage />} />
//         </Routes>
//       </div>
//     </Router>
//   );
// }

// export default App;


import React, { useState, useEffect } from "react";
import { BrowserRouter as Router, Routes, Route, Navigate } from "react-router-dom";
import Navbar from "./components/Navbar";
import DashboardPage from "./pages/DashboardPage";
import TopologySettingsPage from "./pages/TopologySettingsPage";
import ReportPage from "./pages/ReportPage";
import ModelUploadPage from "./pages/ModelUploadPage";
import LoginPage from "./pages/LoginPage";

function App() {
  const [topologyType, setTopologyType] = useState("default");
  const [isLoggedIn, setIsLoggedIn] = useState(() => !!localStorage.getItem("auth_token"));
  const [theme, setTheme] = useState(
    () => localStorage.getItem("theme") || "dark"
  );

  useEffect(() => {
    if (theme === "light") {
      document.body.classList.add("light-mode");
    } else {
      document.body.classList.remove("light-mode");
    }
    localStorage.setItem("theme", theme);
  }, [theme]);

  const toggleTheme = () =>
    setTheme((prev) => (prev === "dark" ? "light" : "dark"));

  const handleLoginSuccess = (data) => {
    if (data?.token) localStorage.setItem("auth_token", data.token);
    setIsLoggedIn(true);
  };

  return (
    <Router>
      {!isLoggedIn ? (
        <Routes>
          <Route path="/login" element={<LoginPage onLoginSuccess={handleLoginSuccess} theme={theme} toggleTheme={toggleTheme} />} />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      ) : (
        <div>
          <Navbar theme={theme} toggleTheme={toggleTheme} />
          <Routes>
            <Route path="/" element={<DashboardPage topologyType={topologyType} />} />
            <Route
              path="/settings"
              element={
                <TopologySettingsPage
                  topologyType={topologyType}
                  setTopologyType={setTopologyType}
                />
              }
            />
            <Route path="/report" element={<ReportPage />} />
            <Route path="/models" element={<ModelUploadPage />} />
            <Route path="/login" element={<Navigate to="/" replace />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      )}
    </Router>
  );
}

export default App;
import React, { useState } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import Login from './Login';
import AgenticMemberPortalDemo from './AgenticMemberPortalDemo';
import LandingPage from './LandingPage';
import ProviderDashboard from './ProviderDashboard';
import PayerDashboard from './PayerDashboard';

function App() {
  const [role, setRole] = useState(() => sessionStorage.getItem('role') || null);

  const handleLogin = (userRole) => {
    sessionStorage.setItem('role', userRole);
    setRole(userRole);
  };

  const handleLogout = () => {
    sessionStorage.removeItem('role');
    sessionStorage.removeItem('member');
    sessionStorage.removeItem('sessionId');
    sessionStorage.removeItem('lp_travel_city');
    sessionStorage.removeItem('lp_travel_state');
    sessionStorage.removeItem('lp_location_changed');
    setRole(null);
  };

  return (
    <Router>
      <Routes>
        {/* Public */}
        <Route path="/login" element={<Login onLogin={handleLogin} />} />

        {/* Member routes */}
        <Route
          path="/"
          element={
            role === 'member'
              ? <LandingPage onLogout={handleLogout} />
              : <Navigate to="/login" replace />
          }
        />
        <Route
          path="/chat"
          element={
            role === 'member'
              ? <AgenticMemberPortalDemo onLogout={handleLogout} />
              : <Navigate to="/login" replace />
          }
        />

        {/* Provider route */}
        <Route
          path="/provider"
          element={
            role === 'provider'
              ? <ProviderDashboard onLogout={handleLogout} />
              : <Navigate to="/login" replace />
          }
        />

        {/* Payer route */}
        <Route
          path="/payer"
          element={
            role === 'payer'
              ? <PayerDashboard onLogout={handleLogout} />
              : <Navigate to="/login" replace />
          }
        />

        {/* Fallback */}
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </Router>
  );
}

export default App;

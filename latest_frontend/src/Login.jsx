import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import './Login.css';
import logoCog from './assets/logocog.png';

const ROLES = [
  { id: 'member',   label: 'Member',   icon: '👤', placeholder: 'e.g. MEM-10001', hint: 'Password: same as ID digits' },
  { id: 'provider', label: 'Provider', icon: '🏥', placeholder: 'PROV-001',        hint: 'Password: provider123' },
  { id: 'payer',    label: 'Payer',    icon: '🏦', placeholder: 'PAYER-001',       hint: 'Password: payer123' },
];

export default function Login({ onLogin }) {
  const [role, setRole]       = useState('member');
  const [userId, setUserId]   = useState('');
  const [password, setPassword] = useState('');
  const [error, setError]     = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const activeRole = ROLES.find(r => r.id === role);

  const handleRoleChange = (r) => {
    setRole(r);
    setUserId('');
    setPassword('');
    setError('');
  };

  const handleLogin = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await fetch('/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ member_id: userId, password, role }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail || 'Invalid credentials');
        return;
      }

      if (role === 'member') {
        sessionStorage.setItem('member', JSON.stringify(data.member));
        sessionStorage.setItem('plan_change_detected', data.plan_change_detected ? '1' : '0');
        onLogin('member');
        navigate('/');
      } else if (role === 'provider') {
        onLogin('provider');
        navigate('/provider');
      } else if (role === 'payer') {
        onLogin('payer');
        navigate('/payer');
      }
    } catch {
      setError('Could not reach the server. Make sure the backend is running.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-logo">
          <img src={logoCog} alt="Medilife" className="login-logo-img" />
        </div>

        {/* Role selector */}
        <div className="login-role-tabs">
          {ROLES.map(r => (
            <button
              key={r.id}
              type="button"
              className={`login-role-tab${role === r.id ? ' active' : ''}`}
              onClick={() => handleRoleChange(r.id)}
            >
              <span className="login-role-icon">{r.icon}</span>
              {r.label}
            </button>
          ))}
        </div>

        <div className="login-subtitle">
          Sign in as <strong>{activeRole.label}</strong>
        </div>

        {error && <div className="login-error">{error}</div>}

        <form onSubmit={handleLogin}>
          <label className="login-label">
            {role === 'member' ? 'Member ID' : role === 'provider' ? 'Provider ID' : 'Payer ID'}
          </label>
          <input
            className="login-input"
            type="text"
            placeholder={activeRole.placeholder}
            value={userId}
            onChange={e => setUserId(e.target.value)}
            required
          />

          <label className="login-label">Password</label>
          <input
            className="login-input"
            type="password"
            placeholder="Enter your password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            required
          />

          <div className="login-hint">{activeRole.hint}</div>

          <button className="login-btn" type="submit" disabled={loading}>
            {loading ? 'Signing in…' : `Sign In as ${activeRole.label}`}
          </button>
        </form>
      </div>
    </div>
  );
}

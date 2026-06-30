import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import './LandingPage.css';

function ApptCard({ a, type }) {
  return (
    <div className={`lp-appt-item lp-appt-item-${type}`}>
      <div className="lp-appt-item-top">
        <span className={`lp-appt-dot lp-appt-dot-${type}`} />
        <div className="lp-appt-doctor">{a.provider_name || a.doctor_name || 'Unknown Provider'}</div>
        <span className={`lp-appt-type ${(a.consultation_type||'').toLowerCase()==='telehealth'?'lp-appt-type-tele':'lp-appt-type-inperson'}`}>
          {a.consultation_type || 'In-Person'}
        </span>
      </div>
      {a.specialty && <div className="lp-appt-spec">{a.specialty}</div>}
      <div className="lp-appt-meta">
        <span>&#128197; {a.date}</span>
        {a.time_start && <span>&#128336; {a.time_start}</span>}
      </div>
      {a.reason && <div className="lp-appt-reason">"{a.reason}"</div>}
    </div>
  );
}

function MemberPanel({ member, pcp, appointments, parseApptDateTime, goToChat }) {
  const [tab, setTab] = useState('upcoming');
  const now = Date.now();
  const visibleAppointments = appointments.filter(a => (a.status || '').toLowerCase() !== 'cancelled');
  const upcoming = visibleAppointments.filter(a => { const dt = parseApptDateTime(a); return dt && dt.getTime() >= now; });
  const past = visibleAppointments.filter(a => { const dt = parseApptDateTime(a); return !dt || dt.getTime() < now; });
  const list = tab === 'upcoming' ? upcoming : past;
  return (
    <div className="lp-appt-panel">

      {/* Dark header */}
      <div className="lp-appt-panel-header">
        <div className="lp-appt-panel-avatar">
          {(member.first_name?.[0]||'').toUpperCase()}{(member.last_name?.[0]||'').toUpperCase()}
        </div>
        <div>
          <div className="lp-appt-panel-name">{member.first_name} {member.last_name}</div>
          <div className="lp-appt-panel-plan">{member.insurance_plan}</div>
        </div>
      </div>

      {/* PCP */}
      {pcp && (
        <div className="lp-appt-pcp-block">
          <div className="lp-appt-section-label">&#129338; Primary Care Physician</div>
          <div className="lp-appt-pcp-row">
            <div className="lp-appt-pcp-icon">&#128084;</div>
            <div>
              <div className="lp-appt-pcp-name">{pcp.name}</div>
              {pcp.specialty && <div className="lp-appt-pcp-spec">{pcp.specialty}</div>}
              {pcp.phone    && <div className="lp-appt-pcp-phone">&#128222; {pcp.phone}</div>}
            </div>
          </div>
        </div>
      )}

      {/* Dependents */}
      {member.dependents?.length > 0 && (
        <div className="lp-appt-dep-block">
          <div className="lp-appt-section-label">&#128106; Dependents</div>
          <div className="lp-appt-dep-chips">
            {member.dependents.map((d, i) => (
              <div key={i} className="lp-appt-dep-chip">
                <span className="lp-appt-dep-initial">{d.name?.[0]||'?'}</span>
                <div>
                  <div className="lp-appt-dep-name">{d.name}</div>
                  <div className="lp-appt-dep-rel">{d.relationship}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Appointment History */}
      <div className="lp-appt-history-wrap">
        <div className="lp-appt-history-header">
          <span className="lp-appt-history-title">&#128197; Appointment History</span>
        </div>
        <div className="lp-appt-tabs">
          <button className={`lp-appt-tab${tab==='upcoming'?' active':''}`} onClick={()=>setTab('upcoming')}>
            Upcoming {upcoming.length > 0 && <span className="lp-appt-badge">{upcoming.length}</span>}
          </button>
          <button className={`lp-appt-tab${tab==='past'?' active':''}`} onClick={()=>setTab('past')}>
            Past {past.length > 0 && <span className="lp-appt-badge lp-appt-badge-past">{past.length}</span>}
          </button>
        </div>
        <div className="lp-appt-list">
          {list.length === 0 ? (
            <div className="lp-appt-empty">
              <div className="lp-appt-empty-icon">{tab==='upcoming'?'🗓':'📋'}</div>
              <div className="lp-appt-empty-text">No {tab} appointments</div>
              <button className="lp-appt-empty-cta" onClick={goToChat}>Book via AI assistant &rarr;</button>
            </div>
          ) : (
            list.map((a, i) => <ApptCard key={i} a={a} type={tab} />)
          )}
        </div>
      </div>

      {/* Bottom membership strip */}
      <div className="lp-appt-footer">
        <span className="lp-appt-footer-label">Member ID</span>
        <span className="lp-appt-footer-id">{member.member_id}</span>
      </div>

    </div>
  );
}

const LOCATION_OPTIONS = [
  { label: 'Los Angeles, CA', value: 'Los Angeles|CA' },
  { label: 'New York, NY',    value: 'New York|NY' },
  { label: 'Miami, FL',       value: 'Miami|FL' },
  { label: 'Chicago, IL',     value: 'Chicago|IL' },
  { label: 'Houston, TX',     value: 'Houston|TX' },
  { label: 'Seattle, WA',     value: 'Seattle|WA' },
  { label: 'Dallas, TX',      value: 'Dallas|TX' },
  { label: 'Austin, TX',      value: 'Austin|TX' },
];

export default function LandingPage({ onLogout }) {
  const navigate = useNavigate();
  const member = JSON.parse(sessionStorage.getItem('member') || 'null');

  const homeCity  = member?.city  || '';
  const homeState = member?.state || '';
  const homeValue = `${homeCity}|${homeState}`;

  const allLocOptions = LOCATION_OPTIONS.some(o => o.value === homeValue)
    ? LOCATION_OPTIONS
    : [{ label: `${homeCity}, ${homeState}`, value: homeValue }, ...LOCATION_OPTIONS];

  const [locValue, setLocValue]         = useState(homeValue);
  const [notification, setNotification] = useState(null);
  const [bellOpen, setBellOpen]         = useState(false);
  const [appointments, setAppointments] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [readCount, setReadCount]         = useState(0);
  const bellRef = useRef(null);

  useEffect(() => {
    const handler = (e) => { if (bellRef.current && !bellRef.current.contains(e.target)) setBellOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const parseApptDateTime = (appt) => {
    if (!appt?.date) return null;
    const rawDate = appt.date.replace(/^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s*/i, '');
    const dateOnly = new Date(rawDate);
    if (isNaN(dateOnly)) return null;
    if (appt.time) {
      const dateWithTime = new Date(`${dateOnly.toDateString()} ${appt.time}`);
      if (!isNaN(dateWithTime)) return dateWithTime;
    }
    return dateOnly;
  };

  useEffect(() => {
    const fetchAppointments = async () => {
      if (!member?.member_id) return;
      try {
        // Prefer the dashboard endpoint which returns the authoritative bookings
        const resDash = await fetch(`/dashboard/member/${member.member_id}`);
        if (resDash.ok) {
          const dash = await resDash.json();
          setAppointments(dash.bookings || dash.appointments || []);
          return;
        }
        // Fallback to legacy appointments endpoint
        const res  = await fetch(`/appointments/${member.member_id}`);
        const data = await res.json();
        setAppointments(data.appointments || []);
      } catch { /* ignore */ }
    };
    fetchAppointments();
  }, []);

  // Fetch member state to build proactive notifications (prior auth, plan change)
  useEffect(() => {
    if (!member?.member_id) return;
    fetch(`/dashboard/member/${member.member_id}`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!data) return;
        const items = [];
        if (data?.prior_auth?.status === 'approved') {
          items.push({
            id: 'prior_auth',
            icon: '✅',
            title: 'Prior Auth Approved',
            text: `Cigna approved your prior authorization${data.prior_auth.auth_reference_number ? ` (Ref# ${data.prior_auth.auth_reference_number})` : ''}. You can now book your scan.`,
            trigger: '__session_start__',
          });
        }
        if (data?.plan_change?.payer_decision === 'approved' && !data.plan_change._payer_proactive_shown) {
          items.push({
            id: 'plan_change',
            icon: '🔄',
            title: 'Plan Change Approved',
            text: `Your request to switch to ${data.plan_change.new_plan || 'your new plan'} has been approved by Cigna.`,
            trigger: '__plan_change_greeting__',
          });
        }
        setNotifications(items);
      })
      .catch(() => {});
  }, [member?.member_id]);



  const hasUpcomingInPerson = async () => {
    if (!member?.member_id) return { hasAppt: false, doctorName: '' };
    try {
      const res  = await fetch(`/appointments/${member.member_id}`);
      const data = await res.json();
      const appts = data.appointments || [];
      const now = Date.now();
      const found = appts.find(a => {
        if ((a.consultation_type || '').toLowerCase() !== 'in-person') return false;
        const dt = parseApptDateTime(a);
        return dt && dt.getTime() >= now;
      });
      return { hasAppt: !!found, doctorName: found?.provider_name || found?.doctor_name || '' };
    } catch { return { hasAppt: false, doctorName: '' }; }
  };

  const onLocationChange = async (val) => {
    setLocValue(val);
    if (val === homeValue) {
      setNotification(null);
      setNotifications(prev => prev.filter(n => n.id !== 'location'));
      return;
    }
    const [city, state] = val.split('|');
    const label = LOCATION_OPTIONS.find(o => o.value === val)?.label || city;
    const { hasAppt, doctorName } = await hasUpcomingInPerson();
    const text = hasAppt
      ? `You are currently in ${label}. You have an upcoming in-person appointment${doctorName ? ` with ${doctorName}` : ''} in ${homeCity}, ${homeState}.`
      : `\uD83D\uDCCD Location changed to ${label}.`;
    const locNotif = {
      id: 'location',
      icon: '📍',
      title: 'Location Changed',
      text,
      travelCity: city,
      travelState: state,
      hasAppt,
      trigger: '__location_change__',
    };
    setNotification(locNotif);
    setNotifications(prev => [locNotif, ...prev.filter(n => n.id !== 'location')]);
  };

  const goToChat = (notif) => {
    const n = notif || notification;
    if (n?.travelCity) {
      sessionStorage.setItem('lp_travel_city',  n.travelCity);
      sessionStorage.setItem('lp_travel_state', n.travelState);
      sessionStorage.setItem('lp_location_changed', '1');
    }
    if (n?.trigger === '__plan_change_greeting__') {
      sessionStorage.setItem('plan_change_detected', '1');
    }
    navigate('/chat');
  };

  const goToChatWithAppointments = () => {
    if (notification?.travelCity) {
      sessionStorage.setItem('lp_travel_city',  notification.travelCity);
      sessionStorage.setItem('lp_travel_state', notification.travelState);
      sessionStorage.setItem('lp_location_changed', '1');
    }
    navigate('/chat?open=appointments&tab=appointments');
  };

  const unreadCount = notifications.length - readCount;
  const hasNotifications = notifications.length > 0;

  const isTravel = locValue !== homeValue;

  const handleLogout = async () => {
    try { await fetch('/logout', { method: 'POST' }); } catch (_) {}
    sessionStorage.removeItem('member');
    sessionStorage.removeItem('sessionId');
    sessionStorage.removeItem('lp_travel_city');
    sessionStorage.removeItem('lp_travel_state');
    sessionStorage.removeItem('lp_location_changed');
    if (onLogout) onLogout();
    navigate('/login');
  };

  const mh  = member?.medical_history || {};
  const pcp = member?.assigned_pcp;

  return (
    <div className="lp-root">

      {/* Header */}
      <header className="app-header">
        <div className="header-left">
          <div className="logo">
            <img src="/src/assets/cognizant-logo.png" alt="Logo" className="logo-img" />
          </div>
        </div>
        <div className="header-center">
          <h1>Agentic Member Portal</h1>
        </div>
        <div className="header-right">
          <div className="lp-loc-wrap">
            <span className="lp-loc-icon">&#128205;</span>
            <select
              className={`lp-loc-select${isTravel ? ' lp-loc-travel' : ''}`}
              value={locValue}
              onChange={e => onLocationChange(e.target.value)}
            >
              {allLocOptions.map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
            {isTravel && <span className="lp-loc-badge">&#9992;</span>}
          </div>

          <div className="lp-bell-wrap" ref={bellRef}>
            <button
              className={`lp-bell-btn${hasNotifications && unreadCount > 0 ? ' lp-bell-has-notif' : ''}`}
              onClick={() => { setBellOpen(o => !o); setReadCount(notifications.length); }}
            >
              <span className="lp-bell-icon">🔔</span>
              {unreadCount > 0 && (
                <span className="lp-bell-count">{unreadCount}</span>
              )}
            </button>
            {bellOpen && notifications.length > 0 && (
              <div className="lp-bell-popover">
                <div className="lp-bell-popover-header">Notifications</div>
                {notifications.map(n => (
                  <div key={n.id} className="lp-bell-notif-item">
                    <span className="lp-bell-notif-icon">{n.icon}</span>
                    <div className="lp-bell-notif-body">
                      <div className="lp-bell-notif-title">{n.title}</div>
                      <div className="lp-bell-notif-text">{n.text}</div>
                    </div>
                    <button className="lp-bell-viewmore" onClick={() => goToChat(n)}>View in Chat →</button>
                  </div>
                ))}
              </div>
            )}
            {bellOpen && notifications.length === 0 && (
              <div className="lp-bell-popover">
                <div className="lp-bell-empty">No new notifications</div>
              </div>
            )}
          </div>

          {member && (
            <div className="member-info">
              <span className="member-name">{member.first_name} {member.last_name}</span>
            </div>
          )}
          <button className="logout-btn" onClick={handleLogout}>Logout</button>
        </div>
      </header>

      {/* Nav */}
      <nav className="lp-nav">
        <a href="#home">Home</a>
        <a href="#services">Services</a>
        <a href="#benefits">Benefits</a>
        <a href="#contact">Contact</a>
      </nav>

      {/* Hero */}
      <section className="lp-hero" id="home">
        <div className="lp-hero-content">
          <div className="lp-hero-badge">&#127973; Cigna Healthcare</div>
          <h1>Your Health,<br />Our Priority</h1>
          <p>Find the right doctor, book appointments, and manage your healthcare &mdash; all in one place with AI-powered assistance.</p>
          <div className="lp-hero-actions">
            <button className="lp-cta-btn" onClick={() => goToChat()}>
              &#128269; Find me providers
            </button>
            <a href="#services" className="lp-secondary-btn">Learn More</a>
          </div>
          {member && (
            <div className="lp-welcome-chip">
              &#128075; Welcome back, <strong>{member.first_name}</strong> &mdash; {member.insurance_plan}
            </div>
          )}
        </div>

        {/* Appointment History Panel */}
        {member && (
          <MemberPanel
            member={member}
            pcp={pcp}
            appointments={appointments}
            parseApptDateTime={parseApptDateTime}
            goToChat={goToChat}
          />
        )}
      </section>

      {/* Services */}
      <section className="lp-section" id="services">
        <div className="lp-section-inner">
          <div className="lp-section-label">What We Offer</div>
          <h2>Our Services</h2>
          <div className="lp-cards">
            {[
              { icon: '&#128269;', title: 'Find Providers', desc: 'Search in-network doctors near you by specialty, language, and consultation mode.' },
              { icon: '&#128197;', title: 'Book Appointments', desc: 'Schedule in-person or telehealth visits instantly with real-time slot availability.' },
              { icon: '&#128203;', title: 'Validate Provider', desc: 'Validates providers upon your plan, benefits, prior authorizations, and out-of-pocket costs and recommends.' },
            ].map(c => (
              <div className="lp-card" key={c.title}>
                <div className="lp-card-icon" dangerouslySetInnerHTML={{ __html: c.icon }} />
                <h3>{c.title}</h3>
                <p>{c.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Benefits */}
      <section className="lp-section lp-section-alt" id="benefits">
        <div className="lp-section-inner">
          <div className="lp-section-label">Member Perks</div>
          <h2>Member Benefits</h2>
          <div className="lp-cards">
            {[
              { icon: '&#127760;', title: 'Language Specificity', desc: 'Access to services in multiple languages to cater to diverse member needs.' },
              { icon: '&#127973;', title: 'Hospital Network', desc: 'Wide network of top-rated hospitals, clinics, and specialists.' },
              { icon: '&#127760;', title: 'Telehealth 24/7', desc: 'Connect with a doctor anytime, from anywhere — no travel needed.' },
            ].map(c => (
              <div className="lp-card" key={c.title}>
                <div className="lp-card-icon" dangerouslySetInnerHTML={{ __html: c.icon }} />
                <h3>{c.title}</h3>
                <p>{c.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Contact */}
      <section className="lp-section" id="contact">
        <div className="lp-section-inner lp-contact-inner">
          <div className="lp-section-label">Get In Touch</div>
          <h2>Contact Us</h2>
          <p className="lp-contact-text">Our support team is available Mon&ndash;Fri, 8am&ndash;6pm CST.</p>
          <div className="lp-contact-chips">
            <span className="lp-contact-chip">&#128222; 1-800-CIGNA</span>
            <span className="lp-contact-chip">&#9993;&#65039; support@cigna.com</span>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="app-footer">&copy; 2026 Cigna Healthcare. All rights reserved.</footer>

    </div>
  );
}

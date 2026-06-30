import React from 'react';
import {
  FaCheckCircle, FaSpinner, FaSearch, FaMapMarkerAlt,
  FaCalendarCheck, FaClipboardList, FaLink,
  FaUserMd, FaLanguage, FaShieldAlt, FaBrain,
} from 'react-icons/fa';
import { MdOutlineHub, MdPlayCircle, MdMedicalServices } from 'react-icons/md';

// ── Step diagram config ──────────────────────────────────────────────────────

const AGENT_STEP_MAP = {
  medilife_provider_search: 'orchestrator',
  speciality_agent: 'specialty',
  provider_agent: 'search',
};

const TOOL_STEP_MAP = {
  search_and_verify_providers: 'search',
  find_best_provider:          'search',
  search_with_preferences:     'search',
  lookup_provider_by_name:     'search',
  find_providers:              'search',
  notify_provider:             'results',
  check_availability:          'avail',
  check_urgent_availability:   'avail',
  book_appointment:            'booking',
  check_plan_rules:            'results',
  request_plan_change:         'results',
  search_providers_by_language:'search',
};

const TOOL_ICONS = {
  find_providers:      '🏥',
  notify_provider:     '📨',
  check_availability:  '📅',
  book_appointment:    '✅',
  request_plan_change: '🔄',
};

const STEPS = [
  { id: 'specialty', label: 'Specialty',  icon: <MdMedicalServices size={15} /> },
  { id: 'location',  label: 'Location',   icon: <FaMapMarkerAlt size={13} /> },
  { id: 'search',    label: 'Search',     icon: <FaSearch size={12} /> },
  { id: 'results',   label: 'Results',    icon: <FaClipboardList size={13} /> },
  { id: 'avail',     label: 'Avail.',     icon: <FaCalendarCheck size={12} /> },
  { id: 'booking',   label: 'Booking',    icon: <FaLink size={11} /> },
];

// ── Appointment card ─────────────────────────────────────────────────────────

function AppointmentCard({ appt, past = false, cancelled = false }) {
  const [expanded, setExpanded] = React.useState(false);
  const isTele = appt.consultation_type?.toLowerCase() === 'telehealth';
  
  return (
    <div
      onClick={() => setExpanded(e => !e)}
      style={{
        background: cancelled ? '#fff5f5' : past ? '#f8fafc' : '#f0fdf4',
        border: `1px solid ${cancelled ? '#fca5a5' : past ? '#e2e8f0' : '#86efac'}`,
        borderRadius: 8, padding: '8px 10px',
        display: 'flex', flexDirection: 'column', gap: 3,
        opacity: cancelled ? 0.85 : past ? 0.8 : 1,
        cursor: 'pointer',
        transition: 'box-shadow 0.15s',
        boxShadow: expanded ? '0 2px 8px rgba(0,0,72,0.10)' : 'none',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 6 }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            {cancelled && <span style={{ fontSize: 10, fontWeight: 700, color: '#dc2626' }}>❌ Cancelled</span>}
            <div style={{ fontSize: 11, fontWeight: 700, color: cancelled ? '#dc2626' : past ? '#64748b' : '#065f46', textDecoration: cancelled ? 'line-through' : 'none' }}>{appt.provider}</div>
          </div>
          <div style={{ fontSize: 10, color: '#475569' }}>{appt.date}{appt.time ? ` · ${appt.time}` : ''}</div>
        </div>
        {appt.consultation_type && !cancelled && (
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 2,
            fontSize: 9, padding: '2px 6px', borderRadius: 6, fontWeight: 600, whiteSpace: 'nowrap',
            background: isTele ? '#f0fdf4' : '#eff6ff',
            color: isTele ? '#15803d' : '#1d4ed8',
            border: `1px solid ${isTele ? '#bbf7d0' : '#bfdbfe'}`,
            flexShrink: 0,
          }}>
            {isTele ? '💻' : '🏥'} {appt.consultation_type}
          </div>
        )}
      </div>
      {appt.address && <div style={{ fontSize: 10, color: '#94a3b8' }}>{appt.address}</div>}
      {expanded && (
        <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid #e0e7ff', display: 'flex', flexDirection: 'column', gap: 4 }}>
          {appt.specialty && (
            <div style={{ fontSize: 11, color: '#475569' }}>
              <span style={{ fontWeight: 600, color: '#1e1e5c' }}>Specialty: </span>{appt.specialty}
            </div>
          )}
          {appt.reason && (
            <div style={{ fontSize: 11, color: '#475569' }}>
              <span style={{ fontWeight: 600, color: '#1e1e5c' }}>Reason: </span>{appt.reason}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Reasoning step card ──────────────────────────────────────────────────────

function ReasoningCard({ step, index }) {
  const [expanded, setExpanded] = React.useState(false);
  const icon  = TOOL_ICONS[step.tool] || '🔧';
  const label = step.label || step.tool;
  const blocked = step.decision && (step.decision.includes('⛔') || step.decision.toLowerCase().includes('blocked'));
  const confirmed = step.decision && step.decision.includes('✅');

  const borderColor = blocked ? '#fca5a5' : confirmed ? '#86efac' : '#c7d2fe';
  const bgColor     = blocked ? '#fff7f7' : confirmed ? '#f0fdf4' : '#f8faff';
  const labelColor  = blocked ? '#dc2626' : confirmed ? '#065f46' : '#1a2f5a';

  return (
    <div style={{
      border: `1px solid ${borderColor}`,
      borderRadius: 10,
      background: bgColor,
      transition: 'box-shadow 0.15s',
    }}>
      {/* Header row */}
      <button
        onClick={() => setExpanded(e => !e)}
        style={{
          width: '100%', textAlign: 'left',
          background: 'none', border: 'none', cursor: 'pointer',
          padding: '8px 10px',
          display: 'flex', alignItems: 'center', gap: 7,
        }}
      >
        <span style={{ fontSize: 14, flexShrink: 0 }}>{icon}</span>
        <span style={{ fontSize: 11, fontWeight: 700, color: labelColor, flex: 1, lineHeight: 1.3 }}>
          {label}
        </span>
        <span style={{
          fontSize: 9, color: '#94a3b8',
          transform: expanded ? 'rotate(90deg)' : 'none',
          transition: 'transform 0.2s',
          display: 'inline-block',
        }}>›</span>
      </button>

      {/* Expanded reasoning detail */}
      {expanded && (
        <div style={{
          padding: '0 10px 10px',
          display: 'flex', flexDirection: 'column', gap: 8,
          borderTop: `1px solid ${borderColor}`,
          paddingTop: 8,
        }}>
          {step.thought && (
            <div>
              <div style={{ fontSize: 9, fontWeight: 700, color: '#6366f1', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 3 }}>
                🧠 Why this tool was called
              </div>
              <div style={{ fontSize: 11, color: '#334155', lineHeight: 1.5 }}>
                {step.thought}
              </div>
            </div>
          )}
          {step.decision && (
            <div>
              <div style={{ fontSize: 9, fontWeight: 700, color: '#0891b2', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 3 }}>
                📋 What the agent decided
              </div>
              <div style={{ fontSize: 11, color: '#334155', lineHeight: 1.5 }}>
                {step.decision}
              </div>
            </div>
          )}
          {step.keyArgs && Object.keys(step.keyArgs).length > 0 && (
            <div>
              <div style={{ fontSize: 9, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 3 }}>
                ⚙️ Parameters used
              </div>
              <div style={{ fontSize: 10, color: '#64748b', fontFamily: 'monospace', lineHeight: 1.6 }}>
                {Object.entries(step.keyArgs).map(([k, v]) => (
                  <div key={k}><span style={{ color: '#6366f1' }}>{k}</span>: {String(v)}</div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main component ───────────────────────────────────────────────────────────

export default function AgentActivityPane({ events = [], isProcessing = false, initialTab = 'activity', locationChanged = false }) {
  const [tab, setTab] = React.useState(initialTab);
  const [active, setActive] = React.useState(null);
  const [animatingStep, setAnimatingStep] = React.useState(null);
  const [appointments, setAppointments] = React.useState(null);

  // ── Load appointments when tab switches OR when a booking just happened ──
  React.useEffect(() => {
    if (tab !== 'appointments') return;
    const member = JSON.parse(sessionStorage.getItem('member') || 'null');
    if (!member?.member_id) return;
    fetch(`/appointments/${member.member_id}`)
      .then(r => r.json())
      .then(d => setAppointments(d.appointments || []))
      .catch(() => {});
  }, [tab]);

  // Refresh appointments automatically when a booking is confirmed mid-session
  React.useEffect(() => {
    const hasBooking = events.some(e => e._sse && e.type === 'tool_result' && e.tool === 'book_appointment' && e.output?.status === 'confirmed');
    if (!hasBooking) return;
    const member = JSON.parse(sessionStorage.getItem('member') || 'null');
    if (!member?.member_id) return;
    fetch(`/appointments/${member.member_id}`)
      .then(r => r.json())
      .then(d => setAppointments(d.appointments || []))
      .catch(() => {});
  }, [events]);

  // ── Derive completed steps from events ──
  const completedSteps = React.useMemo(() => {
    const done = new Set();

    // Location node: pre-light if a location change was triggered this session
    if (locationChanged) done.add('location');

    for (const ev of events) {
      const author = ev?.author || '';
      if (author === 'speciality_agent') { done.add('specialty'); done.add('location'); }
      if (author === 'provider_agent')   { done.add('location'); }

      // SSE-style events
      if (ev._sse) {
        if (ev.type === 'tool_call') {
          const step = TOOL_STEP_MAP[ev.tool];
          if (step) done.add(step);

          // Specialty node: light up whenever find_providers is called with a specialty,
          // regardless of plan type (PPO direct or HMO→PCP). The agent has already
          // identified the specialty even when it routes to PCP first.
          if (ev.tool === 'find_providers') {
            const specialty = ev.input?.specialty || '';
            if (specialty) done.add('specialty');
          }

          // Location node: light up on any location-aware tool call (find_providers
          // always carries location context) or on explicit location-change events.
          if (
            ev.tool === 'find_providers' ||
            ev.tool === 'check_availability' ||
            ev.tool === 'book_appointment'
          ) {
            done.add('location');
          }
        }
        if (ev.type === 'tool_result') {
          const step = TOOL_STEP_MAP[ev.tool];
          if (step) done.add(step);
        }
        continue;
      }

      // ADK-style events (content.parts)
      for (const part of ev?.content?.parts || []) {
        const fnName = part?.functionCall?.name || part?.function_call?.name || '';
        const step = TOOL_STEP_MAP[fnName];
        if (step) done.add(step);
        if (fnName === 'find_providers') {
          const args = part?.functionCall?.args || part?.function_call?.args || {};
          if (args.specialty) done.add('specialty');
          done.add('location');
        }
        if (fnName === 'check_availability' || fnName === 'book_appointment') {
          done.add('location');
        }
        const fnResp = part?.functionResponse?.name || part?.function_response?.name || '';
        const respStep = TOOL_STEP_MAP[fnResp];
        if (respStep) done.add(respStep);
      }
    }
    if (done.has('search')) done.add('results');
    return done;
  }, [events, locationChanged]);

  // ── Derive active step ──
  const activeStep = React.useMemo(() => {
    if (isProcessing && events.length === 0) return 'orchestrator';
    const called = new Set();
    const responded = new Set();
    for (const ev of events) {
      // SSE-style
      if (ev._sse) {
        if (ev.type === 'tool_call'  && TOOL_STEP_MAP[ev.tool]) called.add(TOOL_STEP_MAP[ev.tool]);
        if (ev.type === 'tool_result' && TOOL_STEP_MAP[ev.tool]) responded.add(TOOL_STEP_MAP[ev.tool]);
        continue;
      }
      for (const part of ev?.content?.parts || []) {
        const fnName = part?.functionCall?.name || part?.function_call?.name || '';
        if (fnName && TOOL_STEP_MAP[fnName]) called.add(TOOL_STEP_MAP[fnName]);
        const fnResp = part?.functionResponse?.name || part?.function_response?.name || '';
        if (fnResp && TOOL_STEP_MAP[fnResp]) responded.add(TOOL_STEP_MAP[fnResp]);
      }
    }
    for (const s of called) { if (!responded.has(s)) return s; }
    if (isProcessing && events.length > 0) {
      const author = events[events.length - 1]?.author || '';
      if (author === 'speciality_agent') return 'specialty';
      if (author === 'provider_agent')   return 'search';
    }
    return null;
  }, [events, isProcessing]);

  // ── Build reasoning steps from SSE tool_call events ──
  // Each event with type=tool_call carries { tool, thought, input, label }
  // Each event with type=tool_result carries { tool, decision }
  const reasoningSteps = React.useMemo(() => {
    const steps = [];
    const callMap = {}; // tool → step index

    for (const ev of events) {
      // SSE-style events (from streamAgentEvents fed into AgentActivityPane)
      if (ev._sse) {
        if (ev.type === 'tool_call') {
          const idx = steps.length;
          callMap[ev.tool + '_' + idx] = idx;
          // keep track by insertion order
          ev._stepIdx = idx;
          const keyArgs = {};
          const inp = ev.input || {};
          if (inp.specialty)          keyArgs.specialty          = inp.specialty;
          if (inp.doctor_name)        keyArgs.doctor_name        = inp.doctor_name;
          if (inp.provider_name)      keyArgs.provider_name      = inp.provider_name;
          if (inp.notification_type)  keyArgs.notification_type  = inp.notification_type;
          if (inp.new_plan)           keyArgs.new_plan           = inp.new_plan;
          if (inp.time_slot)          keyArgs.time_slot          = inp.time_slot;
          if (inp.appointment_date)   keyArgs.appointment_date   = inp.appointment_date;
          steps.push({
            tool:     ev.tool,
            label:    ev.label || ev.tool,
            thought:  ev.thought || '',
            decision: '',
            keyArgs,
          });
        }
        if (ev.type === 'tool_result') {
          // attach decision to the last call for this tool
          for (let i = steps.length - 1; i >= 0; i--) {
            if (steps[i].tool === ev.tool && !steps[i].decision) {
              steps[i].decision = ev.decision || '';
              break;
            }
          }
        }
        continue;
      }

      // ADK-style events (from content.parts functionCall / functionResponse)
      for (const part of ev?.content?.parts || []) {
        const fnCall = part?.functionCall || part?.function_call;
        if (fnCall?.name) {
          const args = fnCall.args || {};
          const keyArgs = {};
          if (args.specialty)         keyArgs.specialty         = args.specialty;
          if (args.doctor_name)       keyArgs.doctor_name       = args.doctor_name;
          if (args.provider_name)     keyArgs.provider_name     = args.provider_name;
          if (args.notification_type) keyArgs.notification_type = args.notification_type;
          if (args.new_plan)          keyArgs.new_plan          = args.new_plan;
          steps.push({
            tool:     fnCall.name,
            label:    (TOOL_ICONS[fnCall.name] || '🔧') + ' ' + fnCall.name.replace(/_/g, ' '),
            thought:  '',
            decision: '',
            keyArgs,
          });
        }
        const fnResp = part?.functionResponse || part?.function_response;
        if (fnResp?.name) {
          for (let i = steps.length - 1; i >= 0; i--) {
            if (steps[i].tool === fnResp.name && !steps[i].decision) {
              steps[i].decision = '';
              break;
            }
          }
        }
      }
    }
    return steps;
  }, [events]);

  // ── Animate step transitions ──
  React.useEffect(() => {
    if (activeStep && activeStep !== animatingStep) {
      setAnimatingStep(activeStep);
      const t = setTimeout(() => setAnimatingStep(null), 800);
      return () => clearTimeout(t);
    }
  }, [activeStep]);

  const completedCount     = completedSteps.size;
  const hasStarted         = events.length > 0 || isProcessing;
  const orchestratorDone   = completedSteps.size > 0 || (isProcessing && events.length > 0);
  const orchestratorActive = isProcessing && events.length === 0;

  // ── Appointment split ──
  const now = Date.now();
  const parseDate = (s) => { if (!s) return null; const d = new Date(s.replace(/^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s*/i, '')); return isNaN(d) ? null : d; };
  const parseDateTime = (a) => {
    const d = parseDate(a.date);
    if (!d) return Infinity;
    if (a.time) {
      const t = new Date(`${d.toDateString()} ${a.time}`);
      if (!isNaN(t)) return t.getTime();
    }
    return d.getTime();
  };
  const apptList = appointments || [];
  const upcoming = apptList
    .filter(a => {
      if ((a.status || '').toLowerCase() === 'cancelled') return false;
      const ts = parseDateTime(a);
      return ts === Infinity || ts >= now;
    })
    .sort((a, b) => parseDateTime(a) - parseDateTime(b));
  const past = apptList
    .filter(a => {
      if ((a.status || '').toLowerCase() === 'cancelled') return false;
      const ts = parseDateTime(a);
      return ts !== Infinity && ts < now;
    })
    .sort((a, b) => parseDateTime(a) - parseDateTime(b));
  const cancelled = apptList
    .filter(a => (a.status || '').toLowerCase() === 'cancelled')
    .sort((a, b) => parseDateTime(b) - parseDateTime(a));

  const tabs = [
    { id: 'activity',     label: '⚡ Activity' },
    { id: 'reasoning',    label: '🧠 Reasoning' },
    { id: 'appointments', label: '📅 Appts' },
  ];

  return (
    <div className="aap-root">
      {/* Header */}
      <div className="aap-header">
        <span className="aap-pulse-dot" />
        <span className="aap-header-title">Agent Activity</span>
        <span className="aap-live-badge">Live</span>
      </div>

      {/* Tab bar */}
      <div style={{ display: 'flex', borderBottom: '2px solid #e0e7ff', flexShrink: 0 }}>
        {tabs.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            flex: 1, padding: '7px 0', fontSize: 10, fontWeight: 700,
            background: 'none', border: 'none', cursor: 'pointer',
            color: tab === t.id ? '#1a2f5a' : '#94a3b8',
            borderBottom: tab === t.id ? '2px solid #1a2f5a' : '2px solid transparent',
            marginBottom: -2, letterSpacing: 0.3,
          }}>
            {t.label}
          </button>
        ))}
      </div>

      {/* ── Activity tab: diagram ── */}
      {tab === 'activity' && (
        <div className="aap-scroll">
          {/* Task Start */}
          <div className="aap-level-center">
            <div className="aap-node aap-node-task">
              <MdPlayCircle size={20} color={hasStarted ? '#10b981' : '#1a2f5a'} />
            </div>
            <div className="aap-node-label">Task Start</div>
          </div>

          <div className="aap-vline" />

          {/* Orchestrator */}
          <div className="aap-level-center">
            <div className={`aap-node aap-node-orch ${orchestratorActive ? 'aap-node-active' : ''}`}>
              <MdOutlineHub size={20} color="#fff" />
              {orchestratorActive && (
                <span className="aap-check-badge"><FaSpinner size={10} color="#f59e0b" className="aap-spin" /></span>
              )}
              {orchestratorDone && !orchestratorActive && (
                <span className="aap-check-badge"><FaCheckCircle size={10} color="#10b981" /></span>
              )}
            </div>
            <div className="aap-node-label aap-orch-label">Agent</div>
          </div>

          <div className="aap-vline" />

          {/* Branch connector */}
          <div className="aap-branch-wrap">
            <div className="aap-branch-hline" />
            <div className="aap-branch-ticks">
              {STEPS.map((_, i) => <div key={i} className="aap-branch-tick" />)}
            </div>
          </div>

          {/* Step nodes */}
          <div className="aap-agents-row">
            {STEPS.map((step) => {
              const isDone      = completedSteps.has(step.id);
              const isRunning   = activeStep === step.id;
              const isAnimating = animatingStep === step.id;
              const status      = isRunning ? 'in-progress' : isDone ? 'completed' : 'idle';
              return (
                <div key={step.id} className="aap-agent-col"
                  onClick={() => setActive(p => p === step.id ? null : step.id)}>
                  <div className={`aap-node aap-node-agent ${
                      status === 'idle' ? 'aap-node-idle' : 'aap-node-done'
                    } ${isRunning   ? 'aap-node-active' : ''
                    } ${isAnimating ? 'aap-node-pulse'  : ''}`}>
                    <span className="aap-agent-icon">{step.icon}</span>
                    {status === 'completed'   && <span className="aap-check-badge"><FaCheckCircle size={10} color="#10b981" /></span>}
                    {status === 'in-progress' && <span className="aap-check-badge"><FaSpinner size={10} color="#f59e0b" className="aap-spin" /></span>}
                  </div>
                  <div className={`aap-node-label aap-agent-label ${status === 'idle' ? 'aap-label-idle' : ''}`}>
                    {step.label}
                  </div>
                  {active === step.id && (
                    <div className="aap-tooltip">
                      <div className="aap-tooltip-name">{step.label}</div>
                      <div className={`aap-tooltip-status aap-status-${status}`}>
                        {status === 'completed' ? '✓ Completed' : status === 'in-progress' ? '⟳ Running' : '○ Pending'}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

        </div>
      )}

      {/* ── Reasoning tab ── */}
      {tab === 'reasoning' && (
        <div className="aap-scroll" style={{ padding: '10px 8px', gap: 8, display: 'flex', flexDirection: 'column', overflowY: 'auto', overflowX: 'hidden' }}>
          {reasoningSteps.length === 0 && (
            <div style={{
              fontSize: 12, color: '#94a3b8', textAlign: 'center',
              marginTop: 24, lineHeight: 1.6,
            }}>
              {isProcessing
                ? '⏳ Agent is thinking…'
                : 'No tool calls yet.\nSend a message to see the agent reason through your request.'}
            </div>
          )}
          {reasoningSteps.map((step, i) => (
            <ReasoningCard key={i} step={step} index={i} />
          ))}
          {isProcessing && reasoningSteps.length > 0 && (
            <div style={{
              fontSize: 11, color: '#6366f1', textAlign: 'center',
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
            }}>
              <FaSpinner size={10} className="aap-spin" style={{ color: '#6366f1' }} />
              Reasoning…
            </div>
          )}
        </div>
      )}

      {/* ── Appointments tab ── */}
      {tab === 'appointments' && (
        <div className="aap-scroll" style={{ padding: '12px 10px', gap: 10 }}>
          {appointments === null && (
            <div style={{ fontSize: 12, color: '#94a3b8', textAlign: 'center', marginTop: 20 }}>Loading appointments...</div>
          )}
          {appointments !== null && appointments.length === 0 && (
            <div style={{ fontSize: 12, color: '#94a3b8', textAlign: 'center', marginTop: 20 }}>No appointments found.</div>
          )}
          {upcoming.length > 0 && (
            <>
              <div style={{ fontSize: 10, fontWeight: 700, color: '#1a2f5a', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>Upcoming</div>
              {upcoming.map((a, i) => <AppointmentCard key={i} appt={a} />)}
            </>
          )}
          {past.length > 0 && (
            <>
              <div style={{ fontSize: 10, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.5, margin: '10px 0 4px' }}>Past</div>
              {past.map((a, i) => <AppointmentCard key={i} appt={a} past />)}
            </>
          )}
          {cancelled.length > 0 && (
            <>
              <div style={{ fontSize: 10, fontWeight: 700, color: '#dc2626', textTransform: 'uppercase', letterSpacing: 0.5, margin: '10px 0 4px', display: 'flex', alignItems: 'center', gap: 4 }}>
                <span>&#x274C;</span> Cancelled
              </div>
              {cancelled.map((a, i) => <AppointmentCard key={i} appt={a} cancelled />)}
            </>
          )}
        </div>
      )}

      {/* Footer */}
      <div className="aap-footer">
        <span className="aap-footer-dot" />
        {tab === 'activity'
          ? <span>{completedCount} / {STEPS.length} tasks completed</span>
          : tab === 'reasoning'
          ? <span>{reasoningSteps.length} reasoning step{reasoningSteps.length !== 1 ? 's' : ''}</span>
          : <span>{apptList.length} appointment{apptList.length !== 1 ? 's' : ''}</span>
        }
      </div>
    </div>
  );
}

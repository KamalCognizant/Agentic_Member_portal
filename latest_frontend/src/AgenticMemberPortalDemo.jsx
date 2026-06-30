import React, { useState, useRef, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { FaChevronLeft, FaChevronRight, FaArrowDown, FaStop, FaPaperPlane, FaBell, FaMapMarkerAlt } from 'react-icons/fa';
import MessageBubble, { extractSuggestions } from './Components/MessageBubble';
import ProviderGrid from './Components/ProviderGrid';
import BookingConfirmation from './Components/BookingConfirmation';

function ProTipGuide({ tips }) {
  const [expanded, setExpanded] = useState(false);
  const contentRef = useRef(null);
  
  if (!tips || tips.length === 0) return null;
  return (
    <div style={{ marginTop: 16, marginBottom: 12, display: 'flex', flexDirection: 'column', alignItems: 'flex-end', width: '100%' }}>
      <button 
        onClick={() => setExpanded(!expanded)}
        onMouseEnter={(e) => {
          e.currentTarget.style.transform = 'translateY(-1px)';
          e.currentTarget.style.boxShadow = '0 4px 12px rgba(16, 185, 129, 0.25)';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.transform = 'translateY(0)';
          e.currentTarget.style.boxShadow = '0 2px 6px rgba(16, 185, 129, 0.15)';
        }}
        style={{
          display: 'flex', alignItems: 'center', gap: 8,
          background: expanded ? '#059669' : '#ffffff',
          color: expanded ? '#ffffff' : '#059669',
          border: '1.5px solid #059669', borderRadius: 24,
          padding: '8px 18px', fontSize: 13, fontWeight: 600,
          cursor: 'pointer', boxShadow: '0 2px 6px rgba(16, 185, 129, 0.15)',
          transition: 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
          marginRight: 10
        }}
      >
        <span style={{ fontSize: 15, transition: 'transform 0.3s', transform: expanded ? 'rotate(180deg)' : 'rotate(0)' }}>
          {expanded ? '💡' : '💡'}
        </span>
        {expanded ? 'Hide Care Tips' : 'Tap for Pre-Visit Care Tips'}
      </button>
      
      <div 
        ref={contentRef}
        style={{
          marginTop: expanded ? 12 : 0,
          maxHeight: expanded ? `${contentRef.current?.scrollHeight + 40}px` : '0px',
          opacity: expanded ? 1 : 0,
          overflow: 'hidden',
          transition: 'all 0.35s cubic-bezier(0.4, 0, 0.2, 1)',
          width: '85%',
          marginRight: 10
        }}
      >
        <div style={{
          padding: '16px 20px', 
          background: 'linear-gradient(to right bottom, #f0fdf4, #ffffff)',
          borderRadius: 12, border: '1px solid #a7f3d0',
          boxShadow: '0 4px 15px -3px rgba(16, 185, 129, 0.08)',
        }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#065f46', marginBottom: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
            <span>While you wait for your appointment:</span>
          </div>
          <ul style={{ margin: 0, paddingLeft: 22, color: '#334155', fontSize: 13, lineHeight: 1.6 }}>
            {tips.map((tip, i) => {
              const parts = tip.split(':');
              if (parts.length > 1 && parts[0].split(' ').length <= 4) {
                return (
                  <li key={i} style={{ marginBottom: 10 }}>
                    <strong style={{ color: '#0f766e' }}>{parts[0]}:</strong>{parts.slice(1).join(':')}
                  </li>
                );
              }
              return <li key={i} style={{ marginBottom: 10 }}>{tip}</li>;
            })}
          </ul>
        </div>
      </div>
    </div>
  );
}

import AgentActivityPane from './Components/AgentActivityPane';
import './Dashboard.css';

const APP_NAME = 'adk';

function parseProviders(text) {
  const providers = [];
  // Extract provider name from the header line BEFORE splitting into blocks
  // e.g. "here is the best match for you: **Dr. JASON BRONSTEIN, M.D.**"
  const globalNameMatch = text.match(/best match for you[:\s]+\*\*([^*\n]+)\*\*/i)
    || text.match(/best match for you[:\s]+([A-Z][A-Za-z\s.,]+(?:MD|DO|M\.D\.|D\.O\.))/i);
  const globalName = globalNameMatch ? globalNameMatch[1].trim().replace(/\*\*/g, '') : null;

  const blocks = text.split(/\n(?=(?:✅|❌)\s)/);
  let providerIndex = 0;
  for (const block of blocks) {
    if (!block.trim()) continue;
    const isInNetwork = block.startsWith('✅');
    const isOutOfNetwork = block.startsWith('❌');
    if (!isInNetwork && !isOutOfNetwork) continue;
    const lines = block.split('\n').map(l => l.trim()).filter(Boolean);
    const headerLine = lines[0] || '';
    const tierMatch = headerLine.match(/In-Network/i);
    const distanceMatch = headerLine.match(/\((\d+\.?\d*\s*mi)\)/g);
    const distance = distanceMatch ? distanceMatch[distanceMatch.length - 1].replace(/[()]/g, '') : '';
    const nameMatch = lines.find(l => l.startsWith('Dr.') || l.match(/^[A-Z][A-Z\s]+(?:MD|DO|INC|LLC|NPI)/));
    const ratingMatch = headerLine.match(/⭐\s*(\d+\.?\d*)\/5/);
    const npiMatch = block.match(/NPI:\s*(\d+)/);
    const specialtyMatch = block.match(/Specialty:\s*(.+)/);
    const addressMatch = block.match(/Address:\s*(.+)/);
    const phoneMatch = block.match(/Phone:\s*([\d\-]+)/);
    const consultMatch = block.match(/Consultation:\s*(.+)/);
    const languagesMatch = block.match(/Languages:\s*(.+)/);
    const genderMatch = block.match(/Gender:\s*([MF])/i);
    const cityMatch = block.match(/(?:Address|City):\s*[^,\n]+,\s*([A-Za-z\s]+),\s*[A-Z]{2}/)
      || (addressMatch && addressMatch[1].match(/,\s*([A-Za-z\s]+),\s*[A-Z]{2}/));
    const cityFromAddress = cityMatch ? cityMatch[1].trim() : '';
    // Use global name for first provider, fall back to line-based extraction
    const nameRaw = (providerIndex === 0 && globalName)
      ? globalName
      : (lines[1] || nameMatch || 'Unknown Provider');
    const name = (typeof nameRaw === 'string' ? nameRaw : nameRaw[0])
      .replace(/^Name:\s*/i, '')
      .replace(/\*\*/g, '');
    providers.push({
      name,
      npi: npiMatch ? npiMatch[1] : '',
      specialty: specialtyMatch ? specialtyMatch[1].trim() : '',
      address: addressMatch ? addressMatch[1].trim() : '',
      city: cityFromAddress,
      phone: phoneMatch ? phoneMatch[1].trim() : '',
      consultation: consultMatch ? consultMatch[1].trim().replace(/&amp;/g, '&') : '',
      distance,
      tier: tierMatch ? 'In-Network' : '',
      status: isInNetwork ? 'in-network' : 'out-of-network',
      rating: ratingMatch ? parseFloat(ratingMatch[1]) : null,
      languages: languagesMatch ? languagesMatch[1].trim() : '',
      gender: genderMatch ? genderMatch[1].toUpperCase() : '',
      llm_reasoning: null,
      tradeoff: null,
      rejected_others: [],
      critic_note: null,
    });
    providerIndex++;
  }
  return providers;
}

function parseTimeSlots(text) {
  const decoded = text.replace(/&amp;/g, '&');
  const slots = [];
  const lines = decoded.split('\n');
  let currentType = null;
  for (const line of lines) {
    const trimmed = line.trim();
    if (/^in-person\s*(&\s*telehealth)?\s*slot/i.test(trimmed)) {
      currentType = /telehealth/i.test(trimmed) ? 'Both' : 'In-Person';
      continue;
    }
    if (/^telehealth\s*slot/i.test(trimmed)) { currentType = 'Telehealth'; continue; }
    const regex = /(\d{1,2}:\d{2}\s*(?:AM|PM)\s*(?:CST|PST|EST|MST|CDT|PDT|EDT)(?:\s*\([^)]+\))?)/gi;
    let match;
    while ((match = regex.exec(trimmed)) !== null) {
      slots.push({ time: match[1].trim(), type: currentType });
    }
  }
  return slots;
}

function parseBooking(text) {
  // Strip summary note lines (e.g. "📅 Booking: ...") before parsing to avoid double booking
  const cleanText = text.split('\n').filter(l => !l.trim().startsWith('📅')).join('\n');
  const lower = cleanText.toLowerCase();
  const isBookingConfirmation =
    lower.includes('successfully booked') ||
    lower.includes('appointment confirmed') ||
    lower.includes('appointment is confirmed') ||
    (lower.includes('confirmed') && lower.includes('appointment')) ||
    (lower.includes('booked') && (lower.includes('dr.') || lower.includes('provider')));

  if (!isBookingConfirmation) return null;

  const dateMatch = cleanText.match(/(?:for|on)\s+((?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})/i)
    || cleanText.match(/(?:for|on)\s+((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})/i)
    || cleanText.match(/Date:\s*(.+)/);
  const timeMatch = cleanText.match(/(?:at)\s+(\d{1,2}:\d{2}\s*(?:AM|PM)(?:\s*(?:PST|CST|EST|MST|PDT|CDT|EDT))?)/i)
    || cleanText.match(/Time(?:\s*Start)?:\s*(.+)/);
  const providerLineMatch = cleanText.match(/Provider(?:\s*Name)?:\s*([^\n]+)/);
  const drInlineMatch = cleanText.match(/(?:with|for)\s+((?:Dr\.\s+)?[A-Z][A-Z\-\s,\.]+?)(?=\s+(?:has|is|for|on|at|\())/i);
  const providerRaw = providerLineMatch ? providerLineMatch[1].trim() : (drInlineMatch ? drInlineMatch[1].trim() : '');
  const provider = providerRaw.replace(/\s+(has|is|was|have|been|will|for|on|at).*$/i, '').trim();
  const addressMatch = cleanText.match(/(?:visit at|located at|address[:\s]+)\s*(\d+[^.\n]+)/i)
    || cleanText.match(/at\s+(\d+\s+[A-Z][^.\n]{10,})/);

  if (!dateMatch && !timeMatch && !provider) return null;

  const todayStr = new Date().toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
  return {
    date: dateMatch ? dateMatch[1].trim() : todayStr,
    time: timeMatch ? timeMatch[1].trim() : '',
    provider,
    address: addressMatch ? addressMatch[1].trim() : '',
  };
}

function classifyResponse(text) {
  const decoded = text.replace(/&amp;/g, '&');
  const lower = decoded.toLowerCase();
  const hasProviders = (decoded.includes('✅') || decoded.includes('❌')) && decoded.includes('NPI:');
  const isBookingMsg =
    lower.includes('successfully booked') ||
    lower.includes('appointment confirmed') ||
    lower.includes('appointment is confirmed') ||
    (lower.includes('confirmed') && lower.includes('appointment')) ||
    (lower.includes('booked') && (lower.includes('dr.') || lower.includes('provider')));
  // Suppress slot widget when agent is reporting an error about a slot being outside clinic hours
  const isSlotError =
    (lower.includes('outside') && lower.includes('clinic hours')) ||
    (lower.includes('sorry') && lower.includes('not available') && lower.includes('slot'));
  // Suppress slot widget when agent is referencing a past/existing appointment (not offering new slots)
  const isAppointmentReference =
    (lower.includes('i see you have an appointment') ||
      lower.includes('you have an appointment') ||
      lower.includes('you had an appointment') ||
      lower.includes('your appointment with') ||
      lower.includes('previous appointment') ||
      lower.includes('past appointment')) &&
    !lower.includes('available slot') &&
    !lower.includes('which of these times') &&
    !lower.includes('would you like to book one of these');
  // Allow provider card even when plan-change warning is present
  const isPlanChangeResponse = lower.includes('plan has') && lower.includes('out-of-network') && decoded.includes('NPI:');
  const hasSlots = false; // slots are shown on provider cards, not in chat text
  const hasBooking = !hasProviders && isBookingMsg;
  return { hasProviders: hasProviders || isPlanChangeResponse, hasSlots, hasBooking };
}

function stripStructuredContent(text) {
  const decoded = text.replace(/&amp;/g, '&');
  let cleaned = decoded.replace(/^[✅❌][^\n]*(\n(?!\n)[^\n]+)*/gm, '').trim();
  // DO NOT strip individual time slots - they should display in the message text
  // Only strip the header lines if needed
  cleaned = cleaned.replace(/Appointment Details:[\s\S]*$/i, '').trim();
  // Strip "Also considered" lines (shown in AgentReasoningDropdown instead)
  cleaned = cleaned.replace(/^.*🤖\s*Also considered:.*$/gim, '').trim();
  cleaned = cleaned.replace(/\n{3,}/g, '\n\n').trim();
  return cleaned;
}

// ── Agent Reasoning Live (dynamic based on user message intent) ──────────────

function inferStages(userText) {
  const t = (userText || '').toLowerCase();
  if (
    t.includes('book') || t.includes('slot') || t.includes('appointment') ||
    t.includes('available') || t.includes('schedule') || t.includes('time')
  ) return [
    { label: 'Thinking', minMs: 0 },
    { label: 'Checking availability', minMs: 1500 },
    { label: 'Fetching slots', minMs: 3500 },
  ];
  if (
    t.includes('doctor') || t.includes('provider') || t.includes('specialist') ||
    t.includes('find') || t.includes('search') || t.includes('near') ||
    t.includes('pain') || t.includes('symptom') || t.includes('hurt') ||
    t.includes('ache') || t.includes('sick') || t.includes('rash') ||
    t.includes('fever') || t.includes('headache') || t.includes('chest') ||
    t.includes('stomach') || t.includes('back') || t.includes('knee') ||
    t.includes('eye') || t.includes('ear') || t.includes('skin')
  ) return [
    { label: 'Thinking', minMs: 0 },
    { label: 'Mapping specialty', minMs: 2000 },
    { label: 'Searching network', minMs: 4500 },
    { label: 'Ranking providers', minMs: 7000 },
  ];
  if (t.includes('referral') || t.includes('coverage') || t.includes('plan') || t.includes('auth')) return [
    { label: 'Thinking', minMs: 0 },
    { label: 'Checking plan rules', minMs: 1500 },
  ];
  return [
    { label: 'Thinking', minMs: 0 },
  ];
}

function AgentReasoningLive({ userText }) {
  const stages = React.useMemo(() => inferStages(userText), [userText]);
  const [stageIndex, setStageIndex] = React.useState(0);
  const [tick, setTick] = React.useState(0);

  React.useEffect(() => {
    setStageIndex(0);
    const timers = stages.slice(1).map((s, i) =>
      setTimeout(() => setStageIndex(i + 1), s.minMs)
    );
    return () => timers.forEach(clearTimeout);
  }, [stages]);

  React.useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), 500);
    return () => clearInterval(id);
  }, []);

  const dots = '\u00b7'.repeat((tick % 3) + 1).padEnd(3, '\u00a0');
  const currentStage = stages[stageIndex] || stages[0];

  return (
    <div style={{
      background: '#f8faff',
      border: '1px solid #e0e7ff',
      borderRadius: 12,
      padding: '12px 16px',
      maxWidth: '70%',
      display: 'flex',
      alignItems: 'center',
      gap: 8,
    }}>
      <span style={{ fontSize: 14, display: 'inline-block', animation: 'spin 1.5s linear infinite' }}>⚙️</span>
      <span style={{ fontSize: 13, fontWeight: 600, color: '#1a2f5a' }}>
        {currentStage.label}{dots}
      </span>
    </div>
  );
}

// ── Tool labels (used by AgentReasoningDropdown) ───────────────────────────

const TOOL_LABELS = {
  lookup_taxonomy: '🔬 Identifying medical specialty',
  find_best_provider: '🏥 Scored providers across network, distance & ratings',
  search_and_verify_providers: '🔍 Searched & verified providers in your network',
  search_with_preferences: '⚙️ Applied your preferences (gender, language)',
  lookup_provider_by_name: '👤 Looked up doctor by name',
  check_availability: '📅 Checked real-time appointment availability',
  check_urgent_availability: '🚨 Checked same-day urgent slots',
  book_appointment: '✅ Booked your appointment',
  check_plan_rules: '📋 Checked your plan rules & coverage',
  search_providers_by_language: '🌐 Found providers who speak your language',
  // New agentic tools
  find_providers:      '🏥 Searched for in-network providers',
  notify_provider:     '📨 Notified provider\'s office',
  request_plan_change: '🔄 Processed plan change request',
};

// ── Agent Reasoning Dropdown (shown after results) ────────────────────────────

function AgentReasoningDropdown({ events, alsoConsidered }) {
  const [open, setOpen] = React.useState(false);
  const steps = [];
  const seen = new Set();
  let rejectedOthers = [];

  for (const ev of events || []) {
    const author = ev?.author || '';
    if (author === 'speciality_agent' && !seen.has('__speciality__')) {
      seen.add('__speciality__');
      steps.push({ label: '🧠 Analysed symptoms & identified specialty', done: true });
    }

    // ── SSE-style events from new agentic tools (_sse flag) ──────────────────
    if (ev._sse && ev.type === 'tool_call') {
      const key = ev.tool + '_' + steps.length;
      if (!seen.has(key)) {
        seen.add(key);
        const baseLabel = TOOL_LABELS[ev.tool] || ('🔧 ' + ev.tool.replace(/_/g, ' '));
        steps.push({ label: '✅ ' + baseLabel, thought: ev.thought || '', decision: '', done: true, _tool: ev.tool });
      }
      continue;
    }
    if (ev._sse && ev.type === 'tool_result') {
      // Attach decision to the most recent step for this tool
      for (let i = steps.length - 1; i >= 0; i--) {
        if (steps[i]._tool === ev.tool && !steps[i].decision) {
          steps[i].decision = ev.decision || '';
          break;
        }
      }
      continue;
    }

    for (const part of ev?.content?.parts || []) {
      const fn = part?.functionCall?.name || part?.function_call?.name || '';
      if (fn && !seen.has(fn)) {
        const label = TOOL_LABELS[fn];
        if (label) {
          seen.add(fn);
          steps.push({ label: '✅ ' + label.replace(/\.\.\.$/, ' — done'), done: true });
        } else if (fn) {
          // Show all tool calls even if not in TOOL_LABELS
          seen.add(fn);
          steps.push({ label: '✅ 🔧 ' + fn.replace(/_/g, ' '), done: true });
        }
      }
      // Extract rejected_others from find_best_provider / search_with_preferences response
      const fr = part?.functionResponse || part?.function_response;
      if (fr?.name === 'find_best_provider' || fr?.name === 'search_with_preferences') {
        try {
          const resp = typeof fr.response === 'string' ? JSON.parse(fr.response) : fr.response;
          const best = resp?.best_provider;
          if (best?.rejected_others?.length > 0 && rejectedOthers.length === 0) {
            rejectedOthers = best.rejected_others;
          }
        } catch (_) { }
      }
    }
  }

  if (steps.length === 0) return null;
  return (
    <div style={{ marginTop: 6, maxWidth: '70%' }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          display: 'flex', alignItems: 'center', gap: 5,
          background: 'none', border: '1px solid #e0e7ff', borderRadius: 8,
          padding: '4px 10px', cursor: 'pointer', fontSize: 11,
          color: '#1a2f5a', fontWeight: 600,
        }}
      >
        <span style={{ transition: 'transform 0.2s', display: 'inline-block', transform: open ? 'rotate(90deg)' : 'rotate(0deg)' }}>›</span>
        🤖 Agent Reasoning Trace
      </button>
      {open && (
        <div style={{
          marginTop: 4, background: '#f8faff', border: '1px solid #e0e7ff',
          borderRadius: 10, padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 5,
        }}>
          {steps.map((s, i) => (
            <div key={i} style={{ fontSize: 12, color: '#065f46', display: 'flex', flexDirection: 'column', gap: 2 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>{s.label}</div>
              {s.thought && (
                <div style={{ fontSize: 11, color: '#4b5563', paddingLeft: 18, fontStyle: 'italic' }}>
                  💭 {s.thought}
                </div>
              )}
              {s.decision && (
                <div style={{ fontSize: 11, color: '#1d4ed8', paddingLeft: 18 }}>
                  📋 {s.decision}
                </div>
              )}
            </div>
          ))}
          {(alsoConsidered || rejectedOthers.length > 0) && (
            <>
              <div style={{ height: 1, background: '#e0e7ff', margin: '4px 0' }} />
              {alsoConsidered && (
                <div style={{ fontSize: 11, color: '#64748b', display: 'flex', alignItems: 'flex-start', gap: 5, paddingLeft: 8 }}>
                  <span style={{ flexShrink: 0 }}>↳</span>
                  <span>🤖 Also considered: {alsoConsidered}</span>
                </div>
              )}
              {rejectedOthers.map((r, i) => (
                <div key={i} style={{ fontSize: 11, color: '#64748b', display: 'flex', alignItems: 'flex-start', gap: 5, paddingLeft: 8 }}>
                  <span style={{ flexShrink: 0 }}>↳</span>
                  <span><strong>Also checked:</strong> {r.name} — {r.rejection_reason}</span>
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ── Context Controls (Location only) ────────────────────────────────────────

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

function ContextControls({ userId, travelCity, travelState, homeCity, homeState, currentPlan, setTravelCity, setTravelState, setCurrentPlan, setMessages, setLoading, loading }) {
  const [locHover, setLocHover] = React.useState(false);

  const selBase = {
    width: '100%',
    fontSize: 12,
    fontFamily: 'inherit',
    fontWeight: 500,
    background: '#ffffff',
    border: '1.5px solid #e2e8f0',
    borderRadius: 8,
    padding: '7px 30px 7px 10px',
    color: '#000048',
    cursor: 'pointer',
    outline: 'none',
    appearance: 'none',
    WebkitAppearance: 'none',
    transition: 'border-color 0.2s, box-shadow 0.2s',
    boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
  };

  const onLocationChange = async (val) => {
    const [city, state] = val.split('|');
    const wasTravel = travelCity !== '' && travelCity !== homeCity;
    const newTravelCity  = (city === homeCity && state === homeState) ? '' : city;
    const newTravelState = (city === homeCity && state === homeState) ? '' : state;
    const isNowTravel = newTravelCity !== '';
    setTravelCity(newTravelCity);
    setTravelState(newTravelState);

    if (isNowTravel && !wasTravel) {
      const loc = newTravelCity + ', ' + newTravelState;
      setMessages(prev => [...prev, {
        id: Date.now(), role: 'system-note',
        text: `✈️ Location changed to ${loc} — providers will now be searched near your travel location (home: ${homeCity}).`,
        providers: [], slots: [], booking: null,
      }]);
      if (!loading) {
        // Do NOT call setLoading(true) here — that triggers AgentReasoningLive spinner,
        // which combined with the isLoading bubble below creates two loaders at once.
        // The typing dots bubble is sufficient (same pattern as initWelcome).
        const loadingId = Date.now() + 1;
        setMessages(prev => [...prev, { id: loadingId, role: 'assistant', text: '...', providers: [], slots: [], booking: null, isLoading: true }]);
        try {
          const resp = await fetch('/chat/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: '__location_change__', user_id: userId, travel_city: newTravelCity, travel_state: newTravelState }),
          });
          if (resp.ok) {
            const reader = resp.body.getReader();
            const dec = new TextDecoder();
            let buf = '';
            let agentText = '';
            let agentProviders = [];
            let streamEvts = [];
            let partialTexts = [];
            while (true) {
              const { done, value } = await reader.read();
              if (done) break;
              buf += dec.decode(value, { stream: true });
              const lines = buf.split('\n'); buf = lines.pop();
              for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const raw = line.slice(6).trim();
                if (raw === '[DONE]') break;
                try {
                  const evt = JSON.parse(raw);
                  if (evt.type === 'partial_text' && evt.text?.trim()) {
                    partialTexts.push(evt.text.trim());
                  }
                  if (evt.type === 'tool_call') {
                    streamEvts.push({
                      _sse: true, type: 'tool_call',
                      tool: evt.tool, label: evt.label || evt.tool,
                      thought: evt.thought || '', input: evt.input || {},
                    });
                  }
                  if (evt.type === 'tool_result') {
                    streamEvts.push({ _sse: true, type: 'tool_result', tool: evt.tool, decision: evt.decision || '', output: evt.output || {} });
                    if (evt.tool === 'find_providers' && evt.output?.providers?.length > 0) {
                      agentProviders = evt.output.providers.map(p => ({
                        ...p,
                        name: p.name || 'Unknown Provider',
                        status: p.status || (p.in_network ? 'in-network' : 'out-of-network'),
                        specialty: p.specialty || '',
                        address: typeof p.address === 'object'
                          ? `${p.address.line}, ${p.address.city}, ${p.address.state}`
                          : (p.address || ''),
                        distance: p.distance_miles ? `${p.distance_miles} mi` : '',
                        consultation: p.consultation || '',
                      }));
                    }
                  }
                  if (evt.type === 'final') {
                    const r = evt.response;
                    agentText = r.explanation || r.message || r.question || '';
                    if (!agentText && partialTexts.length > 0) agentText = partialTexts.join(' ');
                    if (r.type === 'provider_results' && r.providers?.length > 0) {
                      agentProviders = r.providers.map(p => ({
                        ...p,
                        name: p.name || 'Unknown Provider',
                        status: p.status || (p.in_network ? 'in-network' : 'out-of-network'),
                        specialty: p.specialty || '',
                        address: typeof p.address === 'object'
                          ? `${p.address.line}, ${p.address.city}, ${p.address.state}`
                          : (p.address || ''),
                        distance: p.distance_miles ? `${p.distance_miles} mi` : '',
                        consultation: p.consultation || '',
                      }));
                    }
                  }
                } catch (_) {}
              }
            }
            // Replace loading bubble with final response
            setMessages(prev => [
              ...prev.filter(m => m.id !== loadingId),
              ...(agentText ? [{
                id: Date.now() + 2, role: 'assistant', text: agentText,
                providers: agentProviders, slots: [], booking: null,
                agentEvents: streamEvts, rankedList: agentProviders,
              }] : []),
            ]);
          }
        } catch (_) {
          setMessages(prev => prev.filter(m => m.id !== loadingId));
        }
        // No setLoading(false) — we never called setLoading(true) for location change
      }
    } else if (!isNowTravel && wasTravel) {
      setMessages(prev => [...prev, {
        id: Date.now(), role: 'system-note',
        text: `🏠 Back to your home location: ${homeCity}.`,
        providers: [], slots: [], booking: null,
      }]);
    }
  };

  const locValue = travelCity ? `${travelCity}|${travelState}` : `${homeCity}|${homeState}`;
  const isTravel = travelCity && travelCity !== homeCity;

  return (
    <div style={{
      flexShrink: 0,
      borderTop: '2px solid #e0e7ff',
      background: '#f8faff',
      padding: '14px 14px 12px',
      display: 'flex',
      flexDirection: 'column',
      gap: 10,
    }}>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{
          fontSize: 10, fontWeight: 700, color: '#497ec9',
          textTransform: 'uppercase', letterSpacing: 1,
        }}>Context Controls</span>
        <span style={{
          width: 6, height: 6, borderRadius: '50%',
          background: isTravel ? '#22c55e' : '#cbd5e1',
          display: 'inline-block',
          boxShadow: isTravel ? '0 0 0 3px rgba(34,197,94,0.2)' : 'none',
          transition: 'background 0.3s, box-shadow 0.3s',
        }} />
      </div>

      {/* Location row */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <label style={{ fontSize: 11, fontWeight: 600, color: '#1e1e5c', display: 'flex', alignItems: 'center', gap: 4 }}>
          <span>📍</span> Location
          {isTravel && (
            <span style={{
              marginLeft: 4, fontSize: 10, fontWeight: 700,
              background: '#dcfce7', color: '#166534',
              border: '1px solid #bbf7d0', borderRadius: 999,
              padding: '1px 7px',
              animation: 'cc-fadein 0.3s ease',
            }}>✈ Traveling</span>
          )}
        </label>
        <div style={{ position: 'relative' }}>
          <select
            style={{
              ...selBase,
              borderColor: locHover ? '#2D308D' : (isTravel ? '#22c55e' : '#e2e8f0'),
              boxShadow: locHover ? '0 0 0 3px rgba(45,48,141,0.12)' : selBase.boxShadow,
            }}
            value={locValue}
            onChange={e => onLocationChange(e.target.value)}
            onMouseEnter={() => setLocHover(true)}
            onMouseLeave={() => setLocHover(false)}
          >
            {LOCATION_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          <span style={{
            position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)',
            color: '#497ec9', fontSize: 9, pointerEvents: 'none',
          }}>▼</span>
        </div>
        {isTravel && (
          <div style={{
            fontSize: 10, color: '#475569',
            display: 'flex', alignItems: 'center', gap: 4,
            animation: 'cc-fadein 0.3s ease',
          }}>
            <span style={{ color: '#94a3b8' }}>🏠 Home:</span> {homeCity}
          </div>
        )}
      </div>

      <style>{`
        @keyframes cc-fadein {
          from { opacity: 0; transform: translateY(-4px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}

// ── Profile Sidebar ───────────────────────────────────────────────────────────

function ProfileSidebar({ member, currentPlan }) {
  const initials = member
    ? `${member.first_name?.[0] || ''}${member.last_name?.[0] || ''}`.toUpperCase()
    : '?';

  const displayPlan = currentPlan || member?.insurance_plan;

  const rows = member ? [
    { label: 'ID', value: member.member_id },
    { label: 'DOB', value: member.date_of_birth },
    { label: 'Address', value: `${member.address}, ${member.city}, ${member.state} ${member.zip}` },
    { label: 'Plan', value: displayPlan },
    { label: 'Since', value: member.member_since },
  ] : [];

  return (
    <div className="profile-sidebar">
      <div className="profile-header">Member Profile</div>
      <div className="profile-avatar">
        <div className="avatar-circle">{initials}</div>
        <div style={{ fontWeight: 700, fontSize: 15, color: '#000048', marginTop: 4 }}>
          {member?.first_name} {member?.last_name}
        </div>
        <div className="status-badge">● Active</div>
      </div>
      <div className="profile-info">
        {rows.map(r => (
          <div className="profile-info-row" key={r.label}>
            <span className="profile-info-label">{r.label}</span>
            <span className="profile-info-value">{r.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Appointments Sidebar ─────────────────────────────────────────────────────

// ── Main Component ────────────────────────────────────────────────────────────

export default function AgenticMemberPortalDemo({ onLogout }) {
  const navigate = useNavigate();
  const member = JSON.parse(sessionStorage.getItem('member') || 'null');

  if (!member) {
    navigate('/login');
    return null;
  }

  const location = useLocation();
  const query = new URLSearchParams(location.search);
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(query.get('open') === 'appointments');
  const initialActivityTab = query.get('tab') || 'activity';

  // Pick up location set from landing page navbar dropdown
  const _lpCity    = sessionStorage.getItem('lp_travel_city')  || '';
  const _lpState   = sessionStorage.getItem('lp_travel_state') || '';

  const [travelCity, setTravelCity] = useState(_lpCity || member?.travel_city || '');
  const [travelState, setTravelState] = useState(_lpState || member?.travel_state || '');
  const homeCity = member?.city || '';
  const homeState = member?.state || '';
  const [currentPlan, setCurrentPlan] = useState(member?.insurance_plan || '');

  const handleLogout = async () => {
    try {
      await fetch('/logout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: member?.member_id }),
      });
    } catch (_) { }
    sessionStorage.removeItem('member');
    sessionStorage.removeItem('sessionId');
    if (onLogout) onLogout();
    navigate('/login');
  };

  const [messages, setMessages] = useState([]);
  const welcomeInitedRef = useRef(false);
  useEffect(() => {
    if (welcomeInitedRef.current) return;
    welcomeInitedRef.current = true;

    // ── Real agent opening — replaces the hardcoded "Welcome back!" string.
    // We call __session_start__ immediately on login. The agent reads the member's
    // full file, runs any pending tools (referral approved → find_providers +
    // check_availability, MRI → notify_provider, etc.) and the first message James
    // sees is the agent's actual proactive response — not a generic greeting.
    const initWelcome = async () => {
      // Seed the snapshot baseline so the first real message can detect changes
      try {
        const snapRes = await fetch(`/dashboard/member/${member.member_id}/state-snapshot`);
        if (snapRes.ok) lastSnapshotRef.current = await snapRes.json();
      } catch (_) {}

      setMessages([{ id: 'loading', role: 'assistant', text: '...', providers: [], slots: [], booking: null, isLoading: true }]);

      // Check if payer approved a plan change — use __plan_change_greeting__ for richer proactive flow
      const planChangeDetected = sessionStorage.getItem('plan_change_detected') === '1';
      sessionStorage.removeItem('plan_change_detected');

      // Landing page location change — consume flags here so they fire once
      const lpLocationChanged = sessionStorage.getItem('lp_location_changed') === '1';
      sessionStorage.removeItem('lp_location_changed');
      sessionStorage.removeItem('lp_travel_city');
      sessionStorage.removeItem('lp_travel_state');

      const triggerMessage = planChangeDetected
        ? '__plan_change_greeting__'
        : lpLocationChanged
        ? '__location_change__'
        : '__session_start__';

      // Use travel city from landing page if location was changed there
      const initTravelCity  = lpLocationChanged ? (travelCity  || '') : (member.travel_city  || '');
      const initTravelState = lpLocationChanged ? (travelState || '') : (member.travel_state || '');

      try {
        const res = await fetch('/chat/stream', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message: triggerMessage,
            user_id: member.member_id,
            travel_city: initTravelCity,
            travel_state: initTravelState,
          }),
        });

        if (!res.ok) throw new Error('stream failed');

        const reader = res.body.getReader();
        const dec = new TextDecoder();
        let buf = '';
        let finalResponse = null;
        let providers = [], referralGate = false;
        const streamEvents = [];

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          const lines = buf.split('\n'); buf = lines.pop();
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const raw = line.slice(6).trim();
            if (raw === '[DONE]') break;
            let evt;
            try { evt = JSON.parse(raw); } catch { continue; }

            if (evt.type === 'tool_call') {
              streamEvents.push({
                author: 'HealthcareProviderSearchAgent',
                content: { parts: [{ functionCall: { name: evt.tool, args: evt.input || {} } }] },
              });
            }
            if (evt.type === 'tool_result' && evt.tool === 'find_providers' && evt.output?.providers?.length > 0) {
              if (evt.output.referral_gate) referralGate = true;
              providers = evt.output.providers.map(p => ({
                ...p,
                name: p.name || 'Unknown Provider',
                status: p.status || (p.in_network ? 'in-network' : 'out-of-network'),
                specialty: p.specialty || '',
                address: typeof p.address === 'object'
                  ? `${p.address.line}, ${p.address.city}, ${p.address.state}`
                  : (p.address || ''),
                distance: p.distance_miles ? `${p.distance_miles} mi` : '',
                consultation: p.consultation || '',
              }));
            }
            if (evt.type === 'final') {
              finalResponse = evt.response;
              // Only refresh prior auth if session start involved tool calls (e.g. notify_provider)
              const hadTools = streamEvents.length > 0;
              if (hadTools && member?.member_id) {
                fetch(`/dashboard/member/${member.member_id}`)
                  .then(r => r.ok ? r.json() : null)
                  .then(data => {
                    if (!data) return;
                    if (data?.prior_auth?.status) setPriorAuthStatus(data.prior_auth.status);
                    // Refresh plan in sidebar — picks up payer-approved plan changes
                    if (data?.plan && data.plan !== currentPlan) {
                      setCurrentPlan(data.plan);
                      const stored = JSON.parse(sessionStorage.getItem('member') || 'null');
                      if (stored) { stored.insurance_plan = data.plan; sessionStorage.setItem('member', JSON.stringify(stored)); }
                    }
                  })
                  .catch(() => {});
              }
            }
          }
        }

        const text = finalResponse
          ? (finalResponse.explanation || finalResponse.message || finalResponse.question || '')
          : `Hey ${member?.first_name || 'there'} — good to see you! What can I help you with today?`;

        if (finalResponse?.type === 'provider_results' && finalResponse.providers?.length > 0) {
          providers = finalResponse.providers.map(p => ({
            ...p,
            name: p.name || 'Unknown Provider',
            status: p.status || (p.in_network ? 'in-network' : 'out-of-network'),
            specialty: p.specialty || '',
            address: p.address || '',
            distance: p.distance_miles ? `${p.distance_miles} mi` : '',
            _agentDate: p._agentDate || null,
          }));
        }

        setMessages([{
          id: Date.now(),
          role: 'assistant',
          text,
          providers,
          slots: [],
          booking: null,
          agentEvents: streamEvents,
          rankedList: providers,
          referralGate,
        }]);

      } catch (_) {
        const fallback = `Hey ${member?.first_name || 'there'} — I'm here whenever you're ready. What can I help you with?`;
        setMessages([{ id: 1, role: 'assistant', text: fallback, providers: [], slots: [], booking: null }]);
      }
    };

    initWelcome();
  }, []);
const [input, setInput] = useState('');
const [loading, setLoading] = useState(false);
const [sessionId, setSessionId] = useState(null);
const [userId] = useState(() => member?.member_id || 'user_' + Math.random().toString(36).slice(2, 8));
const [lastInput, setLastInput] = useState('');
const [agentEvents, setAgentEvents] = useState([]);
// ── MRI / Prior Auth state — drives ProviderGrid booking lock ────────────────
const [priorAuthStatus, setPriorAuthStatus] = useState('none'); // 'none' | 'pending' | 'approved'
const [mriPrescribed, setMriPrescribed] = useState(false);
const mriState = priorAuthStatus === 'pending' ? 'prior_auth_pending'
               : priorAuthStatus === 'none'    ? 'prior_auth_none'
               : 'ok';
const priorAuthPending = priorAuthStatus === 'pending' || priorAuthStatus === 'none';

// Preferred provider state + offer banner
const [preference, setPreference] = useState(null);
const [preferredOffer, setPreferredOffer] = useState(null);

// Fetch prior auth status + latest plan whenever member changes (picks up payer-approved plan changes)
useEffect(() => {
  if (!member?.member_id) return;
  fetch(`/dashboard/member/${member.member_id}`)
    .then(r => r.ok ? r.json() : null)
    .then(data => {
      if (!data) return;
        const status = data?.prior_auth?.status || 'none';
        setPriorAuthStatus(status);

        // Track if MRI is prescribed
        const rx = data?.mri_rx;
        const isPrescribed = !!(rx?.prescription_mri || rx?.body_part || rx?.procedure);
        setMriPrescribed(isPrescribed);

        // Surface any stored preferred imaging provider
        setPreference((data?.preferences && data.preferences.preferred_imaging_provider) || null);
      // Update plan from server — reflects payer-approved plan changes
      if (data?.plan && data.plan !== currentPlan) {
        setCurrentPlan(data.plan);
        // Sync sessionStorage so ProfileSidebar reflects the updated plan immediately
        const stored = JSON.parse(sessionStorage.getItem('member') || 'null');
        if (stored) {
          stored.insurance_plan = data.plan;
          sessionStorage.setItem('member', JSON.stringify(stored));
        }
      }
    })
    .catch(() => {});
}, [member?.member_id]);


// When prior auth becomes approved and we have a saved preference, fetch an offer
useEffect(() => {
  if (!member?.member_id) return;
  if (priorAuthStatus !== 'approved') return;
  if (!preference) return;
  const flag = sessionStorage.getItem(`preferred_booking_offered_${member.member_id}`);
  if (flag === '1') return; // already offered this session

  (async () => {
    try {
      const res = await fetch(`/dashboard/member/${member.member_id}/preferred-booking-offer`);
      if (!res.ok) return;
      const data = await res.json();
      if (data?.can_book) {
        setPreferredOffer(data);
        sessionStorage.setItem(`preferred_booking_offered_${member.member_id}`, '1');
      }
    } catch (_) { }
  })();
}, [priorAuthStatus, preference, member?.member_id]);
const bottomRef = useRef(null);
const inputRef = useRef(null);
const chatRef = useRef(null);
const abortControllerRef = useRef(null);
const [showScrollBtn, setShowScrollBtn] = useState(false);
const animQueueRef = useRef(Promise.resolve()); // serial animation queue
const partialCountRef = useRef(0);
const pendingBookingSpecialtyRef = useRef(''); // stash specialty from ProviderModal until booking confirms



// useEffect(() => {
//   bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
// }, [messages, loading]);

const userMsgRef = useRef(null);
const [lastUserMsgId, setLastUserMsgId] = useState(null);

// Scroll to user's message when they send
useEffect(() => {
  if (lastUserMsgId && userMsgRef.current) {
    userMsgRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}, [lastUserMsgId]);

// Scroll to bottom only when response finishes AND user is near bottom
useEffect(() => {
  if (!loading) {
    const el = chatRef.current;
    if (!el) return;
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distFromBottom < 200) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }
}, [loading]);


useEffect(() => {
  const el = chatRef.current;
  if (!el) return;
  const onScroll = () => {
    setShowScrollBtn(el.scrollHeight - el.scrollTop - el.clientHeight > 80);
  };
  el.addEventListener('scroll', onScroll);
  return () => el.removeEventListener('scroll', onScroll);
}, []);

useEffect(() => {
  // Session creation and context injection is handled entirely by the backend
  // via the __session_start__ message in /chat/stream. Do NOT call /adk/apps/sessions
  // or /adk/run directly here — it creates duplicate sessions (+15s latency each).
  if (false) {
    const createSession = async () => {
    try {
      const res = await fetch(`/adk/apps/${APP_NAME}/users/${userId}/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(member && { 'X-Member-ID': member.member_id }) },
        body: JSON.stringify({}),
      });
      const data = await res.json();
      const newSessionId = data.id;
      setSessionId(newSessionId);
      sessionStorage.setItem('sessionId', newSessionId);

      // Inject member context into agent session
      if (member?.member_id) {
        try {
          const apptRes = await fetch(`/appointments/${member.member_id}`);
          const apptData = await apptRes.json();
          const appts = apptData.appointments || [];
          const now = new Date(); now.setHours(0, 0, 0, 0);
          const parseApptDate = (s) => {
            if (!s) return null;
            const d = new Date(s.replace(/^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s*/i, ''));
            return isNaN(d) ? null : d;
          };
          const pastAppts = appts.filter(a => { const d = parseApptDate(a.date); return d && d < now; });
          const upcomingAppts = appts.filter(a => { const d = parseApptDate(a.date); return !d || d >= now; });
          const formatAppt = (a) =>
            `- ${a.provider} on ${a.date}${a.time ? ' at ' + a.time : ''}${a.address ? ', at ' + a.address : ''}${a.consultation_type ? ' (' + a.consultation_type + ')' : ''}${a.reason ? ' — reason: ' + a.reason : ''}${a.plan_at_booking ? ' | Plan at booking: ' + a.plan_at_booking : ''}`;
          const pastSummary = pastAppts.map(formatAppt).join('\n');
          const upcomingSummary = upcomingAppts.map(formatAppt).join('\n');

          const planChangedDoctors = pastAppts.filter(
            a => a.plan_at_booking && a.plan_at_booking.trim().toLowerCase() !== member.insurance_plan.trim().toLowerCase()
          );
          const planChangeAlert = planChangedDoctors.length > 0
            ? `\n\nPLAN CHANGE ALERT — CRITICAL:\nThe following doctors were booked under a DIFFERENT plan than the member's current plan:\n${planChangedDoctors.map(a => `  - ${a.provider} | booked under: "${a.plan_at_booking}" | CURRENT plan: "${member.insurance_plan}" → this doctor may now be OUT-OF-NETWORK`).join('\n')}\nIF the member asks to revisit or rebook ANY of these doctors, you MUST apply Rule 18 ON THE VERY FIRST RESPONSE: show the plan-change cost warning AND the best in-network alternative in the same message. Do NOT show a provider card first.`
            : '';

          const contextMsg = `[SYSTEM CONTEXT — do not show this to the user]
MEMBER USER ID: ${member.member_id} — always pass this as user_id to ALL tool calls. Never ask the user for their ID.

This member's OFFICIAL appointment history from the Medilife system (use this as the single source of truth):

COMPLETED (PAST) APPOINTMENTS — the member has already attended these:
${pastSummary || '(none)'}

UPCOMING APPOINTMENTS — the member has NOT yet attended these:
${upcomingSummary || '(none)'}

CURRENT INSURANCE PLAN: ${member.insurance_plan}${planChangeAlert}${(() => {
            const currentLoc = member.current_location;
            if (!currentLoc) return '';
            const homeCityLower = (member.city || '').toLowerCase();
            const currentCityLower = (currentLoc.city || '').toLowerCase();
            if (currentCityLower === homeCityLower) return '';
            const affected = upcomingAppts.filter(a => a.consultation_type === 'In-Person' && a.address);
            if (affected.length === 0) return '';
            const lines = affected.map(a => '  - ' + a.provider + ' | ' + a.date + ' at ' + a.time + ' | In-Person | ' + a.address).join('\n');
            return '\n\nLOCATION MISMATCH ALERT — CRITICAL:\nMember home: ' + member.city + ', ' + member.state + ' | Current location: ' + currentLoc.city + ', ' + currentLoc.state + '\nThe following UPCOMING IN-PERSON appointments are at the home location and may be unreachable:\n' + lines + '\nApply Rule 19 on the FIRST response: call lookup_provider_by_name for the affected provider, check Telehealth availability, offer conversion, notify provider, fetch Telehealth slots.';
          })()}

IMPORTANT RULES:
- When the member says their previous issue is unresolved or asks about a past visit, refer ONLY to COMPLETED appointments.
- NEVER treat an upcoming appointment as something the member has already experienced.
- If the member describes symptoms related to a past completed appointment, proactively reference that visit and ask if it is a follow-up or a new concern.
- Do not reference any doctor names or appointments not listed above.
- PLAN CHANGE DETECTION: If the member asks to revisit or rebook a doctor from COMPLETED APPOINTMENTS, check if that doctor is still in-network under the CURRENT INSURANCE PLAN above. If the plan has changed and the doctor is now out-of-network, follow Rule 18 (plan-change aware provider lookup) — show cost warning + best in-network alternative FIRST, before any provider card.`;
          await fetch('/adk/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...(member && { 'X-Member-ID': member.member_id }) },
            body: JSON.stringify({
              app_name: APP_NAME,
              user_id: userId,
              session_id: newSessionId,
              new_message: { role: 'user', parts: [{ text: contextMsg }] },
            }),
          });
        } catch (_) { }
      }
    } catch (err) {
      console.error('Session creation failed:', err);
    }
  };
  createSession();
  } // end if(false) — disabled block
}, [userId]);

// Auto location detection — fires once after session is ready
const locationInjectedRef = useRef(false);
const lastSnapshotRef = useRef(null); // { _hash, ...state } — for mid-session change detection
useEffect(() => {
  if (!sessionId || !member) return;
  if (locationInjectedRef.current) return;
  const loc = member.current_location;
  if (!loc) return;
  if (loc.city.toLowerCase() === (member.city || '').toLowerCase()) return;
  locationInjectedRef.current = true;

  const locationMsg =
    `[SYSTEM CONTEXT — do not show this to the user]\n` +
    `The member's home location on file is: ${member.city}, ${member.state}.\n` +
    `Their CURRENT location is: ${loc.city}, ${loc.state} (zip: ${loc.zip}).\n` +
    `The member is currently traveling or has relocated.\n` +
    `IMPORTANT RULES going forward:\n` +
    `1. When the member next asks for a provider or doctor, acknowledge naturally: "I can see you're currently in ${loc.city}, ${loc.state} — that's different from your home in ${member.city}. Let me find the best providers near your current location!"\n` +
    `2. Search ALL providers in ${loc.city}, ${loc.state} — NOT in ${member.city}.\n` +
    `3. Use zip code ${loc.zip} for all distance calculations.\n` +
    `4. Say this acknowledgement ONLY ONCE on the next provider request — do not repeat it.`;

  // Location change is handled by the backend via __location_change__ in /chat/stream.
  // Direct /adk/run calls created duplicate LLM round-trips (24-27s each). Disabled.
  // injectLocation was here — removed. Backend handles it via sendMessage('__location_change__').
  sendMessage('__location_change__').catch(() => {});

  setMessages(prev => [...prev, {
    id: Date.now(),
    role: 'system-note',
    text: `📍 You're currently in ${loc.city}, ${loc.state} — different from your home in ${member.city}. Providers will be searched near your current location.`,
    providers: [], slots: [], booking: null,
  }]);
}, [sessionId]);

// // After the createSession useEffect, add:
//   useEffect(() => {
//     if (!member) return;
//     fetch(`/memory/${member.member_id}`)
//       .then(r => r.json())
//       .then(mem => {
//         if (mem.has_history) {
//           const specialties = mem.specialties_searched?.slice(0, 2).join(', ');
//           const welcomeBack = specialties
//             ? `Welcome back, ${member.first_name}! I see you've been looking into ${specialties} care before. How can I help you today?`
//             : `Welcome back, ${member.first_name}! Great to see you again. How can I help you today?`;
//           setMessages([{ id: 1, role: 'assistant', text: welcomeBack, providers: [], slots: [], booking: null }]);
//         }
//       })
//       .catch(() => {}); // silently fail if no memory yet
//   }, []);


const stopGeneration = () => {
  if (abortControllerRef.current) {
    abortControllerRef.current.abort();
    abortControllerRef.current = null;
  }
  setLoading(false);
  setTimeout(() => inputRef.current?.focus(), 50);
};

const sendMessage = async (content, silent = false) => {
  const text = content.trim();
  if (!text || loading) return;
  if (!silent) {
    const newId = Date.now();
    setLastUserMsgId(newId);                          // ← track this message
    setMessages(prev => [...prev, { id: newId, role: 'user', text }]);
  }
  // setMessages(prev => [...prev, { id: Date.now(), role: 'user', text }]);}
  setLastInput(text);
  setInput('');
  setLoading(true);
  // Do NOT reset agentEvents — accumulate across the session so the reasoning
  // pane holds the full trace, not just the most recent response.
  animQueueRef.current = Promise.resolve();
  partialCountRef.current = 0;
  abortControllerRef.current = new AbortController();
  const signal = abortControllerRef.current.signal;
  if (inputRef.current) inputRef.current.style.height = '40px';

  try {
    // ── Mid-session state-change detection ──────────────────────────────────
    // Before each message, fetch the lightweight state snapshot for this member.
    // If the hash changed since the last message (e.g. payer just approved prior auth),
    // we prepend a hidden system note so the agent surfaces it proactively.
    let stateUpdateNote = '';
    if (userId) {
      try {
        const snapRes = await fetch(`/dashboard/member/${userId}/state-snapshot`);
        if (snapRes.ok) {
          const snap = await snapRes.json();
          const prev = lastSnapshotRef.current;
          if (prev && prev._hash !== snap._hash) {
            const changes = [];
            if (prev.prior_auth_status !== snap.prior_auth_status)
              changes.push(`PRIOR_AUTH_STATUS_CHANGED: was "${prev.prior_auth_status}", now "${snap.prior_auth_status}"`);
            if (prev.plan_change_decision !== snap.plan_change_decision && snap.plan_change_decision)
              changes.push(`PLAN_CHANGE_DECISION: payer decided "${snap.plan_change_decision}"`);
            if (prev.referral_status !== snap.referral_status && snap.referral_status === 'approved')
              changes.push(`REFERRAL_APPROVED: specialist referral just cleared`);
            if (!prev.pcp_change_pending && snap.pcp_change_pending)
              changes.push(`PCP_CHANGE_PENDING: a new PCP change request is now pending`);
            if (changes.length) {
              stateUpdateNote =
                `[SYSTEM STATE UPDATE — do not reveal this was injected]\n` +
                `The following changed since the member's last message:\n` +
                changes.join('\n') +
                `\nBefore answering the member's question, proactively and naturally address these changes first.`;
            }
            // Sync local prior-auth badge
            if (snap.prior_auth_status) setPriorAuthStatus(snap.prior_auth_status);
          }
          lastSnapshotRef.current = snap;
        }
      } catch (_) { /* non-fatal — proceed without injection */ }
    }

    const res = await fetch('/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: stateUpdateNote ? `${stateUpdateNote}\n\nMEMBER MESSAGE: ${text}` : text,
        user_id: userId,
        travel_city: travelCity,
        travel_state: travelState,
      }),
      signal,
    });

    if (!res.ok) throw new Error(`Server error ${res.status}`);

    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    let finalResponse = null;
    const streamAgentEvents = [];
    const partialIds = [];

        let providers = [], slots = [], booking = null, displayText = '', slotProvider = '', alsoConsidered = null, referralGate = false;
    let lastPartialText = '', accumulatedPartialText = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const raw = line.slice(6).trim();
        if (raw === '[DONE]') break;
        let evt;
        try { evt = JSON.parse(raw); } catch { continue; }

        if (evt.type === 'partial_text' && evt.text?.trim()) {
          lastPartialText = evt.text.trim();
          accumulatedPartialText += evt.text;
        }

        // Direct-bypass paths (plan change, telehealth conversion) emit a
        // 'text' event before the 'final' event. Treat it as the display text
        // so the response is never blank if 'explanation' is missing.
        if (evt.type === 'text' && evt.text?.trim()) {
          displayText = evt.text.trim();
        }

        if (evt.type === 'tool_call') {
          // SSE-style event: pass thought + label so the Reasoning tab can show WHY
          streamAgentEvents.push({
            _sse:    true,
            type:    'tool_call',
            tool:    evt.tool,
            label:   evt.label || evt.tool,
            input:   evt.input || {},
            thought: evt.thought || '',
            author: 'HealthcareProviderSearchAgent',
            content: { parts: [{ functionCall: { name: evt.tool, args: evt.input || {} } }] },
          });
          setAgentEvents(prev => [...prev, streamAgentEvents[streamAgentEvents.length - 1]]);
        }

        if (evt.type === 'tool_result') {
          // Attach decision to the last matching tool_call SSE event
          const lastCall = [...streamAgentEvents].reverse().find(e => e._sse && e.tool === evt.tool && !e._decision_attached);
          if (lastCall) {
            lastCall._decision_attached = true;
          }
          streamAgentEvents.push({
            _sse:     true,
            type:     'tool_result',
            tool:     evt.tool,
            decision: evt.decision || '',
            output:   evt.output || {},
            author: 'HealthcareProviderSearchAgent',
            content: { parts: [{ functionResponse: { name: evt.tool, response: evt.output || {} } }] },
          });
          setAgentEvents(prev => [...prev, streamAgentEvents[streamAgentEvents.length - 1]]);
          if (evt.tool === 'find_providers' && evt.output?.providers?.length > 0) {
            if (evt.output.referral_gate) referralGate = true;
            providers = evt.output.providers.map(p => ({
              ...p,
              name: p.name || 'Unknown Provider',
              status: p.status || (p.in_network ? 'in-network' : 'out-of-network'),
              specialty: p.specialty || '',
              address: typeof p.address === 'object'
                ? `${p.address.line}, ${p.address.city}, ${p.address.state}`
                : (p.address || ''),
              distance: p.distance_miles ? `${p.distance_miles} mi` : '',
              consultation: p.consultation || '',
            }));
          }
        }


        if (evt.type === 'final') {
          finalResponse = evt.response;
          // Refresh prior auth status only after booking or notify_provider tool calls
          // (not on every message — avoids a dashboard fetch on every chat turn)
          const hadBookingOrNotify = streamAgentEvents.some(
            e => e._sse && e.type === 'tool_call' && (e.tool === 'book_appointment' || e.tool === 'notify_provider' || e.tool === 'request_plan_change')
          );
          if (hadBookingOrNotify && member?.member_id) {
            fetch(`/dashboard/member/${member.member_id}`)
              .then(r => r.ok ? r.json() : null)
              .then(data => { if (data?.prior_auth?.status) setPriorAuthStatus(data.prior_auth.status); })
              .catch(() => {});
          }
        }

        if (evt.type === 'error') throw new Error(evt.message);
      }
    }

    if (!finalResponse) return;

    
    if (finalResponse.type === 'provider_results') {
    providers = (finalResponse.providers || []).map(p => ({
      ...p,
      name: p.name || p.practitioner_name || 'Unknown Provider',
      status: p.status || (p.in_network ? 'in-network' : 'out-of-network'),
      specialty: p.specialty || p.primary_specialty || '',
      address: p.address || p.practice_address || '',
      distance: p.distance || (p.distance_km ? `${Number(p.distance_km).toFixed(1)} km` : ''),
      consultation: p.consultation || p.consultation_modes || '',
      _agentDate: p._agentDate || null,
    } ));
      
      displayText = finalResponse.message || '';
      slotProvider = providers[0]?.name || '';
    } else if (finalResponse.type === 'booking_confirmation') {
      const b = finalResponse.booking || {};
      booking = {
        provider: b.provider_name || '',
        date: b.date || '',
        time: b.time_start || '',
        consultation_type: b.consultation_type || '',
        address: b.address || '',
        telehealth_link: b.telehealth_link || '',
        specialty: b.specialty || pendingBookingSpecialtyRef.current || '',
        reason: b.reason || '',
      };
      displayText = finalResponse.message || '';

      let bookingConflictMessage = null;
      if (member?.member_id && booking.date && booking.time) {
        try {
          const existingRes = await fetch(`/appointments/${member.member_id}`);
          if (existingRes.ok) {
            const existingData = await existingRes.json();
            const existingAppts = existingData.appointments || [];
            const conflict = existingAppts.find(a => {
              const existingDate = (a.date || '').trim();
              const existingTime = ((a.time || a.time_start) || '').trim();
              const existingProvider = (a.provider_name || a.provider || '').trim().toLowerCase();
              return existingDate && existingTime &&
                existingDate.toLowerCase() === booking.date.trim().toLowerCase() &&
                existingTime.toLowerCase() === booking.time.trim().toLowerCase() &&
                existingProvider !== booking.provider.trim().toLowerCase();
            });
            if (conflict) {
              bookingConflictMessage = `You already have an appointment with ${conflict.provider_name || conflict.provider} at ${conflict.date} ${conflict.time || conflict.time_start}. Would you like to choose a different time?`;
            }
          }
        } catch (_) {}
      }

      if (!bookingConflictMessage && member?.member_id) {
        // Skip re-saving if this is a telehealth conversion of an existing appointment.
        // The backend already updated the record; re-posting creates a duplicate with
        // a differently formatted date (e.g. "June 09, 2026" vs "June 9, 2026").
        let alreadySaved = false;
        try {
          const existingCheck = await fetch(`/appointments/${member.member_id}`);
          if (existingCheck.ok) {
            const existingCheckData = await existingCheck.json();
            const existingList = existingCheckData.appointments || [];
            // Normalise date strings: remove leading zeros from day ("June 09" → "June 9")
            const normDate = (s) => (s || '').trim().replace(/\s0(\d)\b/, ' $1').toLowerCase();
            const bookingProvider = (booking.provider || '').trim().toLowerCase();
            const bookingDate = normDate(booking.date);
            alreadySaved = existingList.some(a => {
              const aProvider = (a.provider_name || a.provider || '').trim().toLowerCase();
              return aProvider === bookingProvider && normDate(a.date) === bookingDate;
            });
          }
        } catch (_) {}

        if (!alreadySaved) {
          const saveRes = await fetch(`/appointments/${member.member_id}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              provider_name:     booking.provider,
              provider:          booking.provider,
              date:              booking.date,
              time:              booking.time,
              time_start:        booking.time,
              consultation_type: booking.consultation_type,
              address:           booking.address,
              reason:            b.reason || '',
              npi:               b.npi || '',
              specialty:         pendingBookingSpecialtyRef.current,
            }),
          });

          try {
            const saveData = await saveRes.json();
            if (saveData?.success === false && saveData?.message) {
              bookingConflictMessage = saveData.message;
            }
          } catch (_) {}
        }
      }

      if (bookingConflictMessage) {
        displayText = bookingConflictMessage;
        booking = null;
      }
      if (member?.member_id && !bookingConflictMessage) {
        pendingBookingSpecialtyRef.current = '';
      }
    } else if (finalResponse.type === 'emergency') {
      displayText = finalResponse.message || '';
    } else {
      displayText = displayText || finalResponse.explanation || finalResponse.message || finalResponse.question || '';
    }

    // Fallback: if the assistant text contains provider details but no structured
    // provider_results payload was returned, parse providers from the message text
    // so the interactive card can still render.
    if (!providers.length && displayText) {
      const parsed = classifyResponse(displayText).hasProviders ? parseProviders(displayText) : [];
      if (parsed.length > 0) {
        providers = parsed;
        slotProvider = providers[0]?.name || '';
      }
    }

    setMessages(prev => {
      const withoutPartials = prev.filter(m => !partialIds.includes(m.id));
      // Prepend lastPartialText only if the final response's first sentence doesn't already
      // contain the core reasoning. Check if specialty/plan keywords from the partial are
      // absent from the opening sentence of the final response.
      if (lastPartialText && displayText) {
        // If the final text already contains the accumulated partial content, skip prepend.
        const accumulated = accumulatedPartialText.trim();
        const finalLower = displayText.toLowerCase();
        const partialLower = accumulated.toLowerCase();
        // Check overlap: if final starts with partial, or partial is substantially inside final
        const partialWords = partialLower.split(/\s+/).filter(w => w.length > 4);
        const overlapRatio = partialWords.length > 0
          ? partialWords.filter(w => finalLower.includes(w)).length / partialWords.length
          : 1;
        if (overlapRatio < 0.5) {
          displayText = accumulated + ' ' + displayText;
        }
      }
      return [...withoutPartials, { id: Date.now() + 1, role: 'assistant', text: displayText, providers, slots, booking, agentEvents: streamAgentEvents, rankedList: providers, alsoConsidered, slotProvider, referralGate, pro_tip_guide: finalResponse.pro_tip_guide || [] }];
    });

  } catch (err) {
    if (err.name === 'AbortError') {
      // User stopped generation — silently do nothing
    } else {
      setMessages(prev => [...prev, {
        id: Date.now() + 1, role: 'assistant',
        text: `Sorry, something went wrong on my end. Please try again in a moment.`,
        providers: [], slots: [], booking: null,
      }]);
    }
  } finally {
    abortControllerRef.current = null;
    setLoading(false);
    setTimeout(() => inputRef.current?.focus(), 50);
  }
};

const handleKeyDown = (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(input); }
};

return (
  <div className="app">
    {/* ── Header ── */}
    <header className="app-header">
      <div className="header-left">
        <div className="logo"><img src="/src/assets/cognizant-logo.png" alt="Logo" className="logo-img" /></div>
      </div>
      <div className="header-center"><h1>Agentic Member Portal</h1></div>
      <div className="header-right">
        {member && (
          <div className="member-info">
            <span className="member-name">{member.first_name} {member.last_name}</span>
            {/* <span className="member-plan-badge">{member.insurance_plan}</span> */}
          </div>
        )}
        {/* <div className="header-status">
            <span className="status-dot" />
            <span className="status-label">Live</span>
          </div> */}
        <button className="logout-btn" onClick={handleLogout}>Logout</button>
      </div>
    </header>

    {/* ── Body ── */}
    <main className="main-content">

      {/* LEFT PANE */}
      <div className={`left-zone ${leftOpen ? 'pane-open' : 'pane-closed'}`}>
        {leftOpen && <ProfileSidebar member={member} currentPlan={currentPlan} />}
        <button
          className="sidebar-toggle left-toggle"
          onClick={() => setLeftOpen(o => !o)}
          title={leftOpen ? 'Collapse profile' : 'Expand profile'}
        >
          {leftOpen ? '◀' : '▶'}
        </button>
      </div>

      {/* CENTER — CHAT */}
      <section className="center-zone">
        <div className="chat-panel-agent">
          <div className="chat-header">
            <div className="chat-header-inner">
              <div className="chat-title-group">
                <div className="chat-avatar-sm">A</div>
                <div>
                  <h2 className="chat-title">Provider Search Assistant</h2>
                  <p className="chat-subtitle">Find doctors · Book appointments</p>
                </div>
              </div>

            </div>
          </div>

          <div className="chat-messages" ref={chatRef}>
            {messages.map((msg) => (
              <div key={msg.id} ref={msg.id === lastUserMsgId ? userMsgRef : null} className={`message-row ${msg.role === 'system-note' ? 'system-note' : msg.role}`}>
                {msg.role === 'assistant' && <div className="bot-avatar">A</div>}
                <div className="message-content-wrap">
                  {msg.role === 'system-note' ? (
                    <div style={{
                      fontSize: '12px',
                      color: '#6b7280',
                      background: '#f3f4f6',
                      border: '1px solid #e5e7eb',
                      borderRadius: '8px',
                      padding: '6px 12px',
                      margin: '4px 0',
                      display: 'inline-block',
                      fontStyle: 'italic'
                    }}>
                      {msg.text}
                    </div>
                  ) : (
                    msg.text && (
                      (msg.isLoading) ? (
                        // Session-start loading — typing dots animation
                        <div style={{
                          display: 'flex', alignItems: 'center', gap: 5,
                          padding: '12px 18px',
                          background: '#eef2ff',
                          border: '1.5px solid #c7d2fe',
                          borderRadius: 14,
                          maxWidth: 120,
                        }}>
                          {[0,1,2].map(i => (
                            <span key={i} style={{
                              width: 8, height: 8, borderRadius: '50%',
                              background: '#4f46e5',
                              animation: `typing-dot 1.2s ease-in-out ${i * 0.2}s infinite`,
                              display: 'inline-block',
                            }} />
                          ))}
                          <style>{`@keyframes typing-dot { 0%,80%,100%{transform:scale(0.6);opacity:0.4} 40%{transform:scale(1);opacity:1} }`}</style>
                        </div>
                      ) : msg.isThinking ? (
                        // Live thinking indicator — updates in place, removed when final response arrives
                        <div style={{
                          display: 'inline-flex', alignItems: 'center', gap: 8,
                          padding: '7px 14px',
                          background: '#f1f5f9',
                          border: '1px solid #e2e8f0',
                          borderRadius: 20,
                          maxWidth: '80%',
                        }}>
                          <span style={{ fontSize: 12, animation: 'spin 1.5s linear infinite', display: 'inline-block' }}>⚙️</span>
                          <span style={{ fontSize: 12, color: '#475569', fontStyle: 'italic', lineHeight: 1.4 }}>
                            {msg.text}
                          </span>
                        </div>
                      ) : msg.isPartial ? (
                        <MessageBubble message={msg.text} isUser={false} showRead={false} hideSuggestions={true} />
                      ) : (
                        <MessageBubble message={msg.text} isUser={msg.role === 'user'} showRead={false} onSuggestion={msg.role === 'assistant' ? (s) => sendMessage(s) : undefined} hideSuggestions={msg.role === 'assistant' && (msg.providers?.length > 0 || !!msg.booking)} context={messages.slice(0, messages.indexOf(msg)).map(m => m.text || '').join(' ')} />
                      )
                    )
                  )}


                  {msg.providers?.length > 0 && <ProviderGrid providers={msg.providers} rankedList={msg.rankedList} mriState={mriState} mriPrescribed={mriPrescribed} priorAuthPending={priorAuthPending} referralGate={msg.referralGate} preference={preference} onBook={(backendMsg, displayMsg, bookingMeta) => {
                    if (displayMsg) setMessages(prev => [...prev, {
                      id: Date.now(),
                      role: 'system-note',
                      text: displayMsg,
                      providers: [], slots: [], booking: null
                    }]);
                    // stash specialty so the appointment save can include it
                    if (bookingMeta?.specialty) pendingBookingSpecialtyRef.current = bookingMeta.specialty;
                    // Persist preferred imaging provider if provided (MRI only)
                    try {
                      const IMAGING_SPECIALTIES = ['radiology', 'diagnostic radiology', 'imaging', 'nuclear medicine', 'mri', 'ct'];
                      const isImaging = IMAGING_SPECIALTIES.some(kw =>
                        (bookingMeta?.specialty || '').toLowerCase().includes(kw) ||
                        (bookingMeta?.provider_name || '').toLowerCase().includes(kw)
                      );
                      if (isImaging && mriPrescribed && bookingMeta?.provider_name && member?.member_id) {
                        fetch(`/dashboard/member/${member.member_id}/preference`, {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({
                            provider_name: bookingMeta.provider_name,
                            npi: bookingMeta.npi,
                            address: bookingMeta.address,
                            city: bookingMeta.city,
                            specialty: bookingMeta.specialty || ''
                          })
                        }).catch(() => { });
                      }
                    } catch (_) { }
                    sendMessage(backendMsg, true);
                  }} />}

                  {msg.pro_tip_guide && msg.pro_tip_guide.length > 0 && (
                    <ProTipGuide tips={msg.pro_tip_guide} />
                  )}

                  {msg.booking && <BookingConfirmation booking={msg.booking} />}

                  {msg.role === 'assistant' && msg.agentEvents?.length > 0 && (
                    <AgentReasoningDropdown events={msg.agentEvents} alsoConsidered={msg.alsoConsidered} />
                  )}

                  {msg.role === 'assistant' && (msg.providers?.length > 0 || !!msg.booking) && (() => {
                    const suggestions = extractSuggestions(msg.text || '');
                    if (!suggestions.length) return null;
                    return (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '6px', justifyContent: 'flex-end', alignSelf: 'flex-end', marginRight: '10px' }}>
                        {suggestions.map((s, i) => (
                          <button key={i} onClick={() => sendMessage(s.message)}
                            style={{ padding: '7px 14px', background: '#ffffff', border: '1.5px solid #2D308D', borderRadius: '20px', color: '#2D308D', fontSize: '13px', fontWeight: 600, cursor: 'pointer', transition: 'all 0.2s' }}
                            onMouseEnter={e => e.currentTarget.style.background = '#eef2ff'}
                            onMouseLeave={e => e.currentTarget.style.background = '#ffffff'}
                          >{s.label}</button>
                        ))}
                      </div>
                    );
                  })()}
                </div>
              </div>
            ))}
            {loading && (
              <div className="message-row assistant">
                <div className="bot-avatar">A</div>
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 5,
                  padding: '12px 18px',
                  background: '#eef2ff',
                  border: '1.5px solid #c7d2fe',
                  borderRadius: 14,
                  maxWidth: 120,
                }}>
                  {[0,1,2].map(i => (
                    <span key={i} style={{
                      width: 8, height: 8, borderRadius: '50%',
                      background: '#4f46e5',
                      animation: `typing-dot 1.2s ease-in-out ${i * 0.2}s infinite`,
                      display: 'inline-block',
                    }} />
                  ))}
                  <style>{`@keyframes typing-dot { 0%,80%,100%{transform:scale(0.6);opacity:0.4} 40%{transform:scale(1);opacity:1} }`}</style>
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {showScrollBtn && (
            <button className="jump-to-bottom-btn" onClick={() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' })}><FaArrowDown size={14} /></button>
          )}

          <div className="input-bar">
            <div className="input-wrapper">
              <textarea
                ref={inputRef}
                className="chat-input"
                placeholder="Describe your symptoms or ask about a doctor…"
                value={input}
                autoFocus
                onChange={(e) => {
                  setInput(e.target.value);
                  e.target.style.height = 'auto';
                  e.target.style.height = Math.min(e.target.scrollHeight, 160) + 'px';
                }}
                onKeyDown={handleKeyDown}
                rows={1}
              />
              <div className="input-actions">
                {loading ? (
                  <button
                    className="send-btn"
                    onClick={stopGeneration}
                    title="Stop generating"
                  >■</button>
                ) : (
                  <button className="send-btn" onClick={() => sendMessage(input)} disabled={!input.trim() || loading} title="Send">➤</button>
                )}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* RIGHT PANE */}
      <div className={`right-zone ${rightOpen ? 'pane-open' : 'pane-closed'}`}>
        <button
          className="sidebar-toggle right-toggle"
          onClick={() => setRightOpen(o => !o)}
          title={rightOpen ? 'Collapse panel' : 'Expand panel'}
        >
          {rightOpen ? '▶' : '◀'}
        </button>
        {rightOpen && (
          <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
            <div style={{ flex: 1, overflow: 'hidden', minHeight: 0 }}>
              <AgentActivityPane events={agentEvents} isProcessing={loading} initialTab={initialActivityTab} locationChanged={!!(travelCity && travelCity !== homeCity)} />
            </div>
          </div>
        )}
      </div>

    </main>

    {/* <div style={{ display: 'flex', justifyContent: 'center', padding: '6px 0', background: '#FFFFFF', borderTop: '1px solid #E0E0E0' }}>
      <div style={{
        background: '#fefce8',
        border: '1px solid #fde047',
        borderRadius: '999px',
        padding: '6px 16px',
        fontSize: 12,
        color: '#854d0e',
        display: 'inline-flex',
        alignItems: 'center',
        gap: 8,
      }}>
        <span style={{ fontSize: 14, flexShrink: 0 }}>⚠️</span>
        <span><strong>Disclaimer:</strong> I am an AI assistant, not a medical professional. For emergencies, call 911 immediately.</span>
      </div>
    </div> */}

    <div className="app-footer">© 2026 Medilife Healthcare. All rights reserved.</div>

    {/* Prior auth and plan changes are managed via the Payer Dashboard (/payer) */}
  </div>
);
}








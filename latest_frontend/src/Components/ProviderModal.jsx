import React, { useState } from 'react';
import { FaPhone, FaIdCard, FaVideo } from 'react-icons/fa';
import { FaLocationDot, FaCircleCheck, FaCircleXmark, FaMars, FaVenus } from 'react-icons/fa6';
import { MdLocalHospital } from 'react-icons/md';

const MONTH_NAMES = ['January','February','March','April','May','June','July','August','September','October','November','December'];
const DAY_NAMES = ['Su','Mo','Tu','We','Th','Fr','Sa'];

function getDatesForMonth(year, month) {
  const days = [];
  const total = new Date(year, month + 1, 0).getDate();
  for (let d = 1; d <= total; d++) days.push(new Date(year, month, d));
  return days;
}

function MiniCalendar({ selected, onSelect }) {
  const today = new Date();
  const [view, setView] = useState(() => {
    const d = selected || today;
    return { year: d.getFullYear(), month: d.getMonth() };
  });
  const days = getDatesForMonth(view.year, view.month);
  const firstDay = new Date(view.year, view.month, 1).getDay();

  const isSame = (a, b) => a && b &&
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate();

  const isPast = (d) => { const t = new Date(); t.setHours(0,0,0,0); return d < t; };

  return (
    <div className="pm-calendar">
      <div className="pm-cal-nav">
        <button className="pm-cal-arrow" onClick={() => setView(v => { const d = new Date(v.year, v.month - 1, 1); return { year: d.getFullYear(), month: d.getMonth() }; })}>‹</button>
        <span className="pm-cal-title">{MONTH_NAMES[view.month]} {view.year}</span>
        <button className="pm-cal-arrow" onClick={() => setView(v => { const d = new Date(v.year, v.month + 1, 1); return { year: d.getFullYear(), month: d.getMonth() }; })}>›</button>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, minmax(0, 1fr))', gap: '2px', width: '100%' }}>
        {DAY_NAMES.map(d => (
          <div key={d} style={{ fontSize: 9, fontWeight: 700, color: '#94a3b8', textAlign: 'center', padding: '3px 0', textTransform: 'uppercase' }}>{d}</div>
        ))}
        {Array(firstDay).fill(null).map((_, i) => <div key={'e'+i} />)}
        {days.map(d => (
          <button
            key={d.getDate()}
            onClick={() => !isPast(d) && onSelect(d)}
            disabled={isPast(d)}
            style={{
              width: '100%', aspectRatio: '1',
              border: isSame(d, selected) ? 'none' : '1px solid #e2e8f0',
              borderRadius: 5,
              background: isSame(d, selected) ? '#000048' : 'white',
              color: isSame(d, selected) ? 'white' : isPast(d) ? '#a3a3a7' : '#334155',
              fontSize: 11, fontWeight: isSame(d, selected) ? 700 : 500,
              cursor: isPast(d) ? 'not-allowed' : 'pointer',
              opacity: isPast(d) ? 0.75 : 1,
              transition: 'all 0.15s', padding: 0,
            }}
          >
            {d.getDate()}
          </button>
        ))}
      </div>
    </div>
  );
}

// Convert browser local time (IST on your laptop) to PST for slot cutoff comparison.
// IST = UTC+5:30, PST = UTC-8  →  PST = local - 13h30m
function getBrowserTimeAsPST() {
  const now = new Date();
  const utcMs = now.getTime() + now.getTimezoneOffset() * 60000; // to UTC ms
  const pstMs = utcMs + (-8 * 3600000);                          // UTC → PST
  const pst   = new Date(pstMs);
  return {
    time: `${String(pst.getHours()).padStart(2,'0')}:${String(pst.getMinutes()).padStart(2,'0')}`,
    date: `${pst.getFullYear()}-${String(pst.getMonth()+1).padStart(2,'0')}-${String(pst.getDate()).padStart(2,'0')}`,
  };
}

function SlotSection({ icon, label, slots, selected, onSelect }) {
  if (!slots || slots.length === 0) return null;
  return (
    <div className="pm-slot-section">
      <div className="pm-slot-label">{icon} {label}</div>
      <div className="pm-slots-grid">
        {slots.map((s, i) => {
          const isPast   = s.past || false;
          const isBooked = !isPast && s.booked;
          const isActive = selected === s.time && !s.booked && !isPast;
          return (
            <button
              key={i}
              className={`pm-slot-btn ${isActive ? 'pm-slot-selected' : ''}`}
              onClick={() => !s.booked && !isPast && onSelect(s.time)}
              disabled={s.booked || isPast}
              title={isPast ? 'Time has passed' : isBooked ? 'Already booked' : ''}
              style={
                isPast ? {
                  opacity: 0.35,
                  cursor: 'not-allowed',
                  textDecoration: 'line-through',
                  background: '#f1f5f9',
                  color: '#94a3b8',
                  borderColor: '#e2e8f0',
                } : isBooked ? {
                  opacity: 0.4,
                  cursor: 'not-allowed',
                  textDecoration: 'line-through',
                  background: '#f1f5f9',
                  color: '#94a3b8',
                  borderColor: '#e2e8f0',
                } : {}
              }
            >
              {s.time}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function parseDateSafe(raw) {
  if (!raw) return null;
  if (raw instanceof Date) return raw;
  if (typeof raw === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(raw)) {
    const [y, m, d] = raw.split('-').map(Number);
    return new Date(y, m - 1, d);
  }
  const d = new Date(raw);
  return isNaN(d.getTime()) ? null : d;
}

export default function ProviderModal({ provider, defaultDate, onClose, onBook, mriPrescribed }) {
  const [selectedDate, setSelectedDate] = useState(() => {
    return parseDateSafe(provider?._agentDate) || parseDateSafe(defaultDate) || new Date();
  });
  const [selectedSlot, setSelectedSlot] = useState(null);
  const [selectedMode, setSelectedMode] = useState(null);
  const [realSlots, setRealSlots] = useState(null);
  const [loadingSlots, setLoadingSlots] = useState(false);
  const [savingPref, setSavingPref] = useState(false);
  const [savedMsg, setSavedMsg] = useState(null);

  const IMAGING_SPECIALTIES = ['radiology', 'diagnostic radiology', 'imaging', 'nuclear medicine', 'mri', 'ct'];
  const provSpecialty = (provider.specialty || '').toLowerCase();
  const provName      = (provider.name || '').toLowerCase();
  const isImagingProvider = IMAGING_SPECIALTIES.some(kw => provSpecialty.includes(kw) || provName.includes(kw));
  
  const showSavePreferred = isImagingProvider && mriPrescribed;

  const consultation = provider?.consultation || '';
  const hasInPerson  = !consultation || consultation === 'In-Person' || consultation === 'Both' || consultation.includes('In-Person');
  const hasTelehealth = consultation === 'Telehealth' || consultation === 'Both' || consultation.includes('Telehealth');

  if (!provider) return null;

  // Preference persistence: defer saving until the user actually books

  // Auto-fetch slots for the initial date on mount
  React.useEffect(() => {
    fetchSlots(selectedDate, true);
  }, []);

  const fetchSlots = async (date, isInitial = false) => {
    setLoadingSlots(true);
    setRealSlots(null);
    setSelectedSlot(null);
    setSelectedMode(null);
    try {
      const now        = new Date();
      const hh         = String(now.getHours()).padStart(2, '0');
      const mm         = String(now.getMinutes()).padStart(2, '0');
      const clientTime = `${hh}:${mm}`;
      const clientDate = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;
      const selDate    = `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
      const res = await fetch('/availability', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          npi: provider.npi,
          provider_name: provider.name,
          city: provider.city || '',
          consultation_mode: 'Both',
          selected_date: selDate,
          client_time:  clientTime,
          client_date:  clientDate,
          is_initial:   isInitial,
        }),
      });
      const data = await res.json();
      const slots = (data.all_slots || []).map(s => ({
        time:   s.time_display,
        booked: s.booked || false,
        past:   s.past   || false,
        type:   s.type   || 'Both',
      }));
      setRealSlots(slots.length > 0 ? slots : []);

      // If the backend auto-advanced to a different date (e.g. tomorrow), update selectedDate state
      if (isInitial && data.date_iso) {
        setSelectedDate(parseDateSafe(data.date_iso));
      }
    } catch (_) {
      setRealSlots([]);
    } finally {
      setLoadingSlots(false);
    }
  };

  const handleDateSelect = (date) => {
    setSelectedDate(date);
    setSelectedSlot(null);
    setSelectedMode(null);
    fetchSlots(date);
  };

  const handleBook = () => {
    if (!selectedDate || !selectedSlot) return;
    const dateStr = selectedDate.toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
    const providerCity = provider.city || provider.address?.split(',').slice(-2, -1)[0]?.trim() || '';
    const displayMsg = `📅 Booking: ${provider.name} on ${dateStr} at ${selectedSlot} (${selectedMode})`;
    const backendMsg = `Book appointment with ${provider.name} (NPI: ${provider.npi})${providerCity ? ` in ${providerCity}` : ''} on ${dateStr} at ${selectedSlot} — ${selectedMode}. Consultation mode: ${provider.consultation || selectedMode}.`;
    // Persist this provider as member preference when the member completes a booking (MRI only)
    if (showSavePreferred) {
      try {
        const member = JSON.parse(sessionStorage.getItem('member') || 'null');
        if (member && member.member_id) {
          fetch(`/dashboard/member/${member.member_id}/preference`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              provider_name: provider.name || '',
              npi: provider.npi || '',
              address: provider.address || '',
              city: provider.city || '',
              specialty: provider.specialty || ''
            })
          }).catch(() => { });
        }
      } catch (_) { }
    }

    onBook(backendMsg, displayMsg, {
      specialty: provider.specialty || '',
      provider_name: provider.name || '',
      npi: provider.npi || '',
      address: provider.address || '',
      city: provider.city || ''
    });
    onClose();
  };

  const handleSavePreference = async () => {
    setSavingPref(true);
    setSavedMsg(null);
    try {
      const member = JSON.parse(sessionStorage.getItem('member') || 'null');
      if (member && member.member_id) {
        const res = await fetch(`/dashboard/member/${member.member_id}/preference`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            provider_name: provider.name || '',
            npi: provider.npi || '',
            address: provider.address || '',
            city: provider.city || '',
            specialty: provider.specialty || ''
          })
        });
        if (res.ok) {
          setSavedMsg('Saved as preferred');
        } else {
          setSavedMsg('Save failed');
        }
      }
    } catch (e) {
      setSavedMsg('Save failed');
    } finally {
      setSavingPref(false);
      setTimeout(() => setSavedMsg(null), 3000);
    }
  };

  const inPersonSlots   = hasInPerson   ? (realSlots || []).filter(s => s.booked || s.type === 'In-Person' || s.type === 'Both') : [];
  const telehealthSlots = hasTelehealth ? (realSlots || []).filter(s => s.booked || s.type === 'Telehealth' || s.type === 'Both') : [];

  return (
    <>
      <div className="pm-backdrop" onClick={onClose} />
      <div className="pm-modal">
        {/* Header */}
        <div className="pm-header">
          <div className="pm-header-info">
            <div className="pm-provider-name" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              {provider.name}
              {provider.gender === 'F' && <FaVenus size={14} style={{ color: '#db2777', flexShrink: 0 }} />}
              {provider.gender === 'M' && <FaMars size={14} style={{ color: '#2563eb', flexShrink: 0 }} />}
            </div>
            {provider.specialty && <div className="pm-provider-specialty">{provider.specialty}</div>}
            <div className="pm-badges">
              {provider.status === 'in-network'
                ? <span className="badge badge-in-network"><FaCircleCheck size={11} /> In-Network</span>
                : <span className="badge badge-out-of-network"><FaCircleXmark size={11} /> Out-of-Network</span>}
              {hasInPerson  && <span className="consult-badge consult-inperson"><MdLocalHospital size={13} /> In-Person</span>}
              {hasTelehealth && <span className="consult-badge consult-telehealth"><FaVideo size={12} /> Telehealth</span>}
            </div>
          </div>
          <div className="pm-header-meta">
            {provider.distance && <div className="pm-meta-row"><FaLocationDot size={11} className="pm-meta-icon" /><span>{provider.distance}</span></div>}
            {provider.npi     && <div className="pm-meta-row"><FaIdCard size={11} className="pm-meta-icon" /><span className="provider-npi">NPI: {provider.npi}</span></div>}
            {provider.phone   && <div className="pm-meta-row"><FaPhone size={10} className="pm-meta-icon" /><a href={`tel:${provider.phone}`} className="provider-phone">{provider.phone}</a></div>}
            {provider.languages && <div className="pm-meta-row"><span style={{ fontSize: 11 }}>🌐</span><span>{provider.languages}</span></div>}
          </div>
          <button className="pm-close-btn" onClick={onClose}>✕</button>
        </div>

        {/* Body */}
        <div className="pm-body">
          <div className="pm-left">
            <div className="pm-section-title">Select a Date</div>
            <MiniCalendar selected={selectedDate} onSelect={handleDateSelect} />
          </div>

          <div className="pm-right">
            <div className="pm-section-title">
              Available Slots {selectedDate ? `— ${selectedDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}` : ''}
            </div>

            {!selectedDate && <p className="pm-pick-date-hint">← Pick a date to see available slots</p>}
            {selectedDate && loadingSlots && <p className="pm-pick-date-hint">⏳ Fetching real-time slots...</p>}
            {selectedDate && !loadingSlots && realSlots !== null && realSlots.length === 0 && (
              <p className="pm-pick-date-hint">⚠️ No slots available for this date.</p>
            )}

            {selectedDate && !loadingSlots && realSlots !== null && realSlots.length > 0 && (
              <>
                <SlotSection
                  icon={<MdLocalHospital size={14} />} label="In-Person"
                  slots={inPersonSlots}
                  selected={selectedMode === 'In-Person' ? selectedSlot : null}
                  onSelect={(t) => { setSelectedSlot(t); setSelectedMode('In-Person'); }}
                />
                <SlotSection
                  icon={<FaVideo size={13} />} label="Telehealth"
                  slots={telehealthSlots}
                  selected={selectedMode === 'Telehealth' ? selectedSlot : null}
                  onSelect={(t) => { setSelectedSlot(t); setSelectedMode('Telehealth'); }}
                />
              </>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="pm-footer">
          {selectedDate && selectedSlot && (
            <div className="pm-selection-summary">
              Selected: <strong>{selectedDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}</strong> at <strong>{selectedSlot}</strong> ({selectedMode})
            </div>
          )}
          <div className="pm-footer-actions">
            <button className="pm-cancel-btn" onClick={onClose}>Cancel</button>
            {showSavePreferred && (
              <button className="pm-save-pref-btn" onClick={handleSavePreference} disabled={savingPref} style={{ marginRight: 8 }}>
                {savingPref ? 'Saving…' : 'Save as preferred'}
              </button>
            )}
            <button className="pm-book-btn" onClick={handleBook} disabled={!selectedDate || !selectedSlot}>
              Book Appointment
            </button>
          </div>
          {savedMsg && <div style={{ marginTop: 8, fontSize: 13, color: savedMsg === 'Saved as preferred' ? '#059669' : '#b91c1c' }}>{savedMsg}</div>}
        </div>
      </div>
    </>
  );
}

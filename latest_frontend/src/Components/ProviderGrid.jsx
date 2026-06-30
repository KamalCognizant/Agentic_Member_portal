// import React, { useState } from 'react';
// import { FaHospital, FaVideo, FaPhone, FaIdCard } from 'react-icons/fa';
// import { FaLocationDot, FaCircleCheck, FaCircleXmark } from 'react-icons/fa6';
// import { MdLocalHospital } from 'react-icons/md';
// import ProviderModal from './ProviderModal';

// function ConsultationBadge({ mode }) {
//   if (mode === 'In-Person') return <span className="consult-badge consult-inperson"><MdLocalHospital size={13} /> In-Person</span>;
//   if (mode === 'Telehealth') return <span className="consult-badge consult-telehealth"><FaVideo size={12} /> Telehealth</span>;
//   if (mode === 'Both') return (
//     <span className="consult-badge-group">
//       <span className="consult-badge consult-inperson"><MdLocalHospital size={13} /> In-Person</span>
//       <span className="consult-badge consult-telehealth"><FaVideo size={12} /> Telehealth</span>
//     </span>
//   );
//   return null;
// }

// function NetworkBadge({ status, tier }) {
//   if (status === 'in-network') return (
//     <span className="badge badge-in-network"><FaCircleCheck size={11} /> In-Network{tier ? ` · ${tier}` : ''}</span>
//   );
//   return <span className="badge badge-out-of-network"><FaCircleXmark size={11} /> Out-of-Network</span>;
// }

// function ProviderCard({ provider, index, onClick }) {
//   return (
//     <div className={`provider-card ${provider.status}`} onClick={() => onClick(provider)} style={{ cursor: 'pointer' }}>
//       <div className="provider-card-top">
//         <div className="provider-index">{index + 1}</div>
//         <div className="provider-card-info">
//           <div className="provider-card-title">{provider.name}</div>
//           {provider.specialty && <div className="provider-card-specialty">{provider.specialty}</div>}
//         </div>
//         <NetworkBadge status={provider.status} tier={provider.tier} />
//       </div>
//       <div className="provider-card-details">
//         {(provider.distance || provider.address) && (
//   <div className="provider-detail-row">
//     <FaLocationDot size={13} className="detail-icon" />
//     <span>
//       {provider.address}
//       {provider.distance ? ` (${provider.distance})` : ''}</span>
//           </div>
//         )}
//         {provider.phone && (
//           <div className="provider-detail-row">
//             <FaPhone size={12} className="detail-icon" />
//             <a href={`tel:${provider.phone}`} className="provider-phone" onClick={e => e.stopPropagation()}>{provider.phone}</a>
//           </div>
//         )}
//         {provider.npi && (
//           <div className="provider-detail-row">
//             <FaIdCard size={13} className="detail-icon" />
//             <span className="provider-npi">NPI: {provider.npi}</span>
//           </div>
//         )}
//         {provider.consultation && (
//           <div className="provider-detail-row">
//             <ConsultationBadge mode={provider.consultation} />
//           </div>
//         )}
//       </div>
//       <div className="pm-card-hint">Click to book →</div>
//     </div>
//   );
// }

// export default function ProviderGrid({ providers, onBook }) {
//   const [activeProvider, setActiveProvider] = useState(null);

//   if (!providers || providers.length === 0) return null;

//   const inNetwork = providers.filter(p => p.status === 'in-network');
//   const outOfNetwork = providers.filter(p => p.status === 'out-of-network');

//   return (
//     <>
//       <div className="provider-results-wrap">
//         {inNetwork.length > 0 && (
//           <div className="provider-section">
//             <div className="provider-section-label in-network-label">
//               <FaCircleCheck size={12} /> In-Network ({inNetwork.length})
//             </div>
//             <div className="provider-grid">
//               {inNetwork.map((p, i) => (
//                 <ProviderCard key={p.npi || i} provider={p} index={i} onClick={setActiveProvider} />
//               ))}
//             </div>
//           </div>
//         )}
//         {outOfNetwork.length > 0 && (
//           <div className="provider-section">
//             <div className="provider-section-label out-of-network-label">
//               <FaCircleXmark size={12} /> Out-of-Network ({outOfNetwork.length})
//             </div>
//             <div className="provider-grid">
//               {outOfNetwork.map((p, i) => (
//                 <ProviderCard key={p.npi || i} provider={p} index={inNetwork.length + i} onClick={setActiveProvider} />
//               ))}
//             </div>
//           </div>
//         )}
//       </div>

//       {activeProvider && (
//         <ProviderModal
//           provider={activeProvider}
//           onClose={() => setActiveProvider(null)}
//           onBook={(msg) => { if (onBook) onBook(msg); }}
//         />
//       )}
//     </>
//   );
// }














// import React, { useState } from 'react';
// import { FaVideo, FaPhone, FaIdCard } from 'react-icons/fa';
// import { FaLocationDot, FaCircleCheck, FaCircleXmark } from 'react-icons/fa6';
// import { MdLocalHospital } from 'react-icons/md';
// import ProviderModal from './ProviderModal';

// const INITIAL_VISIBLE = 1;

// function ConsultationBadge({ mode }) {
//   if (mode === 'In-Person') return <span className="consult-badge consult-inperson"><MdLocalHospital size={13} /> In-Person</span>;
//   if (mode === 'Telehealth') return <span className="consult-badge consult-telehealth"><FaVideo size={12} /> Telehealth</span>;
//   if (mode === 'Both') return (
//     <span className="consult-badge-group">
//       <span className="consult-badge consult-inperson"><MdLocalHospital size={13} /> In-Person</span>
//       <span className="consult-badge consult-telehealth"><FaVideo size={12} /> Telehealth</span>
//     </span>
//   );
//   return null;
// }

// function NetworkBadge({ status }) {
//   if (status === 'in-network') return (
//     <span className="badge badge-in-network"><FaCircleCheck size={11} /> In-Network</span>
//   );
//   return <span className="badge badge-out-of-network"><FaCircleXmark size={11} /> Out-of-Network</span>;
// }

// function ProviderCard({ provider, index, onClick }) {
//   return (
//     <div className={`provider-card ${provider.status}`} onClick={() => onClick(provider)} style={{ cursor: 'pointer' }}>
//       <div className="provider-card-top">
//         <div className="provider-index">{index + 1}</div>
//         <div className="provider-card-info">
//           <div className="provider-card-title">{provider.name}</div>
//           {provider.specialty && <div className="provider-card-specialty">{provider.specialty}</div>}
//         </div>
//         <NetworkBadge status={provider.status} />
//       </div>
//       <div className="provider-card-details">
//         {(provider.distance || provider.address) && (
//           <div className="provider-detail-row">
//             <FaLocationDot size={13} className="detail-icon" />
//             <span>{provider.address}{provider.distance ? ` (${provider.distance})` : ''}</span>
//           </div>
//         )}
//         {provider.phone && (
//           <div className="provider-detail-row">
//             <FaPhone size={12} className="detail-icon" />
//             <a href={`tel:${provider.phone}`} className="provider-phone" onClick={e => e.stopPropagation()}>{provider.phone}</a>
//           </div>
//         )}
//         {provider.npi && (
//           <div className="provider-detail-row">
//             <FaIdCard size={13} className="detail-icon" />
//             <span className="provider-npi">NPI: {provider.npi}</span>
//           </div>
//         )}
//         {provider.consultation && (
//           <div className="provider-detail-row">
//             <ConsultationBadge mode={provider.consultation} />
//           </div>
//         )}
//       </div>
//       <div className="pm-card-hint">Click to book →</div>
//     </div>
//   );
// }

// export default function ProviderGrid({ providers, onBook }) {
//   const [activeProvider, setActiveProvider] = useState(null);
//   const [visibleCount, setVisibleCount] = useState(INITIAL_VISIBLE);

//   if (!providers || providers.length === 0) return null;

//   // In-network first, then out-of-network
//   const inNetwork = providers.filter(p => p.status === 'in-network');
//   const outOfNetwork = providers.filter(p => p.status === 'out-of-network');
//   const allProviders = [...inNetwork, ...outOfNetwork];

//   const visible = allProviders.slice(0, visibleCount);
//   const hiddenCount = allProviders.length - visibleCount;
//   const showingAll = visibleCount >= allProviders.length;

//   const visibleInNetwork = visible.filter(p => p.status === 'in-network');
//   const visibleOutOfNetwork = visible.filter(p => p.status === 'out-of-network');

//   return (
//     <>
//       <div className="provider-results-wrap">
//         {visibleInNetwork.length > 0 && (
//           <div className="provider-section">
//             <div className="provider-section-label in-network-label">
//               <FaCircleCheck size={12} /> In-Network ({inNetwork.length})
//             </div>
//             <div className="provider-grid">
//               {visibleInNetwork.map((p, i) => (
//                 <ProviderCard key={p.npi || i} provider={p} index={i} onClick={setActiveProvider} />
//               ))}
//             </div>
//           </div>
//         )}

//         {visibleOutOfNetwork.length > 0 && (
//           <div className="provider-section">
//             <div className="provider-section-label out-of-network-label">
//               <FaCircleXmark size={12} /> Out-of-Network ({outOfNetwork.length})
//             </div>
//             <div className="provider-grid">
//               {visibleOutOfNetwork.map((p, i) => (
//                 <ProviderCard key={p.npi || i} provider={p} index={visibleInNetwork.length + i} onClick={setActiveProvider} />
//               ))}
//             </div>
//           </div>
//         )}

//         {!showingAll && (
//           <button className="show-more-btn" onClick={() => setVisibleCount(allProviders.length)}>
//             Show {hiddenCount} more doctor{hiddenCount !== 1 ? 's' : ''} ↓
//           </button>
//         )}

//         {showingAll && allProviders.length > INITIAL_VISIBLE && (
//           <button className="show-more-btn show-less-btn" onClick={() => setVisibleCount(INITIAL_VISIBLE)}>
//             Show less ↑
//           </button>
//         )}
//       </div>

//       {activeProvider && (
//         <ProviderModal
//           provider={activeProvider}
//           onClose={() => setActiveProvider(null)}
//           onBook={(backendMsg, displayMsg) => {
//             if (onBook) onBook(backendMsg, displayMsg);
//           }}
//         />
//       )}
//     </>
//   );
// }





import React, { useState } from 'react';
import { FaPhone, FaIdCard, FaVideo } from 'react-icons/fa';
import { FaLocationDot, FaCircleCheck, FaCircleXmark, FaMars, FaVenus } from 'react-icons/fa6';
import { MdLocalHospital } from 'react-icons/md';
import ProviderModal from './ProviderModal';

const INITIAL_VISIBLE = 3;

function StarRating({ rating }) {
  if (!rating) return null;
  const full = Math.floor(rating);
  const half = rating - full >= 0.25 && rating - full < 0.75;
  const empty = 5 - full - (half ? 1 : 0);
  return (
    <span style={{ fontSize: 11, color: '#f59e0b', letterSpacing: 1 }}>
      {'★'.repeat(full)}{half ? '½' : ''}{'☆'.repeat(empty)}
      <span style={{ color: '#64748b', marginLeft: 3, fontWeight: 600 }}>{rating.toFixed(1)}</span>
    </span>
  );
}


function NetworkBadge({ status }) {
  if (status === 'in-network') return (
    <span className="badge badge-in-network"><FaCircleCheck size={11} /> In-Network</span>
  );
  return <span className="badge badge-out-of-network"><FaCircleXmark size={11} /> Out-of-Network</span>;
}

function SavePreferredButton({ provider }) {
  const [saving, setSaving] = React.useState(false);
  const [saved, setSaved] = React.useState(false);

  const handleSave = async (e) => {
    e.stopPropagation();
    setSaving(true);
    try {
      const member = JSON.parse(sessionStorage.getItem('member') || 'null');
      if (member?.member_id) {
        await fetch(`/dashboard/member/${member.member_id}/preference`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            provider_name: provider.name || '',
            npi: provider.npi || '',
            address: provider.address || '',
            city: provider.city || '',
            specialty: provider.specialty || '',
          }),
        });
        setSaved(true);
        setTimeout(() => setSaved(false), 3000);
      }
    } catch (_) {}
    finally { setSaving(false); }
  };

  return (
    <button
      onClick={handleSave}
      disabled={saving || saved}
      style={{
        padding: '5px 14px',
        borderRadius: 20,
        border: '1.5px solid #2D308D',
        background: saved ? '#ecfccb' : '#fff',
        color: saved ? '#15803d' : '#2D308D',
        fontSize: 11,
        fontWeight: 600,
        cursor: saving ? 'wait' : 'pointer',
        transition: 'all 0.2s',
      }}
    >
      {saved ? '⭐ Saved as preferred' : saving ? 'Saving…' : '⭐ Remember this provider'}
    </button>
  );
}

function ProviderCard({ provider, index, onClick, mriState, referralGate, preference, mriPrescribed }) {
  const genderIcon = provider.gender === 'F'
    ? <FaVenus size={15} style={{ color: '#db2777' }} />
    : provider.gender === 'M'
    ? <FaMars size={15} style={{ color: '#2563eb' }} />
    : null;

  // Lock booking for imaging providers when prior auth is pending/missing,
  // OR for any specialist when HMO referral is required and not yet approved.
  const IMAGING_SPECIALTIES = ['radiology', 'diagnostic radiology', 'imaging', 'nuclear medicine', 'mri', 'ct'];
  const provSpecialty = (provider.specialty || '').toLowerCase();
  const provName      = (provider.name || '').toLowerCase();
  const isImagingProvider = IMAGING_SPECIALTIES.some(kw => provSpecialty.includes(kw) || provName.includes(kw));
  
  // "Save as Preferred" button logic:
  // 1. Only show for imaging providers
  // 2. Only show if an MRI is actually prescribed
  const showSavePreferred = isImagingProvider && mriPrescribed;

  const bookingBlocked =
    (isImagingProvider && (mriState === 'prior_auth_pending' || mriState === 'prior_auth_none')) ||
    referralGate;
  const blockLabel = referralGate
    ? '🔒 PCP referral needed — booking unlocks after your PCP visit'
    : mriState === 'prior_auth_pending'
    ? '🔒 Insurance sign-off pending — booking locked until approved'
    : mriState === 'prior_auth_none'
    ? '🔒 Insurance sign-off needed before booking'
    : null;

  return (
    <div className={`provider-card ${provider.status}`}>
      <div className="provider-card-top">
        <div className="provider-index">{index + 1}</div>
        <div className="provider-card-info">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <div className="provider-card-title">{provider.name}</div>
              {genderIcon}
            </div>
            {/** Preferred indicator: match by NPI first, then by provider_name equality */}
            {preference && (
              (() => {
                const prefNpi = (preference.npi || '').toString();
                const provNpi = (provider.npi || '').toString();
                const prefName = (preference.provider_name || preference.provider_name || '').toLowerCase();
                const provName = (provider.name || '').toLowerCase();
                const isPref = (prefNpi && provNpi && prefNpi === provNpi) || (prefName && provName && prefName === provName);
                return isPref ? (
                  <span style={{ background: '#ecfccb', color: '#15803d', padding: '4px 8px', borderRadius: 12, fontSize: 12, fontWeight: 700, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                    ⭐ Preferred
                  </span>
                ) : null;
              })()
            )}
          </div>
          {provider.specialty && <div className="provider-card-specialty">{provider.specialty}</div>}
          {provider.rating && <StarRating rating={provider.rating} />}
          {provider.consultation && (() => {
            const c = provider.consultation.replace(/&amp;/g, '&');
            const hasInPerson  = c === 'In-Person' || c === 'Both' || c.includes('In-Person');
            const hasTelehealth = c === 'Telehealth' || c === 'Both' || c.includes('Telehealth');
            return (
              <div style={{ display: 'flex', gap: 4, marginTop: 4, flexWrap: 'wrap' }}>
                {hasInPerson && (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3, fontSize: 11, padding: '2px 7px', borderRadius: 10, background: '#eff6ff', color: '#1d4ed8', border: '1px solid #bfdbfe' }}>
                    <MdLocalHospital size={12} /> In-Person
                  </span>
                )}
                {hasTelehealth && (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3, fontSize: 11, padding: '2px 7px', borderRadius: 10, background: '#f0fdf4', color: '#15803d', border: '1px solid #bbf7d0' }}>
                    <FaVideo size={11} /> Telehealth
                  </span>
                )}
              </div>
            );
          })()}
        </div>
        <NetworkBadge status={provider.status} />
      </div>
      <div className="provider-card-details">
        {(provider.distance || provider.address) && (
          <div className="provider-detail-row">
            <FaLocationDot size={13} className="detail-icon" />
            <span>
              {provider.address}
              {provider.distance ? ` (${provider.distance})` : ''}
            </span>
          </div>
        )}
        {provider.phone && (
          <div className="provider-detail-row">
            <FaPhone size={12} className="detail-icon" />
            <a href={`tel:${provider.phone}`} className="provider-phone" onClick={e => e.stopPropagation()}>{provider.phone}</a>
          </div>
        )}
        {provider.npi && (
          <div className="provider-detail-row">
            <FaIdCard size={13} className="detail-icon" />
            <span className="provider-npi">NPI: {provider.npi}</span>
          </div>
        )}
        {provider.languages && (
          <div className="provider-detail-row">
            <span style={{ fontSize: 12, flexShrink: 0 }}>🌐</span>
            <span style={{ fontSize: 12, color: '#334155' }}>{provider.languages}</span>
          </div>
        )}
      </div>

      {provider.llm_reasoning && (
        <div style={{
          background: '#f0fdf4', border: '1px solid #86efac',
          borderRadius: 8, padding: '8px 12px', marginTop: 8, fontSize: 12
        }}>
          <strong>🤖 Why chosen:</strong> {provider.llm_reasoning}
        </div>
      )}

      {provider.tradeoff && provider.tradeoff !== 'No significant tradeoff' && (
        <div style={{
          background: '#fef3c7', border: '1px solid #fcd34d',
          borderRadius: 8, padding: '8px 12px', marginTop: 4, fontSize: 11,
          color: '#92400e'
        }}>
          <strong>⚖️ Tradeoff:</strong> {provider.tradeoff}
        </div>
      )}

      {provider.critic_note && (
        <div style={{
          background: '#eff6ff', border: '1px solid #bfdbfe',
          borderRadius: 8, padding: '8px 12px', marginTop: 4, fontSize: 11,
          color: '#1e40af'
        }}>
          <strong>✅ Verified:</strong> {provider.critic_note}
        </div>
      )}

      {provider.rejected_others?.length > 0 && (
        <details style={{ marginTop: 6 }}>
          <summary style={{ fontSize: 11, color: '#64748b', cursor: 'pointer' }}>
            Also considered ({provider.rejected_others.length} others)
          </summary>
          {provider.rejected_others.map((r, i) => (
            <div key={i} style={{ fontSize: 11, color: '#94a3b8', padding: '2px 0' }}>
              ✗ {r.name} — {r.rejection_reason}
            </div>
          ))}
        </details>
      )}

      <div style={{ display: 'flex', justifyContent: 'center', marginTop: 10, flexDirection: 'column', alignItems: 'center', gap: 6 }}>
        {bookingBlocked ? (
          <>
            <div style={{
              padding: '8px 14px',
              borderRadius: 20,
              border: '1.5px solid #f59e0b',
              background: '#fef3c7',
              color: '#92400e',
              fontSize: 12,
              fontWeight: 600,
              display: 'flex',
              alignItems: 'center',
              gap: 6,
            }}>
              {blockLabel}
            </div>
            {showSavePreferred && <SavePreferredButton provider={provider} />}
          </>
        ) : (
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <button
              onClick={(e) => { e.stopPropagation(); onClick(provider); }}
              style={{
                padding: '7px 22px',
                borderRadius: 20,
                border: '1.5px solid #2D308D',
                background: '#2D308D',
                color: '#fff',
                fontSize: 12,
                fontWeight: 700,
                cursor: 'pointer',
                transition: 'background 0.2s',
              }}
              onMouseEnter={e => e.currentTarget.style.background = '#1a1a6e'}
              onMouseLeave={e => e.currentTarget.style.background = '#2D308D'}
            >
              Click to Book
            </button>
            {showSavePreferred && <SavePreferredButton provider={provider} />}
          </div>
        )}
      </div>
    </div>
  );
}

export default function ProviderGrid({ providers, onBook, rankedList, mriState, priorAuthPending, referralGate, preference, mriPrescribed }) {
  const [activeProvider, setActiveProvider] = useState(null);

  if (!providers || providers.length === 0) return null;

  const inNetwork = providers.filter(p => p.status === 'in-network');
  const outOfNetwork = providers.filter(p => p.status === 'out-of-network');

  // Only block modal for imaging providers when prior auth is pending/missing,
  // or for any provider when referral gate is active.
  const IMAGING_SPECIALTIES = ['radiology', 'diagnostic radiology', 'imaging', 'nuclear medicine', 'mri', 'ct'];
  const isImagingProvider = (p) => IMAGING_SPECIALTIES.some(kw =>
    (p.specialty || '').toLowerCase().includes(kw) || (p.name || '').toLowerCase().includes(kw)
  );
  const isModalBlocked = (p) =>
    referralGate ||
    (isImagingProvider(p) && (mriState === 'prior_auth_pending' || mriState === 'prior_auth_none'));

  return (
    <>
      <div className="provider-results-wrap">
        {inNetwork.length > 0 && (
          <div className="provider-section">
            <div className="provider-section-label in-network-label">
              <FaCircleCheck size={12} /> In-Network
            </div>
            <div className="provider-grid">
              {inNetwork.map((p, i) => (
                <ProviderCard key={p.npi || i} provider={p} index={i} onClick={setActiveProvider} mriState={mriState} referralGate={referralGate} preference={preference} mriPrescribed={mriPrescribed} />
              ))}
            </div>
          </div>
        )}
        {outOfNetwork.length > 0 && (
          <div className="provider-section">
            <div className="provider-section-label out-of-network-label">
              <FaCircleXmark size={12} /> Out-of-Network
            </div>
            <div className="provider-grid">
              {outOfNetwork.map((p, i) => (
                <ProviderCard key={p.npi || i} provider={p} index={inNetwork.length + i} onClick={setActiveProvider} mriState={mriState} referralGate={referralGate} preference={preference} mriPrescribed={mriPrescribed} />
              ))}
            </div>
          </div>
        )}
      </div>

      {activeProvider && !isModalBlocked(activeProvider) && (
        <ProviderModal
          provider={activeProvider}
          mriPrescribed={mriPrescribed}
          defaultDate={activeProvider._agentDate || null}
          onClose={() => setActiveProvider(null)}
          onBook={(backendMsg, displayMsg, bookingMeta) => { if (onBook) onBook(backendMsg, displayMsg, bookingMeta); }}
        />
      )}
    </>
  );
}

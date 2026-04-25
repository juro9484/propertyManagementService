import { useState, useEffect, useRef } from 'react'
import { X, Copy, Check, ChevronLeft, ChevronRight, RefreshCw, Send, AlertCircle } from 'lucide-react'

function generateLandlordEmail(lead) {
  const isLLC    = lead.badges?.includes('LLC')
  const isOOS    = lead.badges?.includes('OUT_OF_STATE')
  const isAbsent = lead.badges?.includes('ABSENTEE')
  const count    = lead.property_count ?? 1
  const name     = lead.owner_name ?? 'Property Owner'
  const addr     = lead.property_address ?? 'your property'
  const city     = lead.city ?? 'Boulder'

  const salutation = isLLC
    ? `To the ownership team at ${name}`
    : `Dear ${name.split(',')[0].trim()}`

  const ownerCtx = isLLC
    ? `As an investment entity with ${count > 1 ? `${count} properties` : 'holdings'} in Boulder County, you understand that professional management directly impacts your net operating income.`
    : count > 1
    ? `With ${count} properties across Boulder County, the time and attention required to manage tenants, maintenance, and rent collection adds up quickly.`
    : `Owning a rental property in Boulder County is a sound investment — but managing it well requires local expertise and consistent attention.`

  const locationCtx = isOOS
    ? `\n\nManaging a property remotely means you are often the last to know about deferred maintenance, tenant issues, or market shifts. Our team handles every detail on the ground so you never have to wonder what is happening with your asset.`
    : isAbsent
    ? `\n\nEven managing a property across town means late-night calls, coordinating vendors, and chasing rent. We eliminate all of that.`
    : ''

  const propRef = count > 1
    ? `your portfolio including ${addr} and ${count - 1} additional ${count - 1 === 1 ? 'property' : 'properties'} in Boulder County`
    : `your property at ${addr} in ${city}`

  return `Subject: Property Management Services — ${city}, Boulder County

${salutation},

I am reaching out regarding ${propRef}.

${ownerCtx}${locationCtx}

At All County Property Management, we specialize exclusively in Boulder County and provide:

  • Thorough tenant screening — credit, background, and income verification
  • Guaranteed on-time rent collection with owner direct deposit
  • 24/7 maintenance coordination through our vetted contractor network
  • Monthly financial statements and year-end tax summaries
  • Proactive property inspections to protect long-term asset value
  • Full compliance with Colorado landlord-tenant law

Our owners typically experience higher occupancy, fewer turnovers, and significantly less personal time spent on day-to-day management.

I would welcome the opportunity to schedule a brief call to discuss your portfolio and share how we can add value. I am happy to provide a complimentary rental market analysis for ${city} properties as well.

Please feel free to reach out at your convenience.

Respectfully,
[Your Name]
All County Property Management — Boulder County
Direct: (303) 555-0100
www.allcountyboulder.com`
}

function generateRealtorEmail(realtor) {
  const fname = (realtor.name ?? '').split(' ')[0]
  const brok  = realtor.brokerage ?? 'your brokerage'
  const count = realtor.investor_listings ?? 0
  const specs = realtor.specialties ?? []
  const tier  = realtor.score

  const valueStmt = count >= 18
    ? `Your track record of ${count} investor transactions speaks for itself — you are clearly a trusted advisor in the Boulder County investment community.`
    : count >= 12
    ? `With ${count} investor transactions at ${brok}, you are among the more active investment-focused agents in Boulder County.`
    : `Your investment property work at ${brok} caught my attention.`

  const specLine = specs.length > 0
    ? ` Your focus on ${specs.slice(0, 2).join(' and ')} tells me your clients are thinking long-term about their holdings.`
    : ''

  const close = tier === 'High'
    ? `I would love to find 20 minutes for a coffee or call this week — I am flexible on timing.`
    : `Would you be open to a brief introductory call when your schedule allows?`

  return `Subject: Referral Partnership — ${brok}

Dear ${fname},

${valueStmt}${specLine}

My name is [Your Name], and I run All County Property Management, a boutique firm focused exclusively on Boulder County. I am reaching out because I believe there is a natural referral partnership opportunity between us that would benefit your investor clients.

Here is what I see regularly: your clients close on an investment property and then face the challenge of managing it profitably — especially if they are out of state, hold multiple properties, or simply do not want the day-to-day responsibility of being a landlord. That is precisely where we step in.

What a partnership would look like:

  • You refer your buyer clients to us for property management after closing
  • We refer property owners considering a sale or portfolio expansion back to you
  • Your clients receive hands-on management from a team that knows Boulder County deeply
  • You maintain the relationship with a trusted partner protecting your clients' experience

We are selective about the properties we take on, which means your clients receive genuine attention — not a queue number.

${close}

Best regards,
[Your Name]
All County Property Management — Boulder County
Direct: (303) 555-0100
www.allcountyboulder.com`
}

// ── Backend API ──────────────────────────────────────────────────────────────
// Points to your FastAPI server — holds Lob/SendGrid keys, tracks usage.
const API_BASE = (import.meta.env.VITE_API_URL || '') + '/api'

async function apiVerifyAddress(lead) {
  const res = await fetch(`${API_BASE}/letters/verify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name:    lead.owner_name,
      line1:   lead.mailing_address ?? lead.property_address,
      city:    lead.mailing_city    ?? lead.city,
      state:   lead.mailing_state   ?? 'CO',
      zip:     lead.mailing_zip     ?? '',
    }),
  })
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).message ?? `Verify error ${res.status}`)
  return await res.json()
  // Expected: { deliverability: 'deliverable'|'undeliverable'|..., line1, city, state, zip }
}

async function apiSendLetter(lead, letterText) {
  const res = await fetch(`${API_BASE}/letters/send`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lead, letterText }),
  })
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).message ?? `Send error ${res.status}`)
  return await res.json()
  // Expected: { id: 'ltr_...', expected_delivery_date: '2026-03-18', url: '...' }
}

export default function OutreachModal({ lead, type, allLeads, onClose }) {
  const isRealtor = type === 'realtor'
  const [email, setEmail]           = useState('')
  const [copied, setCopied]         = useState(false)
  const [currentIdx, setCurrentIdx] = useState(null)
  const [sendMode, setSendMode]     = useState(false)
  const [generating, setGenerating] = useState(false)
  // verify: null | 'checking' | { deliverability, line1, city, state, zip } | 'error'
  const [verify, setVerify]         = useState(null)
  const [verifyError, setVerifyError] = useState('')
  const [sendStatus, setSendStatus] = useState(null) // null | 'sending' | 'sent' | 'error'
  const [sendResult, setSendResult] = useState(null)
  const [sendError, setSendError]   = useState('')
  const textareaRef = useRef(null)

  const getAuthHeaders = () => {
    const t = localStorage.getItem('acpm_token')
    return t ? { Authorization: `Bearer ${t}`, 'Content-Type': 'application/json' } : { 'Content-Type': 'application/json' }
  }

  useEffect(() => {
    if (!isRealtor && allLeads)
      setCurrentIdx(allLeads.findIndex(l => l.folio === lead.folio))
  }, [lead, allLeads, isRealtor])

  useEffect(() => {
    // Start with empty — user clicks Generate to create AI email
    setEmail('')
    setCopied(false)
    setGenerating(false)
  }, [lead, type])

  const handleGenerate = async (tone = 'professional') => {
    setGenerating(true)
    try {
      const res = await fetch(`${API_BASE}/outreach/generate`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ lead_id: lead.id, tone }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        // Fall back to static template if AI is unavailable
        setEmail(isRealtor ? generateRealtorEmail(lead) : generateLandlordEmail(lead))
        return
      }
      const data = await res.json()
      setEmail(data.email)
    } catch {
      // Fall back to static template
      setEmail(isRealtor ? generateRealtorEmail(lead) : generateLandlordEmail(lead))
    } finally {
      setGenerating(false)
    }
  }

  useEffect(() => {
    const fn = e => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', fn)
    return () => window.removeEventListener('keydown', fn)
  }, [onClose])

  const handleCopy = async () => {
    try { await navigator.clipboard.writeText(email) }
    catch { textareaRef.current?.select(); document.execCommand('copy') }
    setCopied(true)
    setTimeout(() => setCopied(false), 2200)
  }

  const handleVerify = async () => {
    setVerify('checking')
    setVerifyError('')
    try {
      const result = await apiVerifyAddress(lead)
      setVerify(result)
    } catch (err) {
      setVerify('error')
      setVerifyError(err.message)
    }
  }

  const handleSend = async () => {
    setSendStatus('sending')
    setSendError('')
    try {
      const result = await apiSendLetter(lead, email)
      setSendStatus('sent')
      setSendResult(result)
    } catch (err) {
      setSendStatus('error')
      setSendError(err.message)
    }
  }

  const openSendMode = () => {
    setSendMode(true)
    setVerify(null)
    setVerifyError('')
    setSendStatus(null)
    setSendResult(null)
    setSendError('')
  }

  const displayName = isRealtor ? lead.name : lead.owner_name
  const subline     = isRealtor
    ? `${lead.brokerage} · ${lead.investor_listings} investor listings`
    : `${lead.property_address}, ${lead.city} · Score ${lead.score}`

  const BADGE_CFG = {
    NEW_OWNER:    { label: 'New Owner',    bg: 'var(--b-green-bg)',  tx: 'var(--b-green-tx)',  bd: 'var(--b-green-bd)'  },
    LLC:          { label: 'LLC / Entity', bg: 'var(--b-blue-bg)',   tx: 'var(--b-blue-tx)',   bd: 'var(--b-blue-bd)'   },
    ABSENTEE:     { label: 'Absentee',     bg: 'var(--b-amber-bg)',  tx: 'var(--b-amber-tx)',  bd: 'var(--b-amber-bd)'  },
    OUT_OF_STATE: { label: 'Out of State', bg: 'var(--b-red-bg)',    tx: 'var(--b-red-tx)',    bd: 'var(--b-red-bd)'    },
    PORTFOLIO:    { label: 'Portfolio',    bg: 'var(--b-purple-bg)', tx: 'var(--b-purple-tx)', bd: 'var(--b-purple-bd)' },
    MULTI_PROP:   { label: 'Multi-prop',   bg: 'var(--b-sky-bg)',    tx: 'var(--b-sky-tx)',    bd: 'var(--b-sky-bd)'    },
  }

  return (
    <div
      style={{ position: 'fixed', inset: 0, zIndex: 2000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24px' }}
      onClick={onClose}
    >
      {/* Backdrop */}
      <div style={{ position: 'absolute', inset: 0, backgroundColor: 'rgba(0,0,0,0.55)', backdropFilter: 'blur(4px)' }} />

      {/* Modal */}
      <div
        className="animate-scale-in"
        style={{
          position: 'relative', width: '100%', maxWidth: '900px',
          backgroundColor: 'var(--bg-surface)', border: '1px solid var(--bd)',
          borderRadius: '8px', boxShadow: '0 24px 64px rgba(0,0,0,0.4)',
          display: 'flex', flexDirection: 'column', maxHeight: '92vh',
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{
          padding: '16px 20px', borderBottom: '1px solid var(--bd)',
          backgroundColor: 'var(--bg-raised)', borderRadius: '8px 8px 0 0',
          display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexShrink: 0,
        }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px' }}>
            <img
              src="/img_55573.png"
              alt="All County Property Management"
              style={{ width: '40px', height: '40px', objectFit: 'contain', flexShrink: 0, marginTop: '2px', borderRadius: '4px' }}
            />
            <div>
              <h2 style={{ fontSize: '14px', fontWeight: 600, color: 'var(--tx-1)', margin: 0 }}>
                Draft Outreach Letter
              </h2>
              <p style={{ fontSize: '12px', color: 'var(--tx-2)', margin: '2px 0 0' }}>{displayName}</p>
              <p style={{ fontSize: '11px', color: 'var(--tx-4)', margin: '1px 0 0' }}>{subline}</p>
            </div>
          </div>
          <button className="btn-ghost" style={{ padding: '6px', marginTop: '-2px', marginRight: '-4px' }} onClick={onClose}>
            <X size={15} />
          </button>
        </div>

        {/* Badges — landlord only */}
        {!isRealtor && lead.badges?.length > 0 && (
          <div style={{ padding: '12px 20px 0', display: 'flex', flexWrap: 'wrap', gap: '6px', flexShrink: 0 }}>
            {lead.badges.map(b => {
              const c = BADGE_CFG[b]
              return c ? (
                <span key={b} style={{
                  display: 'inline-flex', alignItems: 'center', padding: '2px 8px',
                  borderRadius: '3px', fontSize: '11px', fontWeight: 500,
                  backgroundColor: c.bg, color: c.tx, border: `1px solid ${c.bd}`,
                }}>
                  {c.label}
                </span>
              ) : null
            })}
          </div>
        )}

        {/* Email editor */}
        <div style={{ padding: '16px 20px', flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
            <label style={{ fontSize: '10px', fontWeight: 700, color: 'var(--tx-3)', textTransform: 'uppercase', letterSpacing: '0.1em' }}>
              {email ? 'Letter Draft — edit before sending' : 'Generate a personalized outreach letter'}
            </label>
            <div style={{ display: 'flex', gap: '4px' }}>
              {email && (
                <button className="btn-ghost" style={{ fontSize: '11px', padding: '4px 8px' }}
                  onClick={() => handleGenerate('professional')} disabled={generating}>
                  <RefreshCw size={10} className={generating ? 'animate-spin' : ''} /> Regenerate
                </button>
              )}
            </div>
          </div>

          {!email && !generating ? (
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '16px', minHeight: '420px' }}>
              <p style={{ fontSize: '13px', color: 'var(--tx-4)', margin: 0, textAlign: 'center' }}>
                AI will write a personalized letter based on this lead's<br />properties, location, score, and ownership signals.
              </p>
              <div style={{ display: 'flex', gap: '8px' }}>
                <button className="btn-gold" style={{ fontSize: '12px', padding: '8px 20px' }} onClick={() => handleGenerate('professional')}>
                  Generate Letter
                </button>
                <button className="btn-ghost" style={{ fontSize: '11px', padding: '8px 12px' }} onClick={() => handleGenerate('friendly')}>
                  Friendly tone
                </button>
                <button className="btn-ghost" style={{ fontSize: '11px', padding: '8px 12px' }} onClick={() => handleGenerate('direct')}>
                  Direct tone
                </button>
              </div>
              <button className="btn-ghost" style={{ fontSize: '11px', color: 'var(--tx-4)' }}
                onClick={() => setEmail(generateLandlordEmail(lead))}>
                Use basic template instead
              </button>
            </div>
          ) : generating ? (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '420px' }}>
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '10px' }}>
                <RefreshCw size={18} className="animate-spin" style={{ color: 'var(--gold)' }} />
                <p style={{ fontSize: '12px', color: 'var(--tx-4)', margin: 0 }}>Writing personalized letter...</p>
              </div>
            </div>
          ) : (
            <textarea
              ref={textareaRef}
              className="field"
              style={{ flex: 1, resize: 'none', fontFamily: 'monospace', fontSize: '12px', lineHeight: 1.6, color: 'var(--tx-2)', minHeight: '420px' }}
              value={email}
              onChange={e => setEmail(e.target.value)}
              spellCheck
            />
          )}
        </div>

        {/* Send via Mail panel */}
        {sendMode && (
          <div style={{ borderTop: '1px solid var(--bd)', backgroundColor: 'var(--bg-raised)', padding: '16px 20px', flexShrink: 0 }}>

            {sendStatus === 'sent' ? (
              /* ── Success state ── */
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <div style={{ width: '32px', height: '32px', borderRadius: '50%', backgroundColor: 'var(--b-green-bg)', border: '1px solid var(--b-green-bd)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                  <Check size={15} style={{ color: 'var(--b-green-tx)' }} />
                </div>
                <div>
                  <p style={{ fontSize: '13px', fontWeight: 600, color: 'var(--b-green-tx)', margin: 0 }}>Letter queued for delivery</p>
                  <p style={{ fontSize: '11px', color: 'var(--tx-4)', margin: '3px 0 0' }}>
                    {sendResult?.expected_delivery_date
                      ? `Expected delivery: ${new Date(sendResult.expected_delivery_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`
                      : 'Typically delivered within 5–7 business days'}
                    {sendResult?.id && <span style={{ marginLeft: '10px', fontFamily: 'monospace', fontSize: '10px', color: 'var(--tx-4)' }}>#{sendResult.id}</span>}
                  </p>
                </div>
              </div>
            ) : (
              <>
                {/* Header row */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
                  <span style={{ fontSize: '11px', fontWeight: 700, color: 'var(--tx-2)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                    Send Physical Letter
                  </span>
                  <span style={{ fontSize: '10px', color: 'var(--tx-4)' }}>Powered by Lob · ~$0.87/letter · 5–7 business days</span>
                </div>

                {/* Address + verify row */}
                <div style={{ display: 'flex', gap: '10px', alignItems: 'flex-start' }}>
                  <div style={{ flex: 1 }}>
                    <p style={{ fontSize: '10px', color: 'var(--tx-4)', margin: '0 0 4px', textTransform: 'uppercase', letterSpacing: '0.07em' }}>Mailing address</p>
                    {verify && verify !== 'checking' && verify !== 'error' ? (
                      /* Verified — show standardized address */
                      <div style={{ display: 'flex', alignItems: 'flex-start', gap: '6px' }}>
                        <Check size={11} style={{ color: 'var(--b-green-tx)', marginTop: '2px', flexShrink: 0 }} />
                        <div>
                          <p style={{ fontSize: '12px', color: 'var(--tx-1)', margin: 0, lineHeight: 1.5 }}>
                            {lead.owner_name}<br />
                            {verify.line1}, {verify.city}, {verify.state} {verify.zip}
                          </p>
                          {verify.deliverability !== 'deliverable' && (
                            <p style={{ fontSize: '10px', color: 'var(--b-amber-tx)', margin: '4px 0 0', display: 'flex', alignItems: 'center', gap: '4px' }}>
                              <AlertCircle size={10} /> {verify.deliverability?.replace(/_/g, ' ')}
                            </p>
                          )}
                        </div>
                      </div>
                    ) : (
                      /* Unverified — show raw address */
                      <p style={{ fontSize: '12px', color: 'var(--tx-2)', margin: 0, lineHeight: 1.5 }}>
                        {lead.owner_name}<br />
                        {lead.mailing_address
                          ? <>{lead.mailing_address}{lead.mailing_city ? `, ${lead.mailing_city}` : ''}{lead.mailing_state ? ` ${lead.mailing_state}` : ''}</>
                          : <span style={{ color: 'var(--b-amber-tx)', fontSize: '11px' }}>No mailing address — property address will be used</span>
                        }
                      </p>
                    )}
                    {verify === 'error' && (
                      <p style={{ fontSize: '11px', color: 'var(--b-red-tx)', margin: '4px 0 0', display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <AlertCircle size={10} /> {verifyError}
                      </p>
                    )}
                  </div>

                  {/* Action buttons */}
                  <div style={{ display: 'flex', gap: '8px', flexShrink: 0, alignItems: 'center', paddingTop: '18px' }}>
                    {/* Step 1: Verify */}
                    {(!verify || verify === 'error') && (
                      <button
                        className="btn-primary"
                        style={{ fontSize: '12px', padding: '6px 14px' }}
                        onClick={handleVerify}
                      >
                        {verify === 'checking' ? <><RefreshCw size={11} style={{ animation: 'spin 1s linear infinite' }} /> Checking…</> : 'Verify Address'}
                      </button>
                    )}
                    {verify === 'checking' && (
                      <span style={{ fontSize: '12px', color: 'var(--tx-4)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <RefreshCw size={11} /> Verifying…
                      </span>
                    )}
                    {/* Step 2: Send (only after verify) */}
                    {verify && verify !== 'checking' && verify !== 'error' && (
                      <button
                        className="btn-gold"
                        style={{ fontSize: '12px', padding: '6px 16px', opacity: sendStatus === 'sending' ? 0.5 : 1 }}
                        disabled={sendStatus === 'sending'}
                        onClick={handleSend}
                      >
                        <Send size={12} />
                        {sendStatus === 'sending' ? 'Sending…' : 'Confirm & Send'}
                      </button>
                    )}
                  </div>
                </div>

                {sendStatus === 'error' && (
                  <p style={{ fontSize: '11px', color: 'var(--b-red-tx)', margin: '10px 0 0', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <AlertCircle size={10} /> {sendError}
                  </p>
                )}
              </>
            )}
          </div>
        )}

        {/* Footer */}
        <div style={{
          padding: '12px 20px', borderTop: '1px solid var(--bd)',
          backgroundColor: 'var(--bg-raised)', borderRadius: '0 0 8px 8px',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0,
        }}>
          {/* Prev / Next — landlord only */}
          {!isRealtor && allLeads && currentIdx !== null ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
              <button className="btn-ghost" style={{ fontSize: '11px', padding: '4px 10px', opacity: currentIdx <= 0 ? 0.3 : 1 }}
                disabled={currentIdx <= 0} onClick={() => setCurrentIdx(i => i - 1)}>
                <ChevronLeft size={12} /> Prev
              </button>
              <span style={{ fontSize: '11px', color: 'var(--tx-4)', padding: '0 6px' }}>
                {currentIdx + 1} / {allLeads.length}
              </span>
              <button className="btn-ghost" style={{ fontSize: '11px', padding: '4px 10px', opacity: currentIdx >= allLeads.length - 1 ? 0.3 : 1 }}
                disabled={currentIdx >= allLeads.length - 1} onClick={() => setCurrentIdx(i => i + 1)}>
                Next <ChevronRight size={12} />
              </button>
            </div>
          ) : <div />}

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <button className="btn-ghost" style={{ fontSize: '12px' }} onClick={onClose}>Close</button>
            <button
              className="btn-ghost"
              style={{ fontSize: '12px', color: sendMode ? 'var(--gold)' : 'var(--tx-3)', borderColor: sendMode ? 'var(--gold-border)' : 'transparent' }}
              onClick={() => sendMode ? setSendMode(false) : openSendMode()}
            >
              <Send size={12} /> Send Letter
            </button>
            <button
              className={copied ? undefined : 'btn-gold'}
              style={copied ? {
                display: 'inline-flex', alignItems: 'center', gap: '6px',
                padding: '6px 16px', borderRadius: '4px', fontSize: '12px', fontWeight: 500, cursor: 'pointer',
                backgroundColor: 'var(--b-green-bg)', color: 'var(--b-green-tx)', border: '1px solid var(--b-green-bd)',
              } : { fontSize: '12px', padding: '6px 16px' }}
              onClick={handleCopy}
            >
              {copied ? <><Check size={13} /> Copied</> : <><Copy size={13} /> Copy to Clipboard</>}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

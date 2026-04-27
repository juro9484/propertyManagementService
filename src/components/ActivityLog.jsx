import { useState, useEffect } from 'react'
import { Activity, Mail, ArrowRight, Clock } from 'lucide-react'

function timeAgo(dateStr) {
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}

const ACTION_CFG = {
  status_change:   { label: 'Status change', color: 'var(--b-blue-tx)' },
  email_generated: { label: 'Email generated', color: 'var(--b-purple-tx)' },
  letter_sent:     { label: 'Letter sent', color: 'var(--b-green-tx)' },
  note:            { label: 'Note', color: 'var(--tx-3)' },
}

const RANGES = [
  { label: '7 days', value: 7 },
  { label: '30 days', value: 30 },
  { label: '90 days', value: 90 },
  { label: 'All time', value: 365 },
]

export default function ActivityLog() {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [days, setDays]       = useState(30)

  const API_BASE = import.meta.env.VITE_API_URL || ''
  const headers = {
    Authorization: `Bearer ${localStorage.getItem('acpm_token')}`,
  }

  useEffect(() => {
    setLoading(true)
    fetch(`${API_BASE}/api/analytics/usage?days=${days}`, { headers })
      .then(r => r.json())
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [days])

  if (loading) return <div style={{ padding: '40px', textAlign: 'center', color: 'var(--tx-4)', fontSize: '12px' }}>Loading analytics...</div>
  if (!data) return <div style={{ padding: '40px', textAlign: 'center', color: 'var(--tx-4)', fontSize: '12px' }}>Failed to load</div>

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>

      {/* Time range selector */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span style={{ fontSize: '11px', color: 'var(--tx-4)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Range</span>
        {RANGES.map(r => (
          <button
            key={r.value}
            onClick={() => setDays(r.value)}
            style={{
              fontSize: '11px', padding: '3px 10px', borderRadius: '3px', cursor: 'pointer',
              backgroundColor: days === r.value ? 'var(--gold-bg)' : 'transparent',
              color: days === r.value ? 'var(--gold)' : 'var(--tx-4)',
              border: `1px solid ${days === r.value ? 'var(--gold-border)' : 'var(--bd)'}`,
              fontWeight: days === r.value ? 600 : 400,
            }}
          >
            {r.label}
          </button>
        ))}
      </div>

      {/* User stats */}
      <div className="panel" style={{ padding: '20px' }}>
        <h3 style={{ fontSize: '13px', fontWeight: 600, color: 'var(--tx-1)', margin: '0 0 14px' }}>
          Team Usage
        </h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '12px' }}>
          {data.user_stats.map(u => {
            const stats = [
              { label: 'Emails', value: u.emails_generated, color: 'var(--b-purple-tx)' },
              { label: 'Contacted', value: u.marked_contacted, color: 'var(--b-blue-tx)' },
              { label: 'Follow Up', value: u.marked_follow_up, color: 'var(--b-amber-tx)' },
              { label: 'Meeting', value: u.marked_meeting, color: 'var(--b-purple-tx)' },
              { label: 'Converted', value: u.marked_converted, color: 'var(--b-green-tx)' },
              { label: 'Not Interested', value: u.marked_not_interested, color: 'var(--b-red-tx)' },
            ].filter(s => s.value > 0)

            return (
              <div key={u.id} style={{ backgroundColor: 'var(--bg-raised)', border: '1px solid var(--bd)', borderRadius: '6px', padding: '14px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '10px' }}>
                  <div>
                    <p style={{ fontSize: '13px', fontWeight: 600, color: 'var(--tx-1)', margin: 0 }}>{u.name}</p>
                    <p style={{ fontSize: '10px', color: 'var(--tx-4)', margin: '2px 0 0' }}>{u.email}</p>
                  </div>
                  {u.last_login && (
                    <span style={{ fontSize: '10px', color: 'var(--tx-4)', display: 'flex', alignItems: 'center', gap: '3px' }}>
                      <Clock size={9} /> {timeAgo(u.last_login)}
                    </span>
                  )}
                </div>
                {stats.length > 0 ? (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                    {stats.map(s => (
                      <div key={s.label} style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '11px' }}>
                        <span style={{ fontWeight: 700, color: s.color }}>{s.value}</span>
                        <span style={{ color: 'var(--tx-4)' }}>{s.label}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p style={{ fontSize: '11px', color: 'var(--tx-4)', margin: 0, fontStyle: 'italic' }}>No activity</p>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* Daily stats */}
      {data.daily_stats.length > 0 && (
        <div className="panel" style={{ padding: '20px' }}>
          <h3 style={{ fontSize: '13px', fontWeight: 600, color: 'var(--tx-1)', margin: '0 0 14px' }}>
            Daily Activity (Last 7 Days)
          </h3>
          <div style={{ display: 'flex', gap: '8px' }}>
            {data.daily_stats.map(d => {
              const day = new Date(d.day).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
              return (
                <div key={d.day} style={{ flex: 1, backgroundColor: 'var(--bg-raised)', border: '1px solid var(--bd)', borderRadius: '6px', padding: '10px', textAlign: 'center' }}>
                  <p style={{ fontSize: '10px', color: 'var(--tx-4)', margin: '0 0 6px' }}>{day}</p>
                  <p style={{ fontSize: '18px', fontWeight: 700, color: 'var(--tx-1)', margin: 0 }}>{d.total_actions}</p>
                  <div style={{ display: 'flex', justifyContent: 'center', gap: '8px', marginTop: '4px' }}>
                    <span style={{ fontSize: '10px', color: 'var(--b-blue-tx)' }}>{d.status_changes} status</span>
                    <span style={{ fontSize: '10px', color: 'var(--b-purple-tx)' }}>{d.emails_generated} emails</span>
                  </div>
                </div>
              )
            })}
          </div>
          <p style={{ fontSize: '11px', color: 'var(--tx-4)', margin: '10px 0 0' }}>
            Total emails generated (all time): {data.total_emails_generated}
          </p>
        </div>
      )}

      {/* Recent activity feed */}
      <div className="panel" style={{ padding: '20px' }}>
        <h3 style={{ fontSize: '13px', fontWeight: 600, color: 'var(--tx-1)', margin: '0 0 14px' }}>
          Recent Activity
        </h3>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          {data.recent_activity.length === 0 ? (
            <p style={{ fontSize: '12px', color: 'var(--tx-4)', textAlign: 'center', padding: '20px' }}>No activity yet</p>
          ) : data.recent_activity.map((a, i) => {
            const cfg = ACTION_CFG[a.action] || ACTION_CFG.note
            return (
              <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: '10px', padding: '8px 0', borderBottom: i < data.recent_activity.length - 1 ? '1px solid var(--bd)' : 'none' }}>
                <div style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: cfg.color, flexShrink: 0, marginTop: '5px' }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: '12px', color: 'var(--tx-2)' }}>
                    <span style={{ fontWeight: 500, color: 'var(--tx-1)' }}>{a.user_name || 'System'}</span>
                    {' '}{cfg.label.toLowerCase()}
                    {a.lead_name && <> on <span style={{ fontWeight: 500 }}>{a.lead_name}</span></>}
                  </div>
                  {a.detail && (
                    <div style={{ fontSize: '11px', color: 'var(--tx-4)', marginTop: '2px' }}>{a.detail}</div>
                  )}
                </div>
                <span style={{ fontSize: '10px', color: 'var(--tx-4)', flexShrink: 0, whiteSpace: 'nowrap' }}>
                  {timeAgo(a.created_at)}
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

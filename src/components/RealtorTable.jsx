import { useState, useMemo } from 'react'
import { Mail, Phone, Search, SlidersHorizontal, Star } from 'lucide-react'

const SCORE_CFG = {
  High:   { bg: 'var(--b-green-bg)',  tx: 'var(--b-green-tx)',  bd: 'var(--b-green-bd)',  dot: 'var(--b-green-tx)'  },
  Medium: { bg: 'var(--b-amber-bg)',  tx: 'var(--b-amber-tx)',  bd: 'var(--b-amber-bd)',  dot: 'var(--b-amber-tx)'  },
  Low:    { bg: 'var(--b-sky-bg)',    tx: 'var(--b-sky-tx)',    bd: 'var(--b-sky-bd)',    dot: 'var(--b-sky-tx)'    },
}

function ScoreBadge({ score }) {
  const c = SCORE_CFG[score] ?? SCORE_CFG.Low
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: '5px',
      padding: '2px 8px', borderRadius: '3px', fontSize: '11px', fontWeight: 500,
      backgroundColor: c.bg, color: c.tx, border: `1px solid ${c.bd}`,
    }}>
      <span style={{ width: '5px', height: '5px', borderRadius: '50%', backgroundColor: c.dot, flexShrink: 0 }} />
      {score}
    </span>
  )
}

const thStyle = {
  textAlign: 'left', padding: '10px 16px',
  fontSize: '10px', fontWeight: 700,
  color: 'var(--tx-3)', textTransform: 'uppercase', letterSpacing: '0.09em',
  backgroundColor: 'var(--bg-raised)', borderBottom: '1px solid var(--bd)',
  whiteSpace: 'nowrap',
}

export default function RealtorTable({ realtors, onOutreach }) {
  const [brokerageFilter, setBrokerageFilter] = useState('')
  const [scoreFilter, setScoreFilter]         = useState('')
  const [search, setSearch]                   = useState('')

  const brokerages = useMemo(() =>
    [...new Set(realtors.map(r => r.brokerage).filter(Boolean))].sort()
  , [realtors])

  const filtered = useMemo(() => {
    let rows = [...realtors]
    if (search) {
      const q = search.toLowerCase()
      rows = rows.filter(r =>
        r.name?.toLowerCase().includes(q) ||
        r.brokerage?.toLowerCase().includes(q) ||
        r.specialties?.some(s => s.toLowerCase().includes(q))
      )
    }
    if (brokerageFilter) rows = rows.filter(r => r.brokerage === brokerageFilter)
    if (scoreFilter)     rows = rows.filter(r => r.score === scoreFilter)
    return rows
  }, [realtors, search, brokerageFilter, scoreFilter])

  const avgListings = filtered.length
    ? Math.round(filtered.reduce((s, r) => s + r.investor_listings, 0) / filtered.length)
    : 0

  return (
    <div className="panel" style={{ overflow: 'hidden' }}>

      {/* Toolbar */}
      <div style={{ padding: '12px 20px', borderBottom: '1px solid var(--bd)', display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
        <div style={{ position: 'relative', flex: '1', maxWidth: '280px' }}>
          <Search size={12} style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: 'var(--tx-4)', pointerEvents: 'none' }} />
          <input className="field" style={{ paddingLeft: '30px', width: '100%' }}
            placeholder="Search name, brokerage, specialty…"
            value={search} onChange={e => setSearch(e.target.value)} />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <SlidersHorizontal size={12} style={{ color: 'var(--tx-4)' }} />
          <select className="field" value={brokerageFilter} onChange={e => setBrokerageFilter(e.target.value)}>
            <option value="">All Brokerages</option>
            {brokerages.map(b => <option key={b}>{b}</option>)}
          </select>
          <select className="field" value={scoreFilter} onChange={e => setScoreFilter(e.target.value)}>
            <option value="">All Tiers</option>
            <option value="High">High</option>
            <option value="Medium">Medium</option>
            <option value="Low">Low</option>
          </select>
        </div>
        <span style={{ fontSize: '11px', color: 'var(--tx-4)', marginLeft: 'auto' }}>
          {filtered.length} prospects
        </span>
      </div>

      {/* Table */}
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={{ ...thStyle, width: '40px' }}>#</th>
              <th style={thStyle}>Agent</th>
              <th style={thStyle}>Brokerage</th>
              <th style={thStyle}>Specialties</th>
              <th style={thStyle}>Inv. Listings</th>
              <th style={thStyle}>Priority</th>
              <th style={thStyle}>Contact</th>
              <th style={{ ...thStyle, width: '100px' }}>Action</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={8} style={{ textAlign: 'center', padding: '56px', fontSize: '13px', color: 'var(--tx-3)' }}>
                  No prospects match the current filters.
                </td>
              </tr>
            ) : filtered.map((r, i) => (
              <tr key={r.id} className="trow">
                <td style={{ padding: '11px 16px', fontSize: '11px', color: 'var(--tx-4)', fontFamily: 'monospace' }}>{i + 1}</td>

                <td style={{ padding: '11px 16px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <div style={{
                      width: '28px', height: '28px', borderRadius: '50%', flexShrink: 0,
                      backgroundColor: 'var(--bg-raised)', border: '1px solid var(--bd)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: '10px', fontWeight: 600, color: 'var(--tx-3)',
                    }}>
                      {r.name?.split(' ').map(n => n[0]).slice(0, 2).join('')}
                    </div>
                    <span style={{ fontSize: '13px', fontWeight: 500, color: 'var(--tx-1)' }}>{r.name}</span>
                  </div>
                </td>

                <td style={{ padding: '11px 16px' }}>
                  <span style={{
                    fontSize: '11px', color: 'var(--tx-2)',
                    backgroundColor: 'var(--bg-raised)', border: '1px solid var(--bd)',
                    padding: '3px 8px', borderRadius: '3px',
                  }}>
                    {r.brokerage}
                  </span>
                </td>

                <td style={{ padding: '11px 16px' }}>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                    {r.specialties?.slice(0, 3).map(s => (
                      <span key={s} style={{
                        fontSize: '10px', color: 'var(--tx-3)',
                        backgroundColor: 'var(--bd-s)', border: '1px solid var(--bd)',
                        padding: '1px 6px', borderRadius: '3px',
                      }}>{s}</span>
                    ))}
                    {r.specialties?.length > 3 && (
                      <span style={{ fontSize: '10px', color: 'var(--tx-4)' }}>+{r.specialties.length - 3}</span>
                    )}
                  </div>
                </td>

                <td style={{ padding: '11px 16px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--tx-1)', fontVariantNumeric: 'tabular-nums' }}>{r.investor_listings}</span>
                    <div style={{ width: '56px', height: '3px', backgroundColor: 'var(--sc-bar)', borderRadius: '2px', overflow: 'hidden' }}>
                      <div style={{
                        height: '100%', borderRadius: '2px',
                        width: `${Math.min((r.investor_listings / 25) * 100, 100)}%`,
                        backgroundColor: r.investor_listings >= 18 ? 'var(--b-green-tx)' : r.investor_listings >= 12 ? 'var(--b-amber-tx)' : 'var(--sc-lo)',
                      }} />
                    </div>
                  </div>
                </td>

                <td style={{ padding: '11px 16px' }}><ScoreBadge score={r.score} /></td>

                <td style={{ padding: '11px 16px' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    <a href={`tel:${r.phone}`} style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '11px', color: 'var(--tx-3)', textDecoration: 'none' }}>
                      <Phone size={10} style={{ color: 'var(--tx-4)' }} />{r.phone}
                    </a>
                    <a href={`mailto:${r.email}`} style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '11px', color: 'var(--tx-3)', textDecoration: 'none' }}>
                      <Mail size={10} style={{ color: 'var(--tx-4)' }} />{r.email}
                    </a>
                  </div>
                </td>

                <td style={{ padding: '11px 16px' }}>
                  <button className="btn-primary" style={{ fontSize: '11px' }} onClick={() => onOutreach(r)}>
                    <Mail size={11} />Contact
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Footer */}
      <div style={{ padding: '10px 20px', borderTop: '1px solid var(--bd)', backgroundColor: 'var(--bg-raised)', display: 'flex', alignItems: 'center', gap: '20px' }}>
        {['High', 'Medium', 'Low'].map(tier => {
          const c = SCORE_CFG[tier]
          return (
            <div key={tier} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: c.dot }} />
              <span style={{ fontSize: '11px', color: 'var(--tx-3)' }}>
                {tier}:{' '}
                <span style={{ fontWeight: 600, color: c.tx }}>
                  {filtered.filter(r => r.score === tier).length}
                </span>
              </span>
            </div>
          )
        })}
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '5px', fontSize: '11px', color: 'var(--tx-3)' }}>
          <Star size={11} style={{ color: 'var(--gold)' }} />
          Avg. listings: <span style={{ fontWeight: 600, color: 'var(--tx-2)', marginLeft: '2px' }}>{avgListings}</span>
        </div>
      </div>
    </div>
  )
}

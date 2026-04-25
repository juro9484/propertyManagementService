import { useState, useMemo, useEffect } from 'react'
import { Mail, MapPin, Home, Search, ChevronDown, ChevronUp } from 'lucide-react'
import 'leaflet/dist/leaflet.css'
import { MapContainer, TileLayer, CircleMarker, useMap } from 'react-leaflet'

const BOULDER_CENTER = [40.015, -105.271]
const TILE_URL   = 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png'
const CARTO_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'

const CITY_CENTERS = {
  boulder:    [40.015, -105.271],
  longmont:   [40.167, -105.102],
  louisville: [39.978, -105.131],
  lafayette:  [39.993, -105.089],
  superior:   [39.952, -105.169],
  erie:       [40.050, -105.048],
  broomfield: [39.921, -105.087],
}

function baseAddress(addr) {
  return (addr ?? '').toUpperCase().replace(/\s+(#|APT|UNIT|STE|SUITE|FL|FLOOR)\b.*/g, '').trim()
}

function resolvePropCoords(prop) {
  if (prop.lat != null && prop.lng != null) return [prop.lat, prop.lng]
  const center = CITY_CENTERS[(prop.city ?? '').toLowerCase()]
  if (!center) return null
  const seed = parseInt(prop.folio) || 0
  const jLat = ((seed % 83) / 83 - 0.5) * 0.06
  const jLng = (((seed * 13) % 97) / 97 - 0.5) * 0.08
  return [center[0] + jLat, center[1] + jLng]
}

// Returns unique properties for a lead (deduped by base address)
function uniqueLeadProps(lead) {
  const seen = new Set()
  return (lead.all_properties?.length ? lead.all_properties : [lead]).filter(p => {
    const k = baseAddress(p.address ?? p.property_address)
    return seen.has(k) ? false : (seen.add(k), true)
  })
}

// True only when ALL unique props have real lat/lng from the pipeline
function hasRealCoords(lead) {
  return uniqueLeadProps(lead).every(p => p.lat != null && p.lng != null)
}

function pinColor(score) {
  if (score >= 15) return '#22c55e'
  if (score >= 11) return '#f59e0b'
  if (score >= 7)  return '#38bdf8'
  return '#94a3b8'
}

// Flies/fits the map to the selected lead's coords whenever selection changes
function MapController({ coords, theme }) {
  const map = useMap()

  useEffect(() => {
    if (!coords || coords.length === 0) {
      map.flyTo(BOULDER_CENTER, 11, { duration: 0.8 })
      return
    }
    if (coords.length === 1) {
      map.flyTo(coords[0], 15, { duration: 0.8 })
    } else {
      map.flyToBounds(coords, { padding: [44, 44], duration: 0.8 })
    }
  }, [coords, map])

  useEffect(() => {
    setTimeout(() => map.invalidateSize(), 50)
  }, [theme, map])

  return null
}

// ── Status system ────────────────────────────────────────────────────────────
const LS_KEY = 'acpm_lead_status'
function loadStatuses() {
  try { return JSON.parse(localStorage.getItem(LS_KEY) ?? '{}') } catch { return {} }
}

const STATUS_CFG = {
  new:       { label: 'New',       bg: 'var(--bd-s)',       tx: 'var(--tx-4)',      bd: 'var(--bd)'         },
  contacted: { label: 'Contacted', bg: 'var(--b-blue-bg)',  tx: 'var(--b-blue-tx)', bd: 'var(--b-blue-bd)'  },
  replied:   { label: 'Replied',   bg: 'var(--b-green-bg)', tx: 'var(--b-green-tx)',bd: 'var(--b-green-bd)' },
}
const STATUS_CYCLE = ['new', 'contacted', 'replied']

// ── Badge system ─────────────────────────────────────────────────────────────
const BADGE_CFG = {
  NEW_OWNER:    { label: 'New Owner',    bg: 'var(--b-green-bg)',  tx: 'var(--b-green-tx)',  bd: 'var(--b-green-bd)'  },
  LLC:          { label: 'LLC / Entity', bg: 'var(--b-blue-bg)',   tx: 'var(--b-blue-tx)',   bd: 'var(--b-blue-bd)'   },
  ABSENTEE:     { label: 'Absentee',     bg: 'var(--b-amber-bg)',  tx: 'var(--b-amber-tx)',  bd: 'var(--b-amber-bd)'  },
  OUT_OF_STATE: { label: 'Out of State', bg: 'var(--b-red-bg)',    tx: 'var(--b-red-tx)',    bd: 'var(--b-red-bd)'    },
  PORTFOLIO:    { label: 'Portfolio',    bg: 'var(--b-purple-bg)', tx: 'var(--b-purple-tx)', bd: 'var(--b-purple-bd)' },
  MULTI_PROP:   { label: 'Multi-prop',   bg: 'var(--b-sky-bg)',    tx: 'var(--b-sky-tx)',    bd: 'var(--b-sky-bd)'    },
}

function Badge({ type }) {
  const c = BADGE_CFG[type]
  if (!c) return null
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center',
      padding: '1px 6px', borderRadius: '3px',
      fontSize: '10px', fontWeight: 500,
      backgroundColor: c.bg, color: c.tx,
      border: `1px solid ${c.bd}`, whiteSpace: 'nowrap',
    }}>
      {c.label}
    </span>
  )
}

// ── Left panel: compact lead card ────────────────────────────────────────────
function LeadCard({ lead, selected, statuses, onSelect, onStatusChange }) {
  const status    = statuses[lead.folio] ?? 'new'
  const sc        = STATUS_CFG[status]
  const nextStatus = STATUS_CYCLE[(STATUS_CYCLE.indexOf(status) + 1) % STATUS_CYCLE.length]
  const scoreColor = pinColor(lead.score)

  return (
    <div
      onClick={onSelect}
      style={{
        padding: '11px 14px',
        cursor: 'pointer',
        borderBottom: '1px solid var(--bd)',
        backgroundColor: selected ? 'var(--bg-hover)' : 'transparent',
        borderLeft: `3px solid ${selected ? 'var(--gold)' : 'transparent'}`,
        transition: 'background-color 0.1s',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div style={{ flex: 1, minWidth: 0, marginRight: '10px' }}>
          <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--tx-1)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {lead.owner_name}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--tx-4)', marginTop: '2px' }}>
            {lead.city}{lead.property_count > 1 ? ` · ${lead.property_count} props` : ''}
          </div>
        </div>
        <div style={{ textAlign: 'right', flexShrink: 0 }}>
          <div style={{ fontSize: '15px', fontWeight: 700, color: scoreColor, lineHeight: 1 }}>{lead.score}</div>
          <div style={{ fontSize: '10px', color: 'var(--tx-4)', marginTop: '2px' }}>#{lead.rank}</div>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '4px', flexWrap: 'wrap', marginTop: '8px' }}>
        {lead.badges?.slice(0, 3).map(b => <Badge key={b} type={b} />)}
        <button
          onClick={e => { e.stopPropagation(); onStatusChange(lead.folio, nextStatus) }}
          title={`Click to mark as "${nextStatus}"`}
          style={{
            marginLeft: 'auto', display: 'inline-flex', alignItems: 'center',
            padding: '2px 8px', borderRadius: '3px', fontSize: '10px', fontWeight: 500,
            cursor: 'pointer', backgroundColor: sc.bg, color: sc.tx,
            border: `1px solid ${sc.bd}`, whiteSpace: 'nowrap',
          }}
        >
          {sc.label}
        </button>
      </div>
    </div>
  )
}

// ── Right panel: detail drawer ───────────────────────────────────────────────
function DetailPanel({ lead, onOutreach }) {
  if (!lead) return (
    <div style={{ height: '300px', display: 'flex', alignItems: 'center', justifyContent: 'center', borderTop: '1px solid var(--bd)', backgroundColor: 'var(--bg-surface)' }}>
      <span style={{ fontSize: '13px', color: 'var(--tx-4)' }}>Select a lead to view details</span>
    </div>
  )

  const scoreColor = pinColor(lead.score)

  return (
    <div style={{ height: '300px', overflowY: 'auto', borderTop: '1px solid var(--bd)', backgroundColor: 'var(--bg-surface)', padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: '12px' }}>

      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <h2 style={{ fontSize: '15px', fontWeight: 700, color: 'var(--tx-1)', margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {lead.owner_name}
          </h2>
          <p style={{ fontSize: '11px', color: 'var(--tx-3)', margin: '3px 0 0' }}>
            {lead.property_address}, {lead.city}
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '4px', marginLeft: '16px', flexShrink: 0 }}>
          <span style={{ fontSize: '26px', fontWeight: 700, color: scoreColor, lineHeight: 1 }}>{lead.score}</span>
          <span style={{ fontSize: '11px', color: 'var(--tx-3)' }}>pts</span>
        </div>
      </div>

      {/* Badges */}
      {lead.badges?.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '5px' }}>
          {lead.badges.map(b => <Badge key={b} type={b} />)}
        </div>
      )}

      {/* 3-column grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '20px', flex: 1 }}>

        {/* Properties */}
        <div>
          <p style={{ fontSize: '10px', fontWeight: 700, color: 'var(--tx-3)', textTransform: 'uppercase', letterSpacing: '0.09em', margin: '0 0 8px' }}>
            Properties ({lead.property_count})
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
            {(lead.all_properties ?? [lead]).map((p, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: '6px' }}>
                <Home size={9} style={{ color: 'var(--tx-4)', flexShrink: 0, marginTop: '2px' }} />
                <span style={{ fontSize: '11px', color: 'var(--tx-2)', lineHeight: 1.35 }}>
                  {p.address ?? p.property_address}{p.city ? `, ${p.city}` : ''}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Score breakdown */}
        <div>
          <p style={{ fontSize: '10px', fontWeight: 700, color: 'var(--tx-3)', textTransform: 'uppercase', letterSpacing: '0.09em', margin: '0 0 8px' }}>
            Score Breakdown
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            {Object.entries(lead.score_breakdown ?? {}).map(([k, v]) => (
              <div key={k} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '11px', color: 'var(--tx-3)', textTransform: 'capitalize' }}>{k.replace(/_/g, ' ')}</span>
                <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--sc-lo)' }}>+{v}</span>
              </div>
            ))}
            <div style={{ display: 'flex', justifyContent: 'space-between', paddingTop: '5px', borderTop: '1px solid var(--bd)', marginTop: '2px' }}>
              <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--tx-2)' }}>Total</span>
              <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--tx-1)' }}>{lead.score}</span>
            </div>
          </div>
        </div>

        {/* Record details + outreach */}
        <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
          <div>
            <p style={{ fontSize: '10px', fontWeight: 700, color: 'var(--tx-3)', textTransform: 'uppercase', letterSpacing: '0.09em', margin: '0 0 8px' }}>
              Record Details
            </p>
            <dl style={{ margin: 0, display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {lead.mailing_address && (
                <div>
                  <dt style={{ fontSize: '10px', color: 'var(--tx-4)', display: 'flex', alignItems: 'center', gap: '3px', marginBottom: '2px' }}>
                    <MapPin size={9} /> Mailing
                  </dt>
                  <dd style={{ fontSize: '11px', color: 'var(--tx-2)', margin: 0, lineHeight: 1.35 }}>{lead.mailing_address}</dd>
                </div>
              )}
              {lead.mailing_state && (
                <div>
                  <dt style={{ fontSize: '10px', color: 'var(--tx-4)', marginBottom: '2px' }}>Mail State</dt>
                  <dd style={{ margin: 0 }}>
                    <span style={{
                      fontSize: '11px', fontWeight: 600, padding: '1px 6px', borderRadius: '3px',
                      backgroundColor: lead.mailing_state === 'CO' ? 'var(--bg-raised)' : 'var(--b-red-bg)',
                      color: lead.mailing_state === 'CO' ? 'var(--tx-3)' : 'var(--b-red-tx)',
                      border: `1px solid ${lead.mailing_state === 'CO' ? 'var(--bd)' : 'var(--b-red-bd)'}`,
                    }}>
                      {lead.mailing_state}
                    </span>
                  </dd>
                </div>
              )}
              {lead.tax_area && (
                <div>
                  <dt style={{ fontSize: '10px', color: 'var(--tx-4)', marginBottom: '2px' }}>Tax Area</dt>
                  <dd style={{ fontSize: '11px', color: 'var(--tx-2)', margin: 0 }}>{lead.tax_area}</dd>
                </div>
              )}
            </dl>
          </div>

          <button
            className="btn-gold"
            style={{ width: '100%', justifyContent: 'center', padding: '8px', marginTop: '12px' }}
            onClick={() => onOutreach(lead)}
          >
            <Mail size={11} />
            Draft Outreach Letter
          </button>
        </div>

      </div>
    </div>
  )
}

// ── Main component ───────────────────────────────────────────────────────────
const PAGE_SIZE = 20

export default function LandlordTable({ leads, onOutreach, theme }) {
  const [selectedFolio, setSelectedFolio] = useState(() => leads[0]?.folio ?? null)
  const [sortDir, setSortDir]             = useState('desc')
  const [cityFilter, setCityFilter]       = useState('')
  const [minScore, setMinScore]           = useState(0)
  const [search, setSearch]               = useState('')
  const [page, setPage]                   = useState(1)
  const [statuses, setStatuses]           = useState(loadStatuses)
  const [statusFilter, setStatusFilter]   = useState('')

  useEffect(() => {
    if (!selectedFolio && leads.length > 0) setSelectedFolio(leads[0].folio)
  }, [leads])

  const handleStatusChange = (folio, next) => {
    const updated = { ...statuses, [folio]: next }
    setStatuses(updated)
    localStorage.setItem(LS_KEY, JSON.stringify(updated))
  }

  const cities = useMemo(() => [...new Set(leads.map(l => l.city).filter(Boolean))].sort(), [leads])

  const filtered = useMemo(() => {
    let rows = [...leads]
    if (search) {
      const q = search.toLowerCase()
      rows = rows.filter(l =>
        l.owner_name?.toLowerCase().includes(q) ||
        l.property_address?.toLowerCase().includes(q) ||
        l.city?.toLowerCase().includes(q)
      )
    }
    if (cityFilter)   rows = rows.filter(l => l.city === cityFilter)
    if (minScore)     rows = rows.filter(l => l.score >= minScore)
    if (statusFilter) rows = rows.filter(l => (statuses[l.folio] ?? 'new') === statusFilter)
    rows.sort((a, b) => sortDir === 'desc' ? b.score - a.score : a.score - b.score)
    return rows
  }, [leads, search, cityFilter, minScore, sortDir, statusFilter, statuses])

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE)
  const paginated  = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
  const resetPage  = () => setPage(1)

  // Selected lead (always looked up from full leads array, not filtered)
  const selected = leads.find(l => l.folio === selectedFolio) ?? null

  const selectedCoords   = useMemo(() => selected ? uniqueLeadProps(selected).map(resolvePropCoords).filter(Boolean) : null, [selected])
  const selectedApprox   = selected ? !hasRealCoords(selected) : false

  // One background pin per lead (primary property)
  const allPins = useMemo(() =>
    leads.map(l => ({ folio: l.folio, score: l.score, coords: resolvePropCoords(l) })).filter(p => p.coords)
  , [leads])

  return (
    <div className="panel" style={{ display: 'flex', height: 'calc(100vh - 430px)', minHeight: '640px', overflow: 'hidden' }}>

      {/* ── Left panel ── */}
      <div style={{ width: '380px', flexShrink: 0, display: 'flex', flexDirection: 'column', borderRight: '1px solid var(--bd)', overflow: 'hidden' }}>

        {/* Toolbar */}
        <div style={{ padding: '10px 12px', borderBottom: '1px solid var(--bd)', display: 'flex', flexDirection: 'column', gap: '7px', flexShrink: 0 }}>
          <div style={{ position: 'relative' }}>
            <Search size={11} style={{ position: 'absolute', left: '9px', top: '50%', transform: 'translateY(-50%)', color: 'var(--tx-4)', pointerEvents: 'none' }} />
            <input
              className="field"
              style={{ paddingLeft: '28px', width: '100%', fontSize: '12px' }}
              placeholder="Search owner, address, city…"
              value={search}
              onChange={e => { setSearch(e.target.value); resetPage() }}
            />
          </div>

          <div style={{ display: 'flex', gap: '5px' }}>
            <select className="field" style={{ flex: 1, minWidth: 0, fontSize: '11px' }} value={cityFilter} onChange={e => { setCityFilter(e.target.value); resetPage() }}>
              <option value="">All Cities</option>
              {cities.map(c => <option key={c}>{c}</option>)}
            </select>
            <select className="field" style={{ flex: 1, minWidth: 0, fontSize: '11px' }} value={minScore} onChange={e => { setMinScore(Number(e.target.value)); resetPage() }}>
              <option value={0}>Any Score</option>
              <option value={5}>5+</option>
              <option value={8}>8+</option>
              <option value={11}>11+</option>
              <option value={14}>14+</option>
            </select>
            <select className="field" style={{ flex: 1, minWidth: 0, fontSize: '11px' }} value={statusFilter} onChange={e => { setStatusFilter(e.target.value); resetPage() }}>
              <option value="">All</option>
              <option value="new">New</option>
              <option value="contacted">Contacted</option>
              <option value="replied">Replied</option>
            </select>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '11px', color: 'var(--tx-4)' }}>{filtered.length} records</span>
            <button
              style={{ fontSize: '10px', color: 'var(--tx-3)', background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '3px', padding: 0 }}
              onClick={() => { setSortDir(d => d === 'desc' ? 'asc' : 'desc'); resetPage() }}
            >
              Score {sortDir === 'desc' ? <ChevronDown size={10} /> : <ChevronUp size={10} />}
            </button>
          </div>
        </div>

        {/* Lead cards */}
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {paginated.length === 0 ? (
            <div style={{ padding: '48px 16px', textAlign: 'center', fontSize: '12px', color: 'var(--tx-4)' }}>
              No records match filters.
            </div>
          ) : paginated.map(lead => (
            <LeadCard
              key={lead.folio}
              lead={lead}
              selected={selectedFolio === lead.folio}
              statuses={statuses}
              onSelect={() => setSelectedFolio(lead.folio)}
              onStatusChange={handleStatusChange}
            />
          ))}
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div style={{ padding: '8px 12px', borderTop: '1px solid var(--bd)', backgroundColor: 'var(--bg-raised)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
            <button className="btn-ghost" style={{ padding: '3px 9px', fontSize: '11px', opacity: page === 1 ? 0.3 : 1 }} disabled={page === 1} onClick={() => setPage(p => p - 1)}>Prev</button>
            <span style={{ fontSize: '11px', color: 'var(--tx-4)' }}>{page} / {totalPages}</span>
            <button className="btn-ghost" style={{ padding: '3px 9px', fontSize: '11px', opacity: page === totalPages ? 0.3 : 1 }} disabled={page === totalPages} onClick={() => setPage(p => p + 1)}>Next</button>
          </div>
        )}
      </div>

      {/* ── Right panel: map + detail ── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

        {/* Persistent map — never unmounts, just flies to new selection */}
        <div style={{ flex: 1, position: 'relative' }}>
          {selectedApprox && (
            <div style={{ position: 'absolute', bottom: '10px', left: '50%', transform: 'translateX(-50%)', zIndex: 1000, backgroundColor: 'rgba(0,0,0,0.65)', color: '#f59e0b', fontSize: '11px', padding: '4px 12px', borderRadius: '4px', pointerEvents: 'none', whiteSpace: 'nowrap', backdropFilter: 'blur(4px)' }}>
              Approximate location — run pipeline for exact coordinates
            </div>
          )}
          <MapContainer
            center={BOULDER_CENTER}
            zoom={11}
            style={{ height: '100%', width: '100%' }}
            scrollWheelZoom
            zoomControl
          >
            <TileLayer url={TILE_URL} attribution={CARTO_ATTR} />
            <MapController coords={selectedCoords} theme={theme} />

            {/* Background pins — all non-selected leads */}
            {allPins
              .filter(p => String(p.folio) !== String(selectedFolio))
              .map(({ folio, score, coords }) => (
                <CircleMarker
                  key={folio}
                  center={coords}
                  radius={6}
                  pathOptions={{ color: 'transparent', fillColor: pinColor(score), fillOpacity: 0.45, weight: 0 }}
                  eventHandlers={{ click: () => setSelectedFolio(folio) }}
                />
              ))
            }

            {/* Selected lead — bright gold pins for each unique property */}
            {selectedCoords?.map((c, i) => (
              <CircleMarker
                key={`sel-${i}`}
                center={c}
                radius={10}
                pathOptions={{ color: '#fff', fillColor: '#f59e0b', fillOpacity: 0.95, weight: 2 }}
              />
            ))}
          </MapContainer>
        </div>

        {/* Detail drawer */}
        <DetailPanel lead={selected} onOutreach={onOutreach} />
      </div>
    </div>
  )
}

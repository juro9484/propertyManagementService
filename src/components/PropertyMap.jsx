import 'leaflet/dist/leaflet.css'
import { MapContainer, TileLayer, CircleMarker, Popup } from 'react-leaflet'

const BOULDER_CENTER = [40.015, -105.271]

const TILE_DARK  = 'https://{s}.basemaps.cartocdn.com/dark_matter/{z}/{x}/{y}{r}.png'
const TILE_LIGHT = 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png'
const CARTO_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'

// City center coordinates — fallback when no geocoded coords available
const CITY_CENTERS = {
  boulder:        [40.015, -105.271],
  longmont:       [40.167, -105.102],
  louisville:     [39.978, -105.131],
  lafayette:      [39.993, -105.089],
  superior:       [39.952, -105.169],
  erie:           [40.050, -105.048],
  broomfield:     [39.921, -105.087],
  lyons:          [40.224, -105.271],
  nederland:      [39.961, -105.510],
  unincorporated: [40.050, -105.300],
}

function resolveCoords(lead) {
  // Check geocoded coords on all_properties first
  const props = lead.all_properties || []
  for (const p of props) {
    if (p.lat != null && p.lng != null) return [p.lat, p.lng]
  }
  // Lead-level coords
  if (lead.lat != null && lead.lng != null) return [lead.lat, lead.lng]
  // City center fallback with jitter
  const city = (lead.city || '').toLowerCase()
  const center = CITY_CENTERS[city]
  if (!center) return null
  const seed = parseInt(lead.folio || lead.id) || 0
  const jLat = ((seed % 83) / 83 - 0.5) * 0.06
  const jLng = (((seed * 13) % 97) / 97 - 0.5) * 0.08
  return [center[0] + jLat, center[1] + jLng]
}

function pinColor(score) {
  if (score >= 15) return '#22c55e'
  if (score >= 11) return '#f59e0b'
  if (score >= 7)  return '#38bdf8'
  return '#94a3b8'
}

const LEGEND = [
  { label: 'High  (15+)',   color: '#22c55e' },
  { label: 'Mid   (11–14)', color: '#f59e0b' },
  { label: 'Fair  (7–10)',  color: '#38bdf8' },
  { label: 'Low   (<7)',    color: '#94a3b8' },
]

const BADGE_LABELS = {
  NEW_OWNER:    'New Owner',
  LLC:          'LLC',
  ABSENTEE:     'Absentee',
  OUT_OF_STATE: 'Out of State',
  PORTFOLIO:    'Portfolio',
  MULTI_PROP:   'Multi-prop',
}

export default function PropertyMap({ leads, theme }) {
  const mappable = leads
    .map(l => ({ ...l, _coords: resolveCoords(l) }))
    .filter(l => l._coords !== null)

  const tileUrl   = theme === 'dark' ? TILE_DARK : TILE_LIGHT
  const legendBg  = theme === 'dark' ? 'rgba(11,21,37,0.94)' : 'rgba(255,255,255,0.94)'
  const popupBase = theme === 'dark' ? '#1a2d45' : '#0f1d2e'

  return (
    <div className="panel" style={{ overflow: 'hidden', position: 'relative' }}>

      {/* Floating legend — sits above the map */}
      <div style={{
        position: 'absolute', top: '56px', right: '12px', zIndex: 1000,
        backgroundColor: legendBg,
        border: '1px solid var(--bd)', borderRadius: '6px',
        padding: '12px 16px', backdropFilter: 'blur(10px)',
        display: 'flex', flexDirection: 'column', gap: '8px', minWidth: '152px',
      }}>
        <p style={{ fontSize: '10px', fontWeight: 700, color: 'var(--tx-3)', textTransform: 'uppercase', letterSpacing: '0.09em', margin: 0 }}>
          Lead Score
        </p>
        {LEGEND.map(({ label, color }) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: '9px' }}>
            <span style={{ width: '10px', height: '10px', borderRadius: '50%', backgroundColor: color, flexShrink: 0 }} />
            <span style={{ fontSize: '11px', color: 'var(--tx-2)', fontVariantNumeric: 'tabular-nums' }}>{label}</span>
          </div>
        ))}
        <div style={{ marginTop: '2px', paddingTop: '8px', borderTop: '1px solid var(--bd)', fontSize: '11px', color: 'var(--tx-4)' }}>
          {mappable.length} leads plotted
        </div>
      </div>

      {/* key={theme} forces remount so tile layer swaps on theme toggle */}
      <MapContainer
        key={theme}
        center={BOULDER_CENTER}
        zoom={11}
        style={{ height: '640px', width: '100%' }}
        scrollWheelZoom
        zoomControl
      >
        <TileLayer attribution={CARTO_ATTR} url={tileUrl} />

        {mappable.map(lead => (
          <CircleMarker
            key={lead.folio}
            center={lead._coords}
            radius={lead.property_count >= 5 ? 11 : lead.property_count >= 3 ? 9 : 7}
            pathOptions={{
              color: 'rgba(255,255,255,0.55)',
              fillColor: pinColor(lead.score),
              fillOpacity: 0.88,
              weight: 1.5,
            }}
          >
            <Popup>
              <div style={{ minWidth: '210px', fontFamily: 'system-ui, -apple-system, sans-serif', color: popupBase }}>
                <div style={{ fontWeight: 700, fontSize: '13px', marginBottom: '3px', lineHeight: 1.3 }}>
                  {lead.owner_name}
                </div>
                <div style={{ fontSize: '11px', color: '#6b7280', marginBottom: '10px' }}>
                  {lead.property_address}, {lead.city}
                </div>
                <div style={{ display: 'flex', gap: '16px', fontSize: '12px', marginBottom: '8px' }}>
                  <div>
                    <span style={{ color: '#9ca3af', fontSize: '10px', display: 'block', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Score</span>
                    <span style={{ fontWeight: 700, color: pinColor(lead.score) }}>{lead.score}</span>
                  </div>
                  <div>
                    <span style={{ color: '#9ca3af', fontSize: '10px', display: 'block', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Properties</span>
                    <span style={{ fontWeight: 700 }}>{lead.property_count}</span>
                  </div>
                  <div>
                    <span style={{ color: '#9ca3af', fontSize: '10px', display: 'block', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Mail State</span>
                    <span style={{ fontWeight: 700 }}>{lead.mailing_state || '—'}</span>
                  </div>
                </div>
                {lead.badges?.length > 0 && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                    {lead.badges.map(b => (
                      <span key={b} style={{
                        fontSize: '10px', padding: '1px 6px', borderRadius: '3px',
                        backgroundColor: '#f3f4f6', color: '#374151', border: '1px solid #e5e7eb',
                      }}>
                        {BADGE_LABELS[b] ?? b}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </Popup>
          </CircleMarker>
        ))}
      </MapContainer>
    </div>
  )
}

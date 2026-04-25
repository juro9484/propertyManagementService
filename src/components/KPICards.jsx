import { useEffect, useRef, useState } from 'react'

function useCountUp(target, duration = 1000) {
  const [display, setDisplay] = useState(0)
  const prev = useRef(0)
  useEffect(() => {
    if (target === prev.current) return
    const start = prev.current
    const diff  = target - start
    const t0    = performance.now()
    const step  = (now) => {
      const p    = Math.min((now - t0) / duration, 1)
      const ease = 1 - Math.pow(1 - p, 3)
      setDisplay(Number.isInteger(target) ? Math.round(start + diff * ease) : parseFloat((start + diff * ease).toFixed(1)))
      if (p < 1) requestAnimationFrame(step)
      else prev.current = target
    }
    requestAnimationFrame(step)
  }, [target, duration])
  return display
}

const STATS = [
  { key: 'totalLandlords', label: 'Landlord Leads'   },
  { key: 'newOwnerEvents', label: 'New Owner Events'  },
  { key: 'totalRealtors',  label: 'Realtor Prospects' },
  { key: 'avgScore',       label: 'Avg Lead Score', suffix: 'pts' },
]

function Stat({ label, suffix, value }) {
  const display = useCountUp(value)
  return (
    <div style={{ flex: 1, padding: '14px 24px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
      <span style={{ fontSize: '22px', fontWeight: 600, color: 'var(--tx-1)', fontVariantNumeric: 'tabular-nums', lineHeight: 1, letterSpacing: '-0.02em' }}>
        {display}{suffix && <span style={{ fontSize: '12px', fontWeight: 400, color: 'var(--tx-4)', marginLeft: '4px' }}>{suffix}</span>}
      </span>
      <span style={{ fontSize: '11px', color: 'var(--tx-4)', letterSpacing: '0.02em' }}>{label}</span>
    </div>
  )
}

function SkeletonStat() {
  return (
    <div style={{ flex: 1, padding: '14px 24px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
      <div style={{ height: '22px', width: '48px', backgroundColor: 'var(--bd)', borderRadius: '3px' }} />
      <div style={{ height: '11px', width: '96px', backgroundColor: 'var(--bd-s)', borderRadius: '3px' }} />
    </div>
  )
}

export default function KPICards({ totalLandlords, newOwnerEvents, totalRealtors, avgScore, loading }) {
  const values = { totalLandlords, newOwnerEvents, totalRealtors, avgScore }

  return (
    <div className="panel" style={{ display: 'flex', overflow: 'hidden' }}>
      {STATS.map((s, i) => (
        <div key={s.key} style={{ flex: 1, display: 'flex', borderLeft: i > 0 ? '1px solid var(--bd)' : 'none' }}>
          {loading
            ? <SkeletonStat />
            : <Stat label={s.label} suffix={s.suffix} value={values[s.key]} />
          }
        </div>
      ))}
    </div>
  )
}

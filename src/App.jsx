import { useState, useEffect } from 'react'
import { RefreshCw, AlertCircle, Sun, Moon, LogOut } from 'lucide-react'
import KPICards from './components/KPICards'
import LandlordTable from './components/LandlordTable'
import PropertyMap from './components/PropertyMap'
import OutreachModal from './components/OutreachModal'
import LoginPage from './components/LoginPage'
import UserManagement from './components/UserManagement'
import { sampleLandlordData } from './sampleData'

const TABS = [
  { label: 'Leads' },
  { label: 'Property Map' },
  { label: 'Settings', adminOnly: true },
]

export default function App() {
  const [user, setUser]                 = useState(() => {
    try { return JSON.parse(localStorage.getItem('acpm_user')) } catch { return null }
  })
  const [token, setToken]               = useState(() => localStorage.getItem('acpm_token'))
  const [landlordData, setLandlordData] = useState(null)
  const [loading, setLoading]           = useState(true)
  const [usingMock, setUsingMock]       = useState(false)
  const [activeTab, setActiveTab]       = useState(0)
  const [modal, setModal]               = useState(null)
  const [theme, setTheme]               = useState('light')

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  const API_BASE = import.meta.env.VITE_API_URL || ''

  const getAuthHeaders = () => {
    const t = localStorage.getItem('acpm_token')
    return t ? { Authorization: `Bearer ${t}` } : {}
  }

  const handleLogout = () => {
    localStorage.removeItem('acpm_token')
    localStorage.removeItem('acpm_user')
    setUser(null)
    setToken(null)
  }

  const loadData = async () => {
    setLoading(true)
    try {
      const apiRes = await fetch(`${API_BASE}/api/leads?per_page=200&sort=score_desc`, { headers: getAuthHeaders() })
      if (apiRes.status === 401) { handleLogout(); return }
      if (apiRes.ok) {
        const apiData = await apiRes.json()
        setLandlordData({
          generated_at: new Date().toISOString(),
          total_records_processed: apiData.total,
          new_owner_events: apiData.leads.filter(l => l.badges?.includes('NEW_OWNER')).length,
          avg_score: apiData.leads.length
            ? (apiData.leads.reduce((s, l) => s + l.score, 0) / apiData.leads.length).toFixed(1)
            : 0,
          leads: apiData.leads.map((l, i) => ({ ...l, rank: i + 1, folio: l.primary_folio || l.id })),
        })
        setUsingMock(false)
        setLoading(false)
        return
      }
    } catch { /* API not available, fall through */ }

    try {
      const lRes = await fetch(`/data/landlord_leads.json?t=${Date.now()}`)
      if (!lRes.ok) throw new Error('Not found')
      setLandlordData(await lRes.json())
      setUsingMock(false)
    } catch {
      setLandlordData(sampleLandlordData)
      setUsingMock(true)
    } finally {
      setLoading(false)
    }
  }

  const handleLogin = (userData, tokenStr) => {
    setUser(userData)
    setToken(tokenStr)
  }

  // Load data whenever token changes (including after login)
  useEffect(() => {
    if (token) loadData()
  }, [token])

  // Not logged in → show login page
  if (!user || !token) {
    return <LoginPage onLogin={handleLogin} />
  }

  const leads    = landlordData?.leads ?? []
  const enrichedCount = leads.filter(l => l.email || l.phone).length
  const newOwnerCount = leads.filter(l => l.badges?.includes('NEW_OWNER')).length
  const avgScore = leads.length
    ? (leads.reduce((s, l) => s + l.score, 0) / leads.length).toFixed(1)
    : 0

  const runDate = landlordData?.generated_at
    ? new Date(landlordData.generated_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
    : new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })

  const S = {
    topBar: {
      backgroundColor: 'var(--bg-raised)',
      borderBottom: '1px solid var(--bd)',
    },
  }

  return (
    <div style={{ minHeight: '100vh', backgroundColor: 'var(--bg-base)' }}>

      {/* ── Top bar ── */}
      <div style={S.topBar}>
        <div className="max-w-[1600px] mx-auto px-8 h-14 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <img src="/img_55573.png" alt="All County" style={{ height: '36px', width: 'auto', objectFit: 'contain' }} />
            <div>
              <span style={{ fontSize: '14px', fontWeight: 600, color: 'var(--tx-1)' }}>Prospect Pipeline</span>
              <span style={{ color: 'var(--tx-4)', fontSize: '11px', marginLeft: '8px' }}>Boulder County</span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {usingMock && (
              <span className="flex items-center gap-1.5 text-xs" style={{ color: 'var(--gold)' }}>
                <AlertCircle size={11} /> Demo mode
              </span>
            )}
            <span style={{ color: 'var(--tx-4)', fontSize: '11px' }}>{runDate}</span>
            <button
              onClick={() => setTheme(t => t === 'dark' ? 'light' : 'dark')}
              className="btn-ghost"
              style={{ padding: '4px 6px' }}
              title="Toggle theme"
            >
              {theme === 'dark'
                ? <Sun  size={12} style={{ color: 'var(--tx-3)' }} />
                : <Moon size={12} style={{ color: 'var(--tx-3)' }} />}
            </button>
            <button onClick={loadData} disabled={loading} className="btn-ghost" style={{ padding: '4px 6px' }}>
              <RefreshCw size={11} className={loading ? 'animate-spin' : ''} style={{ color: 'var(--tx-3)' }} />
            </button>
            <span style={{ color: 'var(--bd)' }}>|</span>
            <span style={{ fontSize: '11px', color: 'var(--tx-4)' }}>{user?.name}</span>
            <button onClick={handleLogout} className="btn-ghost" style={{ padding: '4px 6px' }} title="Sign out">
              <LogOut size={11} style={{ color: 'var(--tx-3)' }} />
            </button>
          </div>
        </div>
      </div>

      <main className="max-w-[1600px] mx-auto px-6 py-4 space-y-4">

        <KPICards
          totalLandlords={leads.length}
          newOwnerEvents={newOwnerCount}
          totalRealtors={enrichedCount}
          avgScore={Number(avgScore)}
          loading={loading}
        />

        {/* ── Tabs ── */}
        <div style={{ borderBottom: '1px solid var(--bd)', display: 'flex' }}>
          {TABS.map((tab, i) => {
            if (tab.adminOnly && user?.role !== 'admin') return null
            return (
              <button
                key={tab.label}
                onClick={() => setActiveTab(i)}
                style={{
                  padding: '10px 20px',
                  fontSize: '13px',
                  fontWeight: 500,
                  marginBottom: '-1px',
                  color: activeTab === i ? 'var(--tx-1)' : 'var(--tx-3)',
                  background: 'none',
                  border: 'none',
                  borderBottom: `2px solid ${activeTab === i ? 'var(--gold)' : 'transparent'}`,
                  cursor: 'pointer',
                }}
              >
                {tab.label}
                {!tab.adminOnly && (
                  <span style={{
                    marginLeft: '8px',
                    fontSize: '11px',
                    padding: '1px 6px',
                    borderRadius: '3px',
                    fontWeight: 600,
                    backgroundColor: activeTab === i ? 'var(--gold-bg)' : 'var(--bd-s)',
                    color: activeTab === i ? 'var(--gold)' : 'var(--tx-4)',
                  }}>
                    {i === 0 ? leads.length : leads.length}
                  </span>
                )}
              </button>
            )
          })}
        </div>

        {loading ? (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '200px' }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '10px' }}>
              <RefreshCw size={20} className="animate-spin" style={{ color: 'var(--tx-4)' }} />
              <p style={{ fontSize: '13px', color: 'var(--tx-3)', margin: 0 }}>Loading prospect data…</p>
            </div>
          </div>
        ) : (
          <>
            {activeTab === 0 && (
              <LandlordTable leads={leads} onOutreach={lead => setModal({ lead, type: 'landlord' })} theme={theme} />
            )}
            {activeTab === 1 && (
              <PropertyMap leads={leads} theme={theme} />
            )}
            {activeTab === 2 && user?.role === 'admin' && (
              <UserManagement />
            )}
          </>
        )}
      </main>

      {modal && (
        <OutreachModal
          lead={modal.lead}
          type={modal.type}
          allLeads={leads}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  )
}

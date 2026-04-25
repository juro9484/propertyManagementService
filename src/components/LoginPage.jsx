import { useState } from 'react'

export default function LoginPage({ onLogin }) {
  const [email, setEmail]       = useState('')
  const [password, setPassword] = useState('')
  const [error, setError]       = useState('')
  const [loading, setLoading]   = useState(false)

  const API_BASE = import.meta.env.VITE_API_URL || ''

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const res = await fetch(`${API_BASE}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })

      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || 'Login failed')
      }

      const data = await res.json()
      localStorage.setItem('acpm_token', data.token)
      localStorage.setItem('acpm_user', JSON.stringify(data.user))
      onLogin(data.user, data.token)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ minHeight: '100vh', backgroundColor: 'var(--bg-base)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ width: '100%', maxWidth: '380px', padding: '0 20px' }}>

        {/* Logo + title */}
        <div style={{ textAlign: 'center', marginBottom: '32px' }}>
          <img src="/img_55573.png" alt="All County" style={{ height: '80px', marginBottom: '16px' }} />
          <h1 style={{ fontSize: '18px', fontWeight: 600, color: 'var(--tx-1)', margin: 0 }}>
            Prospect Pipeline
          </h1>
          <p style={{ fontSize: '13px', color: 'var(--tx-4)', marginTop: '4px' }}>
            Sign in to continue
          </p>
        </div>

        {/* Login form */}
        <form onSubmit={handleSubmit}>
          <div className="panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>

            <div>
              <label style={{ fontSize: '11px', fontWeight: 600, color: 'var(--tx-3)', textTransform: 'uppercase', letterSpacing: '0.08em', display: 'block', marginBottom: '6px' }}>
                Email
              </label>
              <input
                className="field"
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="you@company.com"
                required
                autoFocus
                style={{ width: '100%', fontSize: '13px', padding: '10px 12px' }}
              />
            </div>

            <div>
              <label style={{ fontSize: '11px', fontWeight: 600, color: 'var(--tx-3)', textTransform: 'uppercase', letterSpacing: '0.08em', display: 'block', marginBottom: '6px' }}>
                Password
              </label>
              <input
                className="field"
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="Enter password"
                required
                style={{ width: '100%', fontSize: '13px', padding: '10px 12px' }}
              />
            </div>

            {error && (
              <div style={{ fontSize: '12px', color: 'var(--b-red-tx)', backgroundColor: 'var(--b-red-bg)', border: '1px solid var(--b-red-bd)', borderRadius: '4px', padding: '8px 12px' }}>
                {error}
              </div>
            )}

            <button
              className="btn-gold"
              type="submit"
              disabled={loading}
              style={{ width: '100%', justifyContent: 'center', padding: '10px', fontSize: '13px', opacity: loading ? 0.6 : 1 }}
            >
              {loading ? 'Signing in...' : 'Sign In'}
            </button>
          </div>
        </form>

        <p style={{ textAlign: 'center', fontSize: '11px', color: 'var(--tx-4)', marginTop: '20px' }}>
          All County Property Management — Boulder County
        </p>
      </div>
    </div>
  )
}

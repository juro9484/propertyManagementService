import { useState, useEffect } from 'react'
import { UserPlus, Trash2, Shield, Eye, Briefcase, KeyRound } from 'lucide-react'

const ROLE_CFG = {
  admin:   { label: 'Admin',   icon: Shield,    color: 'var(--b-red-tx)',    bg: 'var(--b-red-bg)',    bd: 'var(--b-red-bd)' },
  manager: { label: 'Manager', icon: Briefcase, color: 'var(--b-blue-tx)',   bg: 'var(--b-blue-bg)',   bd: 'var(--b-blue-bd)' },
  viewer:  { label: 'Viewer',  icon: Eye,       color: 'var(--b-green-tx)',  bg: 'var(--b-green-bg)',  bd: 'var(--b-green-bd)' },
}

export default function UserManagement() {
  const [users, setUsers]       = useState([])
  const [loading, setLoading]   = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm]         = useState({ email: '', name: '', password: '', role: 'viewer' })
  const [error, setError]       = useState('')
  const [success, setSuccess]   = useState('')

  const API_BASE = import.meta.env.VITE_API_URL || ''
  const headers = {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${localStorage.getItem('acpm_token')}`,
  }

  const loadUsers = async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/auth/users`, { headers })
      if (res.ok) setUsers(await res.json())
    } catch {}
    setLoading(false)
  }

  useEffect(() => { loadUsers() }, [])

  const handleResetPassword = async (userId, name) => {
    const newPass = prompt(`New password for ${name}:`)
    if (!newPass) return
    try {
      const res = await fetch(`${API_BASE}/api/auth/users/${userId}/password`, {
        method: 'PATCH', headers,
        body: JSON.stringify({ password: newPass }),
      })
      if (!res.ok) throw new Error((await res.json()).detail || 'Failed')
      setSuccess(`Password reset for ${name}`)
    } catch (err) { setError(err.message) }
  }

  const handleDeleteUser = async (userId, name) => {
    if (!confirm(`Delete ${name}? This cannot be undone.`)) return
    try {
      const res = await fetch(`${API_BASE}/api/auth/users/${userId}`, {
        method: 'DELETE', headers,
      })
      if (!res.ok) throw new Error((await res.json()).detail || 'Failed')
      setSuccess(`Deleted ${name}`)
      loadUsers()
    } catch (err) { setError(err.message) }
  }

  const handleCreate = async (e) => {
    e.preventDefault()
    setError('')
    setSuccess('')
    try {
      const res = await fetch(`${API_BASE}/api/auth/users`, {
        method: 'POST',
        headers,
        body: JSON.stringify(form),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || 'Failed to create user')
      }
      const newUser = await res.json()
      setSuccess(`Created account for ${newUser.email}`)
      setForm({ email: '', name: '', password: '', role: 'viewer' })
      setShowForm(false)
      loadUsers()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="panel" style={{ padding: '24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <div>
          <h2 style={{ fontSize: '15px', fontWeight: 600, color: 'var(--tx-1)', margin: 0 }}>Team Access</h2>
          <p style={{ fontSize: '12px', color: 'var(--tx-4)', margin: '3px 0 0' }}>Manage who can access the dashboard</p>
        </div>
        <button className="btn-gold" style={{ fontSize: '12px', padding: '6px 14px' }} onClick={() => setShowForm(!showForm)}>
          <UserPlus size={12} />
          {showForm ? 'Cancel' : 'Add User'}
        </button>
      </div>

      {success && (
        <div style={{ fontSize: '12px', color: 'var(--b-green-tx)', backgroundColor: 'var(--b-green-bg)', border: '1px solid var(--b-green-bd)', borderRadius: '4px', padding: '8px 12px', marginBottom: '16px' }}>
          {success}
        </div>
      )}

      {/* Create user form */}
      {showForm && (
        <form onSubmit={handleCreate} style={{ backgroundColor: 'var(--bg-raised)', border: '1px solid var(--bd)', borderRadius: '6px', padding: '16px', marginBottom: '20px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
            <div>
              <label style={{ fontSize: '11px', fontWeight: 600, color: 'var(--tx-3)', textTransform: 'uppercase', letterSpacing: '0.08em', display: 'block', marginBottom: '4px' }}>Name</label>
              <input className="field" style={{ width: '100%', fontSize: '12px' }} placeholder="Jane Smith" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} required />
            </div>
            <div>
              <label style={{ fontSize: '11px', fontWeight: 600, color: 'var(--tx-3)', textTransform: 'uppercase', letterSpacing: '0.08em', display: 'block', marginBottom: '4px' }}>Email</label>
              <input className="field" type="email" style={{ width: '100%', fontSize: '12px' }} placeholder="jane@company.com" value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} required />
            </div>
            <div>
              <label style={{ fontSize: '11px', fontWeight: 600, color: 'var(--tx-3)', textTransform: 'uppercase', letterSpacing: '0.08em', display: 'block', marginBottom: '4px' }}>Password</label>
              <input className="field" type="password" style={{ width: '100%', fontSize: '12px' }} placeholder="Set a password" value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} required minLength={6} />
            </div>
            <div>
              <label style={{ fontSize: '11px', fontWeight: 600, color: 'var(--tx-3)', textTransform: 'uppercase', letterSpacing: '0.08em', display: 'block', marginBottom: '4px' }}>Role</label>
              <select className="field" style={{ width: '100%', fontSize: '12px' }} value={form.role} onChange={e => setForm({ ...form, role: e.target.value })}>
                <option value="viewer">Viewer — read-only</option>
                <option value="manager">Manager — leads + outreach</option>
                <option value="admin">Admin — full access</option>
              </select>
            </div>
          </div>

          {error && (
            <div style={{ fontSize: '12px', color: 'var(--b-red-tx)', backgroundColor: 'var(--b-red-bg)', border: '1px solid var(--b-red-bd)', borderRadius: '4px', padding: '8px 12px' }}>
              {error}
            </div>
          )}

          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <button className="btn-gold" type="submit" style={{ fontSize: '12px', padding: '6px 16px' }}>
              Create Account
            </button>
          </div>
        </form>
      )}

      {/* User list */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1px' }}>
        {loading ? (
          <p style={{ fontSize: '12px', color: 'var(--tx-4)', padding: '20px', textAlign: 'center' }}>Loading...</p>
        ) : users.length === 0 ? (
          <p style={{ fontSize: '12px', color: 'var(--tx-4)', padding: '20px', textAlign: 'center' }}>No users found</p>
        ) : users.map(u => {
          const rc = ROLE_CFG[u.role] || ROLE_CFG.viewer
          const RoleIcon = rc.icon
          return (
            <div key={u.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', backgroundColor: 'var(--bg-raised)', borderBottom: '1px solid var(--bd)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <div style={{ width: '32px', height: '32px', borderRadius: '50%', backgroundColor: rc.bg, border: `1px solid ${rc.bd}`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <RoleIcon size={14} style={{ color: rc.color }} />
                </div>
                <div>
                  <p style={{ fontSize: '13px', fontWeight: 500, color: 'var(--tx-1)', margin: 0 }}>{u.name}</p>
                  <p style={{ fontSize: '11px', color: 'var(--tx-4)', margin: '1px 0 0' }}>{u.email}</p>
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{
                  fontSize: '10px', fontWeight: 600, padding: '2px 8px', borderRadius: '3px',
                  backgroundColor: rc.bg, color: rc.color, border: `1px solid ${rc.bd}`, textTransform: 'uppercase',
                }}>
                  {rc.label}
                </span>
                {u.last_login && (
                  <span style={{ fontSize: '10px', color: 'var(--tx-4)' }}>
                    {new Date(u.last_login).toLocaleDateString()}
                  </span>
                )}
                <button className="btn-ghost" style={{ padding: '3px 6px' }} title="Reset password"
                  onClick={() => handleResetPassword(u.id, u.name)}>
                  <KeyRound size={11} style={{ color: 'var(--tx-3)' }} />
                </button>
                <button className="btn-ghost" style={{ padding: '3px 6px' }} title="Delete user"
                  onClick={() => handleDeleteUser(u.id, u.name)}>
                  <Trash2 size={11} style={{ color: 'var(--b-red-tx)' }} />
                </button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

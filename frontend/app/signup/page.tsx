'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'

export default function SignUpPage() {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [sent, setSent] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (new URLSearchParams(window.location.search).get('error') === 'verification_expired') {
      setError('That verification link is invalid or expired. Please sign up again or contact the site owner.')
    }
  }, [])

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      const response = await fetch('/api/auth/register', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, email, password }),
      })
      const result = await response.json()
      if (!response.ok) throw new Error(result.error || 'Could not create your account.')
      setSent(true)
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : 'Could not create your account.')
    } finally {
      setBusy(false)
    }
  }

  return <main className="auth-page">
    <section className="auth-card" aria-labelledby="signup-title">
      <a className="auth-brand" href="/" aria-label="Patrick home"><span className="brand-mark"><span /></span>patrick</a>
      {sent ? <>
        <span className="profile-eyebrow">ONE LAST STEP</span>
        <h1 id="signup-title">Check your email</h1>
        <p className="auth-subtitle">We sent a verification link to <strong>{email}</strong>. Verify your email before signing in.</p>
        <Link className="auth-submit auth-link-button" href="/signin">Back to sign in</Link>
      </> : <>
        <span className="profile-eyebrow">YOUR PRIVATE THINKING SPACE</span>
        <h1 id="signup-title">Create your account</h1>
        <p className="auth-subtitle">Start a thoughtful conversation with Patrick.</p>
        <a className="google-auth-button" href="/auth/google"><span className="google-g" aria-hidden="true">G</span>Continue with Google</a>
        <div className="auth-divider"><span>or continue with email</span></div>
        <form className="auth-form" onSubmit={submit}>
          <label htmlFor="signup-name">Name</label>
          <input id="signup-name" autoComplete="name" maxLength={120} required value={name} onChange={(event) => setName(event.target.value)} />
          <label htmlFor="signup-email">Email</label>
          <input id="signup-email" type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} />
          <label htmlFor="signup-password">Password</label>
          <input id="signup-password" type="password" autoComplete="new-password" minLength={8} maxLength={128} required value={password} onChange={(event) => setPassword(event.target.value)} />
          {error && <p className="auth-error" role="alert">{error}</p>}
          <button className="auth-submit" type="submit" disabled={busy}>{busy ? 'Creating account…' : 'Create account'}</button>
        </form>
        <p className="auth-switch">Already have an account? <Link href="/signin">Sign in</Link></p>
      </>}
    </section>
  </main>
}

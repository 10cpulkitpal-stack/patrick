'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'

export default function SignInPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const code = new URLSearchParams(window.location.search).get('error')
    const messages: Record<string, string> = {
      google_unavailable: 'Google sign-in is not configured. Use your email and password instead.',
      google_unverified: 'Google did not confirm a verified email address. Please try again.',
      google_failed: 'Google sign-in failed. Please try again or use email and password.',
    }
    if (code && messages[code]) setError(messages[code])
    if (new URLSearchParams(window.location.search).has('verified')) setError('Email verified. You can sign in now.')
  }, [])

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })
      const result = await response.json()
      if (!response.ok) throw new Error(result.error || 'Could not sign in.')
      window.location.assign('/')
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : 'Could not sign in.')
    } finally {
      setBusy(false)
    }
  }

  return <main className="auth-page">
    <section className="auth-card" aria-labelledby="signin-title">
      <a className="auth-brand" href="/" aria-label="Patrick home"><span className="brand-mark"><span /></span>patrick</a>
      <span className="profile-eyebrow">YOUR PRIVATE THINKING SPACE</span>
      <h1 id="signin-title">Welcome back</h1>
      <p className="auth-subtitle">Sign in to continue with Patrick.</p>
      <a className="google-auth-button" href="/auth/google"><span className="google-g" aria-hidden="true">G</span>Continue with Google</a>
      <div className="auth-divider"><span>or continue with email</span></div>
      <form className="auth-form" onSubmit={submit}>
        <label htmlFor="signin-email">Email</label>
        <input id="signin-email" type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} />
        <label htmlFor="signin-password">Password</label>
        <input id="signin-password" type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} />
        {error && <p className="auth-error" role="alert">{error}</p>}
        <button className="auth-submit" type="submit" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
      <p className="auth-switch">New to Patrick? <Link href="/signup">Create an account</Link></p>
    </section>
  </main>
}

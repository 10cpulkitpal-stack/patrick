'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'

export default function VerifyEmailPage() {
  const [message, setMessage] = useState('Verifying your email…')
  const [success, setSuccess] = useState(false)

  useEffect(() => {
    const token = new URLSearchParams(window.location.search).get('token')
    if (!token) {
      setMessage('This verification link is missing its token. Please create a new account or request a fresh link.')
      return
    }
    void fetch('/verify-email', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify({ token }),
    }).then(async (response) => {
      const result = await response.json()
      if (!response.ok) throw new Error(result.error || 'This link is invalid or expired.')
      setSuccess(true)
      setMessage('Your email is verified. You can sign in now.')
    }).catch((error: unknown) => {
      setMessage(error instanceof Error ? error.message : 'Could not verify this email.')
    })
  }, [])

  return <main className="auth-page"><section className="auth-card" aria-labelledby="verify-title">
    <a className="auth-brand" href="/" aria-label="Patrick home"><span className="brand-mark"><span /></span>patrick</a>
    <span className="profile-eyebrow">EMAIL VERIFICATION</span>
    <h1 id="verify-title">{success ? 'You’re all set' : 'Verify your email'}</h1>
    <p className="auth-subtitle" role="status">{message}</p>
    {(success || message !== 'Verifying your email…') && <Link className="auth-submit auth-link-button" href="/signin">Continue to sign in</Link>}
  </section></main>
}

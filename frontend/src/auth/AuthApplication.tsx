import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import type { FormEvent } from 'react'
import { api, ApiError } from '../api/index.ts'
import { NavigationLink } from './NavigationLink.tsx'
import type { Navigate } from './NavigationLink.tsx'
import type { AuthRoute } from './routing.ts'
import { authError, SessionStore } from './session.ts'
import { ru } from './texts.ts'
import { trimEmail, validateForm } from './validation.ts'
import type { FormErrors } from './validation.ts'

interface Props {
  route: AuthRoute
  navigate: Navigate
  registeredEmail?: string
  onRegistered: (email: string) => void
  onAuthenticated: () => void
}

export default function AuthApplication({ route, navigate, registeredEmail, onRegistered, onAuthenticated }: Props) {
  const [session] = useState(() => new SessionStore(api.auth))
  const state = useSyncExternalStore(session.subscribe, session.getSnapshot)
  const [email, setEmail] = useState(registeredEmail ?? '')
  const [errors, setErrors] = useState<FormErrors>({})
  const [message, setMessage] = useState('')
  const [pending, setPending] = useState(false)
  const busy = useRef(false)
  const active = useRef(false)
  const emailInput = useRef<HTMLInputElement>(null)
  const passwordInput = useRef<HTMLInputElement>(null)
  const errorBox = useRef<HTMLDivElement>(null)
  const title = useRef<HTMLHeadingElement>(null)
  const mode = route === '/register' ? 'register' : 'login'

  useEffect(() => {
    active.current = true
    void session.restore()
    return () => { active.current = false; session.invalidate() }
  }, [session])

  useEffect(() => {
    if (state.kind === 'authenticated' && route !== '/session') onAuthenticated()
    if (state.kind === 'anonymous' && route === '/session') navigate('/login', true)
  }, [state.kind, route, navigate, onAuthenticated])

  useEffect(() => { if (state.kind !== 'checking') title.current?.focus() }, [state.kind])
  useEffect(() => { if (message) errorBox.current?.focus() }, [message, state.kind])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy.current) return
    const password = passwordInput.current?.value ?? ''
    const validation = validateForm(mode, email, password)
    setErrors(validation)
    setMessage('')
    if (validation.email || validation.password) {
      if (validation.email) emailInput.current?.focus()
      else passwordInput.current?.focus()
      return
    }
    busy.current = true
    setPending(true)
    try {
      if (mode === 'register') {
        const account = await api.auth.register(trimEmail(email), password)
        if (active.current) onRegistered(account.email)
      } else {
        await api.auth.login(trimEmail(email), password)
        if (active.current) onAuthenticated()
      }
    } catch (error) {
      if (!active.current) return
      if (error instanceof ApiError && error.code === 'already_authenticated') {
        await session.restore()
      } else {
        setMessage(authError(error, mode))
        // An interrupted login may already have created a session. Verify using GET.
        if (mode === 'login' && error instanceof ApiError && error.code === 'network_error') await session.restore()
      }
    } finally {
      if (passwordInput.current) passwordInput.current.value = ''
      busy.current = false
      if (active.current) setPending(false)
    }
  }

  async function logout() {
    if (busy.current) return
    busy.current = true
    setPending(true)
    setMessage('')
    try {
      await api.auth.logout()
      if (active.current) session.signedOut()
    } catch (error) {
      if (!active.current) return
      if (error instanceof ApiError && error.code === 'authentication_required') session.signedOut()
      else {
        setMessage(authError(error, 'logout'))
        if (error instanceof ApiError && error.code === 'network_error') await session.restore()
      }
    } finally {
      busy.current = false
      if (active.current) setPending(false)
    }
  }

  const notice = message ? <div className="form-alert" role="alert" tabIndex={-1} ref={errorBox}>{message}</div> : null
  return (
    <main className="auth-shell">
      <nav className="auth-nav" aria-label="Навигация аккаунта">
        <NavigationLink to="/" navigate={navigate}>{ru.home}</NavigationLink>
        <span>{ru.brand}</span>
      </nav>
      <section className="auth-card" aria-labelledby="auth-title">
        {state.kind === 'checking' && <p role="status">{ru.checking}</p>}
        {state.kind === 'error' && <>
          <h1 id="auth-title" tabIndex={-1} ref={title}>{ru.session}</h1>
          <p role="alert">{ru.sessionError}</p>
          <button onClick={() => { void session.restore() }}>{ru.retry}</button>
        </>}
        {state.kind === 'authenticated' && route === '/session' && <>
          <h1 id="auth-title" tabIndex={-1} ref={title}>{ru.session}</h1>
          <p>{ru.signedIn}</p>
          <dl><dt>{ru.sessionEmail}</dt><dd className="session-email">{state.user.email}</dd></dl>
          <p className="help-text">{ru.sessionHelp}</p>
          <p><NavigationLink to="/topics" navigate={navigate}>{ru.topics}</NavigationLink></p>
          {notice}
          <button disabled={pending} onClick={() => { void logout() }}>{pending ? ru.signingOut : ru.logout}</button>
          {pending && <p role="status">{ru.signingOut}</p>}
        </>}
        {state.kind === 'anonymous' && route !== '/session' && <>
          <h1 id="auth-title" tabIndex={-1} ref={title}>{mode === 'register' ? ru.register : ru.login}</h1>
          <p>{mode === 'register' ? ru.registerIntro : ru.loginIntro}</p>
          {registeredEmail && mode === 'login' && <p className="success-notice" role="status">{ru.registered}</p>}
          <p className="help-text">{ru.requiredNote}</p>
          {notice}
          <form noValidate aria-labelledby="auth-title" aria-busy={pending} onSubmit={event => { void submit(event) }}>
            <div className="form-field">
              <label htmlFor="auth-email">{ru.email}</label>
              <input id="auth-email" name="email" type="email" autoComplete="username" inputMode="email"
                required value={email} onChange={event => setEmail(event.target.value)} ref={emailInput}
                disabled={pending} aria-invalid={Boolean(errors.email)} aria-describedby={errors.email ? 'email-error' : undefined} />
              {errors.email && <p className="field-error" id="email-error">{errors.email}</p>}
            </div>
            <div className="form-field">
              <label htmlFor="auth-password">{ru.password}</label>
              <input id="auth-password" name="password" type="password" required ref={passwordInput}
                autoComplete={mode === 'register' ? 'new-password' : 'current-password'} disabled={pending}
                aria-invalid={Boolean(errors.password)}
                aria-describedby={[mode === 'register' ? 'password-hint' : '', errors.password ? 'password-errors' : ''].filter(Boolean).join(' ') || undefined} />
              {mode === 'register' && <p className="help-text" id="password-hint">{ru.passwordHint}</p>}
              {errors.password && <ul className="field-error" id="password-errors">{errors.password.map(error => <li key={error}>{error}</li>)}</ul>}
            </div>
            <button type="submit" disabled={pending}>{pending ? (mode === 'register' ? ru.creating : ru.signingIn) : (mode === 'register' ? ru.registerAction : ru.loginAction)}</button>
            {pending && <p role="status">{mode === 'register' ? ru.creating : ru.signingIn}</p>}
          </form>
          <p className="auth-switch">{mode === 'register' ? ru.haveAccount : ru.noAccount}{' '}
            <NavigationLink to={mode === 'register' ? '/login' : '/register'} navigate={navigate}>
              {mode === 'register' ? ru.loginAction : ru.register}
            </NavigationLink>
          </p>
        </>}
      </section>
    </main>
  )
}

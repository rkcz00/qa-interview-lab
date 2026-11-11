import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ApiError } from '../src/api/client.ts'
import { authError, SessionStore } from '../src/auth/session.ts'
import { resolveRoute } from '../src/auth/routing.ts'
import { ru } from '../src/auth/texts.ts'
import { passwordIssues, trimEmail, validateForm } from '../src/auth/validation.ts'
import type { Account } from '../src/api/types.ts'

const email = 'learner@example.invalid'
const user: Account = { user_id: '7', email }
const failure = (code: string) => new ApiError({ status: code === 'network_error' ? 0 : 403, code, kind: 'http', message: 'Untrusted detail' })

test('login validates only filled values and preserves password whitespace', () => {
  for (const password of ['x', '123', '        ', 'password']) assert.deepEqual(validateForm('login', email, password), {})
  assert.deepEqual(validateForm('login', 'not-an-email', 'x'), {})
  assert.equal(validateForm('login', '', 'x').email, ru.requiredEmail)
  assert.deepEqual(validateForm('login', email, '').password, [ru.requiredPassword])
  assert.equal(trimEmail('  Learner+lab@Example.INVALID  '), 'Learner+lab@Example.INVALID')
})

for (const [label, password, expected] of [
  ['length', 'Ab!2', 'password_too_short'],
  ['numeric', '987654321987654321', 'password_entirely_numeric'],
  ['unicode digits', '²²²²²²²²', 'password_entirely_numeric'],
  ['common', 'password123', 'password_too_common'],
  ['case and spaces', ' PASSWORD123 ', 'password_too_common'],
  ['similar', 'learner1', 'password_too_similar'],
] as const) test(`registration rejects ${label}`, () => {
  assert.equal(passwordIssues(email, password).includes(expected), true, 'Expected password policy rejection')
})

test('registration checks email and Unicode code-point length', () => {
  assert.equal(validateForm('register', 'wrong', 'qil-unique-strong-phrase').email, ru.invalidEmail)
  assert.equal(validateForm('register', email, '😀😀😀😀').password?.includes(ru.shortPassword), true)
  assert.deepEqual(validateForm('register', email, 'qil-unique-strong-phrase'), {})
})

test('UI routing accepts only fixed routes and does not resolve redirect targets', () => {
  for (const route of ['/', '/register', '/login', '/session'] as const) assert.equal(resolveRoute(route), route)
  for (const route of ['/logout', '/topics', 'https://outside.example.invalid', '//outside.example.invalid', '/login?next=/elsewhere']) {
    assert.equal(resolveRoute(route), null)
  }
})

test('restore distinguishes guest from transport and server errors', async () => {
  const guest = new SessionStore({ currentSession: async () => { throw failure('authentication_required') } })
  await guest.restore()
  assert.deepEqual(guest.getSnapshot(), { kind: 'anonymous' })
  for (const code of ['network_error', 'internal_error', 'csrf_failed', 'invalid_response']) {
    const store = new SessionStore({ currentSession: async () => { throw failure(code) } })
    await store.restore()
    assert.deepEqual(store.getSnapshot(), { kind: 'error' })
  }
})

test('late restore cannot recreate a logged-out user', async () => {
  let resolve!: (account: Account) => void
  const store = new SessionStore({ currentSession: () => new Promise(ready => { resolve = ready }) })
  const pending = store.restore()
  store.signedOut()
  resolve(user)
  await pending
  assert.deepEqual(store.getSnapshot(), { kind: 'anonymous' })
})

test('late guest response cannot overwrite a newer authenticated session', async () => {
  let reject!: (error: Error) => void
  const store = new SessionStore({ currentSession: () => new Promise((_resolve, failed) => { reject = failed }) })
  const pending = store.restore()
  store.signedIn(user)
  reject(failure('authentication_required'))
  await pending
  assert.deepEqual(store.getSnapshot(), { kind: 'authenticated', user })
})

test('invalidated restore publishes no result after unmount', async () => {
  let resolve!: (account: Account) => void
  const store = new SessionStore({ currentSession: () => new Promise(ready => { resolve = ready }) })
  const pending = store.restore()
  store.invalidate()
  resolve(user)
  await pending
  assert.deepEqual(store.getSnapshot(), { kind: 'checking' })
})

test('state subscriptions can be removed', async () => {
  const store = new SessionStore({ currentSession: async () => user })
  let updates = 0
  const unsubscribe = store.subscribe(() => { updates++ })
  await store.restore()
  assert.equal(updates, 2)
  unsubscribe()
  store.signedOut()
  assert.equal(updates, 2)
})

test('error texts are centralized and never display untrusted server details', () => {
  assert.equal(authError(failure('invalid_credentials'), 'login'), ru.invalidCredentials)
  assert.equal(authError(failure('validation_error'), 'register'), ru.validationError)
  assert.equal(authError(failure('csrf_failed'), 'login'), ru.csrfError)
  assert.equal(authError(failure('network_error'), 'logout'), ru.networkError)
  assert.equal(authError(new Error('Untrusted detail'), 'login'), ru.serverError)
})

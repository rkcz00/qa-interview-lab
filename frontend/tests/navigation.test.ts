import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ApiError } from '../src/api/client.ts'
import { PageFocus } from '../src/ui/focus.ts'
import { learnerNavigation } from '../src/ui/navigation.ts'
import { LogoutStore } from '../src/ui/logout.ts'

test('a page heading is focused once after readiness, not after translation or refresh', () => {
  const policy = new PageFocus()
  let focuses = 0
  const heading = { focus: () => { focuses++ } }
  assert.equal(policy.focus('article', null, true), false)
  assert.equal(policy.focus('article', heading, false), false)
  assert.equal(policy.focus('article', heading, true), true)
  policy.focus('article', heading, false)
  policy.focus('article', heading, true)
  policy.focus('article', heading, true)
  assert.equal(focuses, 1)
  policy.focus('result', heading, true)
  assert.equal(focuses, 2)
  policy.focus(null, heading, false)
  policy.focus('result', heading, true)
  assert.equal(focuses, 2)
  policy.focus('other-page', null, false)
  policy.focus('article', heading, true)
  assert.equal(focuses, 3)
})

test('learner routes have one active section and stable safe navigation targets', () => {
  for (const [route, active, current] of [
    ['/', '/', 'page'], ['/topics', '/', 'location'], ['/topics/12', '/', 'location'],
    ['/topics/12/test', '/', 'location'], ['/attempts/51', '/', 'location'],
    ['/progress', '/progress', 'page'], ['/session', '/session', 'page'],
  ]) {
    const nav = learnerNavigation(route)
    assert.deepEqual(nav.map(item => item.to), ['/', '/progress', '/session'])
    assert.deepEqual(nav.filter(item => item.current).map(item => [item.to, item.current]), [[active, current]])
  }
  for (const route of ['/login', '/register', '/topics-extra', 'https://outside.invalid/topics']) {
    assert.equal(learnerNavigation(route).some(item => item.current), false)
  }
})

const failure = (code: string) => new ApiError({ status: code === 'network_error' ? 0 : 403,
  code, kind: code === 'network_error' ? 'network' : 'http', message: 'Untrusted private detail' })

test('shared logout blocks duplicate submissions and ignores completion after leaving the page', async () => {
  let finish!: () => void
  let writes = 0
  const store = new LogoutStore({ logout: () => { writes++; return new Promise<undefined>(resolve => { finish = () => resolve(undefined) }) },
    currentSession: async () => ({ user_id: '7', email: 'learner@example.invalid' }) })
  const request = store.logout()
  await store.logout()
  assert.equal(writes, 1)
  assert.equal(store.getSnapshot().kind, 'pending')
  store.invalidate()
  finish()
  await request
  assert.equal(store.getSnapshot().kind, 'pending')
})

test('lost logout response is verified by GET without replaying POST', async () => {
  for (const stillAuthenticated of [false, true]) {
    let writes = 0
    let reads = 0
    const store = new LogoutStore({ logout: async () => { writes++; throw failure('network_error') },
      currentSession: async () => {
        reads++
        if (!stillAuthenticated) throw failure('authentication_required')
        return { user_id: '7', email: 'learner@example.invalid' }
      } })
    await store.logout()
    assert.equal(writes, 1)
    assert.equal(reads, 1)
    assert.equal(store.getSnapshot().kind, stillAuthenticated ? 'error' : 'signed_out')
    assert.equal(JSON.stringify(store.getSnapshot()).includes('Untrusted private detail'), false)
  }
})

test('CSRF refusal preserves the session and allows an explicit successful logout', async () => {
  let writes = 0
  let reads = 0
  const store = new LogoutStore({ logout: async () => { if (++writes === 1) throw failure('csrf_failed') },
    currentSession: async () => { reads++; return { user_id: '7', email: 'learner@example.invalid' } } })
  await store.logout()
  assert.equal(store.getSnapshot().kind, 'error')
  assert.equal(reads, 0)
  await store.logout()
  assert.equal(store.getSnapshot().kind, 'signed_out')
  await store.logout()
  assert.equal(writes, 2)
})

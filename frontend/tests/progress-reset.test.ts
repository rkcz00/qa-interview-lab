import assert from 'node:assert/strict'
import test from 'node:test'
import { ProgressStore } from '../src/progress/model.ts'
import { progressRu as text } from '../src/progress/texts.ts'
import { completion, deferred, failure, fixture, ready, tick, uuid, zero } from './progress-fixture.ts'

async function setup() {
  const f = fixture()
  const store = new ProgressStore(f.api, () => uuid)
  await store.load()
  return { ...f, store, before: ready(store).view }
}

test('cancel and unconfirmed actions never send reset or generate a request', async () => {
  const { api, posts } = fixture()
  const store = new ProgressStore(api, () => { assert.fail('No UUID before confirmation') })
  await store.load()
  await store.confirmReset()
  store.openReset()
  assert.equal(ready(store).reset.kind, 'confirming')
  store.cancelReset()
  await store.retryReset()
  assert.equal(ready(store).reset.kind, 'idle')
  assert.equal(posts.length, 0)
})

test('200 receipt is followed by GET; old values persist through both pending phases and double clicks', async () => {
  const { api, store, before, posts, calls } = await setup()
  const post = deferred<{ progress_generation: string }>()
  const get = deferred<ReturnType<typeof zero>>()
  api.progress.reset = async (...args) => { posts.push(args); return post.promise }
  api.progress.completion = () => { calls.push('completion-after'); return get.promise }
  store.openReset()
  const pending = store.confirmReset()
  await store.confirmReset()
  store.cancelReset()
  await store.load(true)
  assert.equal(posts.length, 1)
  assert.equal(ready(store).view, before)
  assert.equal(ready(store).reset.kind, 'posting')
  post.resolve({ progress_generation: '2' })
  await tick()
  assert.equal(ready(store).reset.kind, 'refreshing')
  assert.equal(ready(store).view, before)
  assert.equal(calls.filter(call => call === 'completion-after').length, 1)
  get.resolve(zero())
  await pending
  assert.equal(ready(store).view.percentage, 0)
  assert.equal(ready(store).view.generation, '2')
  assert.equal(ready(store).reset.kind, 'success')
  assert.deepEqual(posts, [['reset_all_progress', uuid, '1']])
  assert.equal(store.ownsReset(), false)
})

for (const [status, code, message] of [[400, 'validation_error', text.resetInvalid], [403, 'csrf_failed', text.resetForbidden],
  [500, 'internal_error', text.resetFailed]] as const) {
  test(`reset ${status}/${code} preserves displayed values and permits only an explicit identical retry`, async () => {
    const { api, store, before, posts } = await setup()
    api.progress.reset = async (...args) => { posts.push(args); throw failure(status, code) }
    store.openReset()
    await store.confirmReset()
    assert.equal(ready(store).view, before)
    assert.deepEqual(ready(store).reset, { kind: 'error', action: 'retry', message, open: true })
    assert.equal(JSON.stringify(store.getSnapshot()).includes('Private'), false)
    assert.equal(posts.length, 1)
    api.progress.completion = async () => zero()
    api.progress.reset = async (...args) => { posts.push(args); return { progress_generation: '2' } }
    await store.retryReset()
    assert.equal(ready(store).reset.kind, 'success')
    assert.deepEqual(posts[1], posts[0])
  })
}

for (const kind of ['network', 'protocol'] as const) {
  test(`uncertain ${kind} never retries until an explicit successful GET; same UUID and original generation survive`, async () => {
    const { api, store, before, posts } = await setup()
    api.progress.reset = async (...args) => { posts.push(args); throw failure(0, 'network_error', kind) }
    store.openReset()
    await store.confirmReset()
    await store.retryReset()
    assert.equal(posts.length, 1)
    assert.equal(ready(store).view, before)
    store.cancelReset()
    await store.load(true)
    store.openReset()
    assert.equal(ready(store).reset.kind, 'error')
    api.progress.completion = async () => zero('2')
    await store.recoverReset()
    assert.equal(ready(store).view, before, 'GET alone must not invent confirmation of this UUID')
    assert.equal(posts.length, 1)
    api.progress.reset = async (...args) => { posts.push(args); return { progress_generation: '2' } }
    await store.retryReset()
    assert.equal(ready(store).reset.kind, 'success')
    assert.deepEqual(posts, [['reset_all_progress', uuid, '1'], ['reset_all_progress', uuid, '1']])
  })
}

test('failed verification forbids POST retry and preserves the previous display', async () => {
  const { api, store, before, posts } = await setup()
  api.progress.reset = async (...args) => { posts.push(args); throw failure(0, 'network_error') }
  store.openReset()
  await store.confirmReset()
  api.progress.completion = async () => { throw failure(0, 'network_error') }
  await store.recoverReset()
  await store.retryReset()
  assert.equal(ready(store).view, before)
  assert.equal(posts.length, 1)
  const state = ready(store).reset
  assert.ok(state.kind === 'error' && state.action === 'check')
})

test('failed GET after acknowledged reset retries GET only and retains old values until confirmed', async () => {
  const { api, store, before, posts } = await setup()
  api.progress.completion = async () => { throw failure(404, 'not_found') }
  store.openReset()
  await store.confirmReset()
  assert.equal(ready(store).view, before)
  assert.deepEqual(ready(store).reset, { kind: 'error', action: 'refresh', message: text.resetRefreshFailed, open: true })
  store.cancelReset()
  store.openReset()
  api.progress.completion = async () => zero()
  await store.recoverReset()
  assert.equal(posts.length, 1)
  assert.equal(ready(store).reset.kind, 'success')
})

test('a response older than acknowledged generation cannot replace the frozen view', async () => {
  const { api, store, before } = await setup()
  store.openReset()
  await store.confirmReset()
  assert.equal(ready(store).view, before)
  const state = ready(store).reset
  assert.ok(state.kind === 'error' && state.action === 'refresh')
  api.progress.completion = async () => zero('3')
  await store.recoverReset()
  assert.equal(ready(store).view.generation, '3')
})

for (const code of ['progress_reset', 'reset_request_conflict']) {
  test(`409 ${code} never replays POST with a newer generation`, async () => {
    const { api, store, before, posts } = await setup()
    api.progress.reset = async (...args) => { posts.push(args); throw failure(409, code) }
    store.openReset()
    await store.confirmReset()
    await store.retryReset()
    assert.equal(ready(store).view, before)
    store.cancelReset()
    store.openReset()
    const recovery = ready(store).reset
    assert.ok(recovery.kind === 'error' && recovery.action === 'reload', 'Reopening a conflict must require GET, not a new POST')
    api.progress.completion = async () => zero('4')
    await store.recoverReset()
    assert.equal(ready(store).view.generation, '4')
    assert.equal(ready(store).reset.kind, 'idle')
    assert.equal(posts.length, 1)
  })
}

for (const phase of ['post', 'get', 'check'] as const) {
  test(`session loss during reset ${phase} clears private view and prevents late restoration`, async () => {
    const { api, store } = await setup()
    if (phase === 'post') api.progress.reset = async () => { throw failure(403, 'authentication_required') }
    else if (phase === 'get') api.progress.completion = async () => { throw failure(403, 'authentication_required') }
    else api.progress.reset = async () => { throw failure(0, 'network_error') }
    store.openReset()
    await store.confirmReset()
    if (phase === 'check') {
      api.progress.completion = async () => { throw failure(403, 'authentication_required') }
      await store.recoverReset()
    }
    assert.deepEqual(store.getSnapshot(), { kind: 'authentication' })
    assert.equal(store.ownsReset(), false)
  })
}

test('unmount and earlier GET cannot restore a stale reset view', async () => {
  const { api, store, before } = await setup()
  const old = deferred<typeof completion>()
  api.progress.completion = () => old.promise
  const loading = store.load(true)
  store.openReset()
  const post = deferred<{ progress_generation: string }>()
  api.progress.reset = () => post.promise
  const reset = store.confirmReset()
  old.resolve(completion)
  await loading
  assert.equal(ready(store).view, before)
  assert.equal(ready(store).reset.kind, 'posting')
  store.invalidate()
  post.resolve({ progress_generation: '2' })
  await reset
  assert.equal(ready(store).reset.kind, 'posting', 'Disposed store cannot publish new data')
})

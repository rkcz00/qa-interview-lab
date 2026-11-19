import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { TestContext } from 'node:test'
import { observeArticleEnd } from '../src/learning/useAutomaticRead.ts'

function browser(t: TestContext) {
  const cleanups: (() => void)[] = []
  t.after(() => { for (const cleanup of cleanups) cleanup() })
  let visibility: DocumentVisibilityState = 'visible'
  const document = new EventTarget()
  Object.defineProperty(document, 'visibilityState', { get: () => visibility })
  const observers: Observer[] = []
  class Observer {
    targets = new Set<Element>()
    disconnected = false
    callback: IntersectionObserverCallback
    constructor(callback: IntersectionObserverCallback) { this.callback = callback; observers.push(this) }
    observe(target: Element) { this.targets.add(target) }
    unobserve(target: Element) { this.targets.delete(target) }
    takeRecords() { return [] }
    disconnect() { this.disconnected = true; this.targets.clear() }
    intersect(target: Element, ratio = 1) {
      this.callback([{ target, isIntersecting: ratio > 0, intersectionRatio: ratio } as IntersectionObserverEntry], this as unknown as IntersectionObserver)
    }
  }
  for (const [name, value] of Object.entries({ document, window: { innerWidth: 390, innerHeight: 844 }, IntersectionObserver: Observer })) {
    const descriptor = Object.getOwnPropertyDescriptor(globalThis, name)
    Object.defineProperty(globalThis, name, { configurable: true, value })
    t.after(() => { if (descriptor) Object.defineProperty(globalThis, name, descriptor); else Reflect.deleteProperty(globalThis, name) })
  }
  return {
    observers,
    onCleanup(cleanup: () => void) { cleanups.push(cleanup) },
    visibility(value: DocumentVisibilityState) { visibility = value; document.dispatchEvent(new Event('visibilitychange')) },
  }
}

function marker() {
  const geometry = { width: 300, height: 1, top: 500, bottom: 501, left: 24, right: 324 }
  const state = { connected: true, visible: true }
  const element = {
    get isConnected() { return state.connected },
    getBoundingClientRect: () => geometry,
    checkVisibility: () => state.visible,
  } as unknown as HTMLSpanElement
  return { element, geometry, state }
}

test('hidden events and a zero-area marker cannot record reading; a fresh visible intersection records once', t => {
  const env = browser(t)
  const end = marker()
  let writes = 0
  const cleanup = observeArticleEnd(() => end.element, () => { writes++ })!
  env.onCleanup(cleanup)
  const observer = env.observers[0]
  env.visibility('hidden')
  observer.intersect(end.element)
  assert.equal(writes, 0)
  Object.assign(end.geometry, { width: 0, height: 0, top: 0, bottom: 0, left: 0, right: 0 })
  env.visibility('visible')
  assert.equal(writes, 0)
  observer.intersect(end.element)
  assert.equal(writes, 0)
  Object.assign(end.geometry, { width: 300, height: 1, top: 500, bottom: 501, left: 24, right: 324 })
  observer.intersect(end.element)
  observer.intersect(end.element)
  env.visibility('hidden')
  env.visibility('visible')
  assert.equal(writes, 1)
})

test('returning to a tab observes the current DOM marker and ignores stale intersections', t => {
  const env = browser(t)
  const old = marker()
  const next = marker()
  let target = old.element
  let writes = 0
  const cleanup = observeArticleEnd(() => target, () => { writes++ })!
  env.onCleanup(cleanup)
  const observer = env.observers[0]
  env.visibility('hidden')
  target = next.element
  next.state.visible = false
  env.visibility('visible')
  assert.deepEqual([...observer.targets], [next.element])
  observer.intersect(old.element)
  observer.intersect(next.element)
  assert.equal(writes, 0)
  next.state.visible = true
  observer.intersect(next.element)
  assert.equal(writes, 1)
})

test('offscreen, clipped, detached and CSS-hidden markers do not count; cleanup stops late events', t => {
  const env = browser(t)
  const end = marker()
  let writes = 0
  const cleanup = observeArticleEnd(() => end.element, () => { writes++ })!
  const observer = env.observers[0]
  end.geometry.bottom = 900
  observer.intersect(end.element)
  end.geometry.bottom = 501
  observer.intersect(end.element, 0.5)
  end.state.connected = false
  observer.intersect(end.element)
  end.state.connected = true
  end.state.visible = false
  observer.intersect(end.element)
  assert.equal(writes, 0)
  cleanup()
  end.state.visible = true
  observer.intersect(end.element)
  env.visibility('visible')
  assert.equal(writes, 0)
  assert.equal(observer.disconnected, true)
})

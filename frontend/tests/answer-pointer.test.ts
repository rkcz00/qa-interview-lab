import assert from 'node:assert/strict'
import { test } from 'node:test'
import { AnswerPointerGuard } from '../src/assessment/answerPointer.ts'

function activation(type: string, detail: number) {
  let defaults = 0
  let propagation = 0
  return {
    type, detail,
    preventDefault() { defaults++ },
    stopPropagation() { propagation++ },
    get cancelled() { return [defaults, propagation] },
  }
}

test('an advancing pointer Answer cancels the whole repeated press regardless of its new target', () => {
  const guard = new AnswerPointerGuard()
  const first = activation('mousedown', 1)
  assert.equal(guard.cancelRepeated(first), false)
  guard.afterAnswer(true, 1)
  for (const type of ['mousedown', 'click', 'dblclick']) {
    const event = activation(type, 2)
    assert.equal(guard.cancelRepeated(event), true)
    assert.deepEqual(event.cancelled, [1, 1])
  }
  assert.deepEqual(first.cancelled, [0, 0])
})

test('a new independent press releases the guard before another control receives focus', () => {
  const guard = new AnswerPointerGuard()
  guard.afterAnswer(true, 1)
  for (const [type, detail] of [['mousedown', 1], ['click', 1], ['mousedown', 2], ['click', 2], ['dblclick', 2]] as const) {
    const event = activation(type, detail)
    assert.equal(guard.cancelRepeated(event), false)
    assert.deepEqual(event.cancelled, [0, 0])
  }
})

test('keyboard Answer and activation without an advance do not arm pointer cancellation', () => {
  for (const [advanced, detail] of [[true, 0], [false, 1]] as const) {
    const guard = new AnswerPointerGuard()
    guard.afterAnswer(advanced, detail)
    const event = activation('mousedown', 2)
    assert.equal(guard.cancelRepeated(event), false)
    assert.deepEqual(event.cancelled, [0, 0])
  }
})

test('keyboard clicks remain available after a pointer advance and release the old gesture', () => {
  const guard = new AnswerPointerGuard()
  guard.afterAnswer(true, 1)
  const keyboard = activation('click', 0)
  assert.equal(guard.cancelRepeated(keyboard), false)
  guard.afterAnswer(true, keyboard.detail)
  assert.equal(guard.cancelRepeated(activation('click', 2)), false)
  assert.deepEqual(keyboard.cancelled, [0, 0])
})

test('a subsequent Answer arms a fresh gesture without cancelling unrelated events', () => {
  const guard = new AnswerPointerGuard()
  guard.afterAnswer(true, 1)
  assert.equal(guard.cancelRepeated(activation('mousedown', 1)), false)
  guard.afterAnswer(true, 1)
  const unrelated = activation('mouseup', 2)
  assert.equal(guard.cancelRepeated(unrelated), false)
  assert.deepEqual(unrelated.cancelled, [0, 0])
  assert.equal(guard.cancelRepeated(activation('click', 2)), true)
})

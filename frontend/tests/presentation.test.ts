import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { buttonState, noticeRole } from '../src/ui/presentation.ts'

const tokens = readFileSync(new URL('../src/tokens.css', import.meta.url), 'utf8')
const styles = readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8')
const values = new Map([...tokens.matchAll(/(--[\w-]+):\s*([^;]+);/g)].map(match => [match[1], match[2].trim()]))

function luminance(name: string) {
  const hex = values.get(name)
  assert.match(hex ?? '', /^#[\da-f]{6}$/i)
  const channels = [1, 3, 5].map(offset => {
    const value = parseInt(hex!.slice(offset, offset + 2), 16) / 255
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
  })
  return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722
}

test('busy buttons are disabled and announced; static disabled is not loading', () => {
  assert.deepEqual(buttonState(), { disabled: false, busy: false, ariaBusy: undefined })
  assert.deepEqual(buttonState(true), { disabled: true, busy: false, ariaBusy: undefined })
  assert.deepEqual(buttonState(false, true), { disabled: true, busy: true, ariaBusy: true })
  assert.deepEqual(buttonState(true, true), { disabled: true, busy: true, ariaBusy: true })
})

test('errors are alerts while success and informational notices are polite statuses', () => {
  assert.equal(noticeRole('error'), 'alert')
  assert.equal(noticeRole('success'), 'status')
  assert.equal(noticeRole('info'), 'status')
})

test('the shared stylesheet resolves all tokens from one imported palette and scale', () => {
  assert.match(styles, /@import '\.\/tokens\.css'/)
  for (const match of styles.matchAll(/var\((--[\w-]+)\)/g)) assert.ok(values.has(match[1]), `Undefined token ${match[1]}`)
})

for (const [foreground, background, minimum] of [
  ['text', 'surface', 4.5], ['text', 'page', 4.5], ['muted', 'surface', 4.5],
  ['muted', 'disabled', 4.5], ['surface', 'accent', 4.5], ['surface', 'accent-hover', 4.5],
  ['accent', 'accent-soft', 4.5], ['error', 'error-bg', 4.5], ['success', 'success-bg', 4.5],
  ['control-border', 'surface', 3], ['focus', 'page', 3], ['focus', 'surface', 3],
] as const) {
  test(`contrast: ${foreground} on ${background} reaches ${minimum}:1`, () => {
    const a = luminance('--color-' + foreground)
    const b = luminance('--color-' + background)
    assert.ok((Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05) >= minimum)
  })
}

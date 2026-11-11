import policy from './password-policy.json' with { type: 'json' }
import { ru } from './texts.ts'

export type AuthMode = 'login' | 'register'
export type PasswordIssue = 'password_too_short' | 'password_entirely_numeric' | 'password_too_common' | 'password_too_similar'
export interface FormErrors { email?: string; password?: string[] }

const commonPasswords = new Set(policy.commonPasswords)
// Python str.strip() whitespace, used by the pinned Django validators.
export function trimEmail(value: string) {
  return value.replace(/^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/gu, '')
}

function tooSimilar(password: string, email: string) {
  const letters = Array.from(password.toLowerCase())
  const normalized = trimEmail(email).toLowerCase()
  if (!normalized) return false
  for (const part of [...normalized.split(/[^\p{L}\p{N}_]+/u), normalized]) {
    const compared = Array.from(part)
    if (letters.length >= 10 * compared.length && compared.length < 0.35 * letters.length) continue
    const available = new Map<string, number>()
    for (const letter of compared) available.set(letter, (available.get(letter) ?? 0) + 1)
    let matches = 0
    for (const letter of letters) {
      const count = available.get(letter) ?? 0
      if (count > 0) { matches++; available.set(letter, count - 1) }
    }
    // SequenceMatcher.quick_ratio(): multiset intersection, not edit distance.
    if ((letters.length + compared.length === 0 ? 1 : 2 * matches / (letters.length + compared.length)) >= 0.7) return true
  }
  return false
}

export function passwordIssues(email: string, password: string): PasswordIssue[] {
  const issues: PasswordIssue[] = []
  const points = Array.from(password)
  if (tooSimilar(password, email)) issues.push('password_too_similar')
  if (points.length < 8) issues.push('password_too_short')
  if (commonPasswords.has(trimEmail(password.toLowerCase()))) issues.push('password_too_common')
  if (points.length > 0 && points.every(letter => {
    const code = letter.codePointAt(0)!
    return policy.digitRanges.some(([start, end]) => start <= code && code <= end)
  })) issues.push('password_entirely_numeric')
  return issues
}

const messages: Record<PasswordIssue, string> = {
  password_too_short: ru.shortPassword, password_entirely_numeric: ru.numericPassword,
  password_too_common: ru.commonPassword, password_too_similar: ru.similarPassword,
}

export function validateForm(mode: AuthMode, email: string, password: string): FormErrors {
  const errors: FormErrors = {}
  const address = trimEmail(email)
  if (!address) errors.email = ru.requiredEmail
  else if (mode === 'register' && (address.length > 254 || !/^[^\s@]+@[^\s@]+$/u.test(address))) errors.email = ru.invalidEmail
  if (password === '') errors.password = [ru.requiredPassword]
  else if (mode === 'register') {
    const issues = passwordIssues(address, password)
    if (issues.length) errors.password = issues.map(issue => messages[issue])
  }
  return errors
}

import type { Language } from '../api/types.ts'

interface Props {
  name: 'material-language' | 'test-language' | 'practice-language'
  legend: string
  language: Language
  disabled?: boolean
  choose: (language: Language) => void
}

export function LanguageSelector({ name, legend, language, disabled = false, choose }: Props) {
  return <fieldset className="material-language" disabled={disabled}>
    <legend>{legend}</legend>
    {(['ru', 'en'] as const).map(value => <label key={value}>
      <input type="radio" name={name} value={value} checked={language === value} onChange={() => choose(value)} />
      <span lang={value}>{value === 'ru' ? 'Русский' : 'English'}</span>
    </label>)}
  </fieldset>
}

import type { Lang } from './types'

export function clock(minutes: number): string {
  const m = ((Math.round(minutes) % 1440) + 1440) % 1440
  return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`
}

export function toMinutes(value: string): number {
  const [h, m] = value.split(':').map(Number)
  return h * 60 + m
}

export function duration(minutes: number, lang: Lang): string {
  const total = Math.max(0, Math.round(minutes))
  const h = Math.floor(total / 60)
  const m = total % 60
  const [hu, mu] = lang === 'uk' ? ['год', 'хв'] : ['h', 'min']
  if (h === 0) return `${m} ${mu}`
  return m === 0 ? `${h} ${hu}` : `${h} ${hu} ${m} ${mu}`
}

export function distance(meters: number, lang: Lang): string {
  const [mu, kmu] = lang === 'uk' ? ['м', 'км'] : ['m', 'km']
  if (meters < 950) return `${Math.round(meters / 10) * 10} ${mu}`
  return `${(meters / 1000).toFixed(1).replace('.', lang === 'uk' ? ',' : '.')} ${kmu}`
}

export function dayLabel(date: string | null, index: number, lang: Lang): string {
  if (!date) return lang === 'uk' ? `День ${index + 1}` : `Day ${index + 1}`
  const d = new Date(`${date}T12:00:00`)
  d.setDate(d.getDate() + index)
  return new Intl.DateTimeFormat(lang === 'uk' ? 'uk-UA' : 'en-GB', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  }).format(d)
}

export function plural(n: number, forms: [string, string, string]): string {
  // Ukrainian plural rule: 1 місце, 2 місця, 5 місць
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return forms[0]
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return forms[1]
  return forms[2]
}

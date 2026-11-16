import { describe, expect, it } from 'vitest'
import { clock, dayLabel, distance, duration, toMinutes } from './format'
import { translate } from './i18n'

describe('format', () => {
  it('formats clock times and wraps past midnight', () => {
    expect(clock(540)).toBe('09:00')
    expect(clock(1439)).toBe('23:59')
    expect(clock(1500)).toBe('01:00')
    expect(toMinutes('19:30')).toBe(1170)
  })

  it('formats durations in both languages', () => {
    expect(duration(45, 'uk')).toBe('45 хв')
    expect(duration(120, 'uk')).toBe('2 год')
    expect(duration(95, 'en')).toBe('1 h 35 min')
    expect(duration(-5, 'uk')).toBe('0 хв')
  })

  it('switches from metres to kilometres', () => {
    expect(distance(284, 'uk')).toBe('280 м')
    expect(distance(1180, 'uk')).toBe('1,2 км')
    expect(distance(1180, 'en')).toBe('1.2 km')
  })

  it('labels days by number or by date', () => {
    expect(dayLabel(null, 1, 'uk')).toBe('День 2')
    expect(dayLabel('2026-11-21', 1, 'en')).toContain('22')
  })
})

describe('translations', () => {
  it('uses Ukrainian plural forms', () => {
    expect(translate('uk', 'trip.stops', { n: 1 })).toBe('1 місце')
    expect(translate('uk', 'trip.stops', { n: 3 })).toBe('3 місця')
    expect(translate('uk', 'trip.stops', { n: 5 })).toBe('5 місць')
    expect(translate('uk', 'trip.stops', { n: 11 })).toBe('11 місць')
    expect(translate('uk', 'trip.stops', { n: 22 })).toBe('22 місця')
    expect(translate('en', 'trip.stops', { n: 1 })).toBe('1 place')
    expect(translate('en', 'trip.stops', { n: 4 })).toBe('4 places')
  })

  it('substitutes variables', () => {
    expect(translate('uk', 'trip.untitled', { city: 'Львів' })).toBe('Маршрут: Львів')
    expect(translate('en', 'reason.wiki_languages', { n: 37 })).toBe('Wikipedia in 37 languages')
  })
})

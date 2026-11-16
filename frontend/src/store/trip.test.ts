import { beforeEach, describe, expect, it } from 'vitest'
import type { Poi } from '../lib/types'
import { byDay, useTrip } from './trip'

const poi = (id: string): Poi => ({
  id,
  name: id,
  lat: 48.29,
  lon: 25.93,
  category: 'culture',
  subtype: 'museum',
  visit_minutes: 60,
  opening_hours: null,
  is_open: null,
  website: null,
  wikidata: null,
  sitelinks: 0,
  score: null,
  distance_m: null,
  reasons: [],
  summary: null,
})

const ids = () => useTrip.getState().stops.map((s) => `${s.poi.id}@${s.day}`)

describe('trip draft', () => {
  beforeEach(() => {
    useTrip.getState().startIn({ name: 'Чернівці', lat: 48.29, lon: 25.93 })
    for (const id of ['a', 'b', 'c']) useTrip.getState().addStop(poi(id), 0)
  })

  it('adds a place only once', () => {
    useTrip.getState().addStop(poi('a'), 0)
    expect(ids()).toEqual(['a@0', 'b@0', 'c@0'])
    expect(useTrip.getState().dirty).toBe(true)
  })

  it('reorders within a day and ignores impossible moves', () => {
    useTrip.getState().moveWithinDay(0, 2, 0)
    expect(ids()).toEqual(['c@0', 'a@0', 'b@0'])
    useTrip.getState().moveWithinDay(0, 0, 9)
    expect(ids()).toEqual(['c@0', 'a@0', 'b@0'])
  })

  it('moves a stop to another day and pulls stops back when days shrink', () => {
    useTrip.getState().setSettings({ days: 3 })
    useTrip.getState().moveToDay('b', 2)
    expect(byDay(useTrip.getState().stops, 3).map((d) => d.map((s) => s.poi.id))).toEqual([['a', 'c'], [], ['b']])
    useTrip.getState().setSettings({ days: 2 })
    expect(ids()).toContain('b@1')
  })

  it('applies an optimised order and keeps stops the optimiser skipped', () => {
    useTrip.getState().setSettings({ days: 2 })
    useTrip.getState().applyOrder([['c'], ['a']])
    expect(ids()).toEqual(['c@0', 'a@1', 'b@0'])
  })

  it('starting in a new city clears the draft', () => {
    useTrip.getState().markSaved('trip-1', 'slug')
    useTrip.getState().startIn({ name: 'Львів', lat: 49.84, lon: 24.03 })
    const state = useTrip.getState()
    expect(state.stops).toEqual([])
    expect(state.id).toBeNull()
    expect(state.city?.name).toBe('Львів')
  })

  it('removing a stop marks the draft as changed', () => {
    useTrip.getState().markSaved('trip-1', null)
    expect(useTrip.getState().dirty).toBe(false)
    useTrip.getState().removeStop('b')
    expect(ids()).toEqual(['a@0', 'c@0'])
    expect(useTrip.getState().dirty).toBe(true)
  })
})

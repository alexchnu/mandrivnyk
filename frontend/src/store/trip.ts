import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { Poi, Trip } from '../lib/types'

export interface City {
  name: string
  lat: number
  lon: number
}

export interface Stop {
  poi: Poi
  day: number
  visitMinutes: number | null
  note: string
}

export interface Draft {
  id: string | null // server id once saved
  shareSlug: string | null
  title: string
  city: City | null
  days: number
  startDate: string | null
  dayStart: string
  dayEnd: string
  stops: Stop[]
  dirty: boolean
}

const EMPTY: Draft = {
  id: null,
  shareSlug: null,
  title: '',
  city: null,
  days: 1,
  startDate: null,
  dayStart: '09:00',
  dayEnd: '19:00',
  stops: [],
  dirty: false,
}

interface TripState extends Draft {
  startIn: (city: City) => void
  load: (trip: Trip, asCopy?: boolean) => void
  setTitle: (title: string) => void
  setSettings: (patch: Partial<Pick<Draft, 'days' | 'startDate' | 'dayStart' | 'dayEnd'>>) => void
  addStop: (poi: Poi, day: number) => void
  removeStop: (poiId: string) => void
  setVisit: (poiId: string, minutes: number | null) => void
  moveWithinDay: (day: number, from: number, to: number) => void
  moveToDay: (poiId: string, day: number) => void
  applyOrder: (days: string[][]) => void
  markSaved: (id: string, shareSlug: string | null) => void
  reset: () => void
}

const clock = (minutes: number) =>
  `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`

/** Stops grouped by day, in visiting order. */
export function byDay(stops: Stop[], days: number): Stop[][] {
  const out: Stop[][] = Array.from({ length: days }, () => [])
  for (const stop of stops) out[Math.min(stop.day, days - 1)].push(stop)
  return out
}

export const useTrip = create<TripState>()(
  persist(
    (set) => ({
      ...EMPTY,
      startIn: (city) => set({ ...EMPTY, city }),
      load: (trip, asCopy = false) =>
        set({
          id: asCopy ? null : trip.id,
          shareSlug: asCopy ? null : trip.share_slug,
          title: trip.title,
          city: { name: trip.city, lat: trip.lat, lon: trip.lon },
          days: trip.n_days,
          startDate: trip.start_date,
          dayStart: clock(trip.day_start_min),
          dayEnd: clock(trip.day_end_min),
          stops: trip.stops.map((s) => ({
            poi: s.poi,
            day: s.day_index,
            visitMinutes: s.visit_minutes,
            note: s.note,
          })),
          dirty: asCopy,
        }),
      setTitle: (title) => set({ title, dirty: true }),
      setSettings: (patch) =>
        set((s) => {
          const days = patch.days ?? s.days
          return {
            ...patch,
            stops: s.stops.map((stop) => (stop.day >= days ? { ...stop, day: days - 1 } : stop)),
            dirty: true,
          }
        }),
      addStop: (poi, day) =>
        set((s) =>
          s.stops.some((x) => x.poi.id === poi.id)
            ? s
            : { stops: [...s.stops, { poi, day, visitMinutes: null, note: '' }], dirty: true },
        ),
      removeStop: (poiId) => set((s) => ({ stops: s.stops.filter((x) => x.poi.id !== poiId), dirty: true })),
      setVisit: (poiId, minutes) =>
        set((s) => ({
          stops: s.stops.map((x) => (x.poi.id === poiId ? { ...x, visitMinutes: minutes } : x)),
          dirty: true,
        })),
      moveWithinDay: (day, from, to) =>
        set((s) => {
          const groups = byDay(s.stops, s.days)
          const list = groups[day]
          if (from < 0 || to < 0 || from >= list.length || to >= list.length) return s
          const [moved] = list.splice(from, 1)
          list.splice(to, 0, moved)
          return { stops: groups.flat(), dirty: true }
        }),
      moveToDay: (poiId, day) =>
        set((s) => {
          const stop = s.stops.find((x) => x.poi.id === poiId)
          if (!stop || stop.day === day) return s
          const rest = s.stops.filter((x) => x.poi.id !== poiId)
          return { stops: [...rest, { ...stop, day }], dirty: true }
        }),
      applyOrder: (days) =>
        set((s) => {
          const known = new Map(s.stops.map((x) => [x.poi.id, x]))
          const ordered: Stop[] = []
          days.forEach((ids, day) => {
            for (const id of ids) {
              const stop = known.get(id)
              if (stop) {
                ordered.push({ ...stop, day })
                known.delete(id)
              }
            }
          })
          // stops the optimiser could not place stay in the trip, at the end of their day
          return { stops: [...ordered, ...known.values()], dirty: true }
        }),
      markSaved: (id, shareSlug) => set({ id, shareSlug, dirty: false }),
      reset: () => set({ ...EMPTY }),
    }),
    { name: 'planner-draft', version: 1 },
  ),
)

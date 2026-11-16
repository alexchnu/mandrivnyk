import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { type PlanParams, api } from './api'
import type { Lang } from './types'
import type { Draft } from '../store/trip'

export function planParams(draft: Pick<Draft, 'stops' | 'days' | 'startDate' | 'dayStart' | 'dayEnd'>, mode: PlanParams['mode']): PlanParams {
  return {
    stops: draft.stops.map((s) => ({ poi_id: s.poi.id, visit_minutes: s.visitMinutes, day: Math.min(s.day, draft.days - 1) })),
    days: draft.days,
    start_date: draft.startDate,
    day_start: draft.dayStart,
    day_end: draft.dayEnd,
    mode,
  }
}

/** Timetable for the trip exactly as the user ordered it; refreshed on every change. */
export function usePlan(draft: Pick<Draft, 'stops' | 'days' | 'startDate' | 'dayStart' | 'dayEnd'>, lang: Lang) {
  const params = planParams(draft, 'keep_order')
  const valid = draft.dayEnd > draft.dayStart
  return useQuery({
    queryKey: ['plan', params, lang],
    queryFn: () => api.plan(params, lang),
    enabled: draft.stops.length > 0 && valid,
    placeholderData: keepPreviousData,
    staleTime: 5 * 60_000,
    retry: 1,
    // a timetable built on straight-line estimates is retried until real walking paths arrive
    refetchInterval: (query) => (query.state.data?.routed === false ? 15_000 : false),
  })
}

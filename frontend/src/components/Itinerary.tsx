import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Link2, Save, Sparkles } from 'lucide-react'
import { ApiError, type TripPayload, api } from '../lib/api'
import { dayColor } from '../lib/categories'
import { dayLabel, duration, toMinutes } from '../lib/format'
import { useT } from '../lib/i18n'
import type { Plan } from '../lib/types'
import { planParams } from '../lib/usePlan'
import { byDay, useTrip } from '../store/trip'
import { useUi } from '../store/ui'
import { Timeline, type TimelineItem } from './Timeline'

interface Props {
  plan: Plan | undefined
  planLoading: boolean
}

export function Itinerary({ plan, planLoading }: Props) {
  const { t, lang } = useT()
  const trip = useTrip()
  const { activeDay, setActiveDay, focusedPoi, focusPoi, toast } = useUi()
  const queryClient = useQueryClient()
  const day = Math.min(activeDay, trip.days - 1)
  const groups = byDay(trip.stops, trip.days)
  const cityName = trip.city?.name ?? ''
  const title = trip.title || t('trip.untitled', { city: cityName })

  const visitOf = new Map((plan?.days ?? []).flatMap((d) => d.visits.map((v) => [v.poi.id, v] as const)))
  const items: TimelineItem[] = groups[day].map((s) => ({
    id: s.poi.id,
    name: s.poi.name,
    category: s.poi.category,
    visitMinutes: s.visitMinutes ?? s.poi.visit_minutes,
    visit: visitOf.get(s.poi.id) ?? null,
  }))
  const warnings = plan?.warnings ?? []
  const problems = warnings.filter((w) => w.code === 'closed' || w.code === 'late')

  const optimize = useMutation({
    mutationFn: () => api.plan(planParams(trip, 'optimize'), lang),
    onSuccess: (result) => {
      trip.applyOrder(result.days.map((d) => d.visits.map((v) => v.poi.id)))
      const saved = result.saved_walk_minutes
      if (result.unscheduled.length > 0) {
        const names = trip.stops.filter((s) => result.unscheduled.includes(s.poi.id)).map((s) => s.poi.name)
        toast(t('warn.unscheduled', { names: names.join(', ') }), 'error')
      } else if (saved !== null && saved >= 1) {
        toast(`${t('trip.optimized')}. ${t('trip.savedMinutes', { t: duration(saved, lang) })}`)
      } else {
        toast(saved === null ? t('trip.optimized') : t('trip.alreadyBest'))
      }
    },
    onError: (err) => toast(t(err instanceof ApiError && err.status === 0 ? 'common.offline' : 'common.error'), 'error'),
  })

  const save = useMutation({
    mutationFn: async () => {
      if (!trip.city) throw new Error('no city')
      const payload: TripPayload = {
        title,
        city: trip.city.name,
        lat: trip.city.lat,
        lon: trip.city.lon,
        start_date: trip.startDate,
        n_days: trip.days,
        day_start_min: toMinutes(trip.dayStart),
        day_end_min: toMinutes(trip.dayEnd),
        stops: groups.flatMap((list, d) =>
          list.map((s) => ({ poi_id: s.poi.id, day_index: d, visit_minutes: s.visitMinutes, note: s.note })),
        ),
      }
      return trip.id ? api.updateTrip(trip.id, payload, lang) : api.createTrip(payload, lang)
    },
    onSuccess: (saved) => {
      trip.markSaved(saved.id, saved.share_slug)
      queryClient.invalidateQueries({ queryKey: ['trips'] })
      toast(t('trip.saved'))
    },
    onError: (err) => toast(t(err instanceof ApiError && err.status === 0 ? 'common.offline' : 'common.error'), 'error'),
  })

  const share = useMutation({
    mutationFn: async () => {
      const saved = trip.id && !trip.dirty ? null : await save.mutateAsync()
      const id = saved?.id ?? trip.id
      if (!id) throw new Error('not saved')
      return api.shareTrip(id)
    },
    onSuccess: async (shared) => {
      trip.markSaved(shared.id, shared.share_slug)
      const url = `${location.origin}/shared/${shared.share_slug}`
      try {
        await navigator.clipboard.writeText(url)
        toast(t('trip.linkCopied'))
      } catch {
        prompt(t('trip.share'), url)
      }
    },
    onError: () => toast(t('common.error'), 'error'),
  })

  const validDay = trip.dayEnd > trip.dayStart
  return (
    <section className="panel panel--right" aria-label={t('planner.itinerary')}>
      <div className="panel__head">
        <input
          className="trip-title"
          aria-label={t('trip.titleLabel')}
          value={trip.title}
          placeholder={t('trip.untitled', { city: cityName })}
          maxLength={120}
          onChange={(e) => trip.setTitle(e.target.value)}
        />
        <p className="panel__sub">
          {t('trip.stops', { n: trip.stops.length })}
          {plan && trip.stops.length > 1 ? `, ${t('trip.totalWalk', { t: duration(plan.total_walk_minutes, lang) })}` : ''}
        </p>
      </div>
      <div className="settings">
        <label className="field">
          {t('trip.days')}
          <select value={trip.days} onChange={(e) => trip.setSettings({ days: Number(e.target.value) })}>
            {[1, 2, 3, 4, 5, 6, 7].map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </label>
        <label className="field">
          {t('trip.date')}
          <input type="date" value={trip.startDate ?? ''} onChange={(e) => trip.setSettings({ startDate: e.target.value || null })} />
        </label>
        <label className="field">
          {t('trip.dayStart')}
          <input type="time" value={trip.dayStart} onChange={(e) => e.target.value && trip.setSettings({ dayStart: e.target.value })} />
        </label>
        <label className="field">
          {t('trip.dayEnd')}
          <input
            type="time"
            value={trip.dayEnd}
            aria-invalid={!validDay}
            onChange={(e) => e.target.value && trip.setSettings({ dayEnd: e.target.value })}
          />
        </label>
      </div>
      {trip.days > 1 && (
        <div className="days" role="tablist">
          {groups.map((list, d) => (
            <button key={d} type="button" role="tab" aria-selected={d === day} onClick={() => setActiveDay(d)}>
              <span className="days__dot" style={{ background: dayColor(d) }} />
              {dayLabel(trip.startDate, d, lang)}
              <span className="days__count">{list.length}</span>
            </button>
          ))}
        </div>
      )}
      <div className="panel__body" style={{ background: 'var(--canvas)' }}>
        {(problems.length > 0 || plan?.routed === false) && (
          <div className="alerts" role="status">
            {problems.length > 0 && (
              <div className="flag flag--bad">
                <AlertTriangle aria-hidden="true" />
                {t('warn.fix')}
              </div>
            )}
            {plan?.routed === false && (
              <div className="flag flag--warn">
                <AlertTriangle aria-hidden="true" />
                {t('warn.estimated_walk')}
              </div>
            )}
          </div>
        )}
        {trip.stops.length === 0 ? (
          <div className="empty">
            <h3>{t('trip.empty.title')}</h3>
            <p>{t('trip.empty.text')}</p>
          </div>
        ) : items.length === 0 ? (
          <div className="empty">
            <p>{t('trip.emptyDay')}</p>
          </div>
        ) : (
          <Timeline
            day={day}
            items={items}
            warnings={warnings.filter((w) => w.day === day)}
            focused={focusedPoi}
            onFocus={focusPoi}
            onMove={(from, to) => trip.moveWithinDay(day, from, to)}
            onRemove={(id) => trip.removeStop(id)}
            onMoveToDay={(id, target) => trip.moveToDay(id, target)}
            dayCount={trip.days}
            startDate={trip.startDate}
          />
        )}
      </div>
      <div className="panel__foot">
        <button
          type="button"
          className="btn btn--primary"
          style={{ flex: 1 }}
          disabled={trip.stops.length < 2 || optimize.isPending || !validDay}
          onClick={() => optimize.mutate()}
        >
          <Sparkles size={17} aria-hidden="true" />
          {optimize.isPending ? t('trip.optimizing') : t('trip.optimize')}
        </button>
        <button
          type="button"
          className="btn"
          disabled={trip.stops.length === 0 || save.isPending || (!trip.dirty && trip.id !== null) || planLoading}
          onClick={() => save.mutate()}
        >
          <Save size={17} aria-hidden="true" />
          <span>{save.isPending ? t('trip.saving') : t('trip.save')}</span>
        </button>
        <button
          type="button"
          className="btn"
          disabled={trip.stops.length === 0 || share.isPending}
          onClick={() => share.mutate()}
          aria-label={t('trip.share')}
          title={t('trip.share')}
        >
          <Link2 size={17} />
        </button>
      </div>
    </section>
  )
}

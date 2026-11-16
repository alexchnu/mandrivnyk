import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { MapView } from '../components/MapView'
import { Timeline, type TimelineItem } from '../components/Timeline'
import { api } from '../lib/api'
import { dayColor } from '../lib/categories'
import { clock, dayLabel, duration } from '../lib/format'
import { useT } from '../lib/i18n'
import { usePlan } from '../lib/usePlan'
import { type Stop, useTrip } from '../store/trip'

/** Read-only view of a trip opened by its public link. */
export function Shared() {
  const { t, lang } = useT()
  const { slug } = useParams()
  const navigate = useNavigate()
  const load = useTrip((s) => s.load)
  const [day, setDay] = useState(0)
  const [focused, setFocused] = useState<string | null>(null)
  const trip = useQuery({ queryKey: ['shared', slug, lang], queryFn: () => api.sharedTrip(slug as string, lang), retry: false })

  const stops: Stop[] = (trip.data?.stops ?? []).map((s) => ({ poi: s.poi, day: s.day_index, visitMinutes: s.visit_minutes, note: s.note }))
  const settings = {
    stops,
    days: trip.data?.n_days ?? 1,
    startDate: trip.data?.start_date ?? null,
    dayStart: clock(trip.data?.day_start_min ?? 540),
    dayEnd: clock(trip.data?.day_end_min ?? 1140),
  }
  const plan = usePlan(settings, lang)

  if (trip.isPending) return <div className="empty">{t('common.loading')}</div>
  if (trip.isError || !trip.data) {
    return (
      <div className="empty" role="alert">
        <h3>{t('trip.notFound')}</h3>
        <Link to="/" className="btn btn--primary">
          {t('nav.newTrip')}
        </Link>
      </div>
    )
  }
  const data = trip.data
  const visitOf = new Map((plan.data?.days ?? []).flatMap((d) => d.visits.map((v) => [v.poi.id, v] as const)))
  const items: TimelineItem[] = stops
    .filter((s) => s.day === day)
    .map((s) => ({ id: s.poi.id, name: s.poi.name, category: s.poi.category, visitMinutes: s.visitMinutes ?? s.poi.visit_minutes, visit: visitOf.get(s.poi.id) ?? null }))

  return (
    <div className="planner" data-tab="itinerary" style={{ gridTemplateColumns: 'minmax(0, 1fr) 420px', gridTemplateRows: 'minmax(0, 1fr)' }}>
      <div className="planner__map" style={{ gridColumn: 1, gridRow: 1 }}>
        <MapView
          city={{ name: data.city, lat: data.lat, lon: data.lon }}
          suggestions={[]}
          stops={stops}
          days={plan.data?.days ?? null}
          activeDay={day}
          focusedPoi={focused}
          onFocus={setFocused}
        />
      </div>
      <section className="panel panel--right" style={{ gridColumn: 2, gridRow: 1, display: 'flex' }}>
        <div className="panel__head">
          <h1 className="panel__title">{data.title}</h1>
          <p className="panel__sub">
            {data.city}, {t('trip.stops', { n: stops.length })}
            {plan.data ? `, ${t('trip.totalWalk', { t: duration(plan.data.total_walk_minutes, lang) })}` : ''}
          </p>
        </div>
        {!data.editable && <p className="notice" style={{ marginBottom: 12 }}>{t('trip.readOnly')}</p>}
        {data.n_days > 1 && (
          <div className="days" role="tablist">
            {Array.from({ length: data.n_days }, (_, d) => (
              <button key={d} type="button" role="tab" aria-selected={d === day} onClick={() => setDay(d)}>
                <span className="days__dot" style={{ background: dayColor(d) }} />
                {dayLabel(data.start_date, d, lang)}
              </button>
            ))}
          </div>
        )}
        <div className="panel__body" style={{ background: 'var(--canvas)' }}>
          {items.length > 0 ? (
            <Timeline day={day} items={items} warnings={(plan.data?.warnings ?? []).filter((w) => w.day === day)} focused={focused} onFocus={setFocused} />
          ) : (
            <div className="empty">
              <p>{t('trip.emptyDay')}</p>
            </div>
          )}
        </div>
        <div className="panel__foot">
          <button
            type="button"
            className="btn btn--primary"
            style={{ flex: 1 }}
            onClick={() => {
              load(data, !data.editable)
              navigate(data.editable ? `/plan/${data.id}` : '/plan')
            }}
          >
            {data.editable ? t('planner.itinerary') : t('trip.copy')}
          </button>
          <button type="button" className="btn" onClick={() => window.print()}>
            PDF
          </button>
        </div>
      </section>
    </div>
  )
}

import { useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useState } from 'react'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { Itinerary } from '../components/Itinerary'
import { MapView } from '../components/MapView'
import { Suggestions } from '../components/Suggestions'
import { api } from '../lib/api'
import { useT } from '../lib/i18n'
import type { Poi } from '../lib/types'
import { usePlan } from '../lib/usePlan'
import { useTrip } from '../store/trip'
import { useUi } from '../store/ui'

type Tab = 'suggestions' | 'itinerary' | 'map'

export function Planner() {
  const { t, lang } = useT()
  const { tripId } = useParams()
  const navigate = useNavigate()
  const trip = useTrip()
  const { activeDay, setActiveDay, focusedPoi, focusPoi, toast } = useUi()
  const [tab, setTab] = useState<Tab>('suggestions')
  const [suggested, setSuggested] = useState<Poi[]>([])
  const onItems = useCallback((items: Poi[]) => setSuggested(items), [])

  // Opening /plan/:id loads a saved trip into the editor once.
  const saved = useQuery({
    queryKey: ['trip', tripId, lang],
    queryFn: () => api.trip(tripId as string, lang),
    enabled: Boolean(tripId) && trip.id !== tripId,
    retry: false,
  })
  useEffect(() => {
    if (saved.data) {
      trip.load(saved.data)
      setActiveDay(0)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [saved.data])
  useEffect(() => {
    if (saved.isError) {
      toast(t('trip.notFound'), 'error')
      navigate('/trips', { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [saved.isError])
  useEffect(() => {
    if (activeDay >= trip.days) setActiveDay(trip.days - 1)
  }, [activeDay, trip.days, setActiveDay])

  const plan = usePlan(trip, lang)

  if (tripId && trip.id !== tripId) return <div className="empty">{t('common.loading')}</div>
  if (!trip.city) return <Navigate to="/" replace />

  return (
    <div className="planner" data-tab={tab}>
      <div className="planner__tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === 'suggestions'} onClick={() => setTab('suggestions')}>
          {t('planner.suggestions')}
        </button>
        <button type="button" role="tab" aria-selected={tab === 'itinerary'} onClick={() => setTab('itinerary')}>
          {t('planner.itinerary')} ({trip.stops.length})
        </button>
        <button type="button" role="tab" className="planner__tab-map" aria-selected={tab === 'map'} onClick={() => setTab('map')}>
          {t('planner.map')}
        </button>
      </div>
      <Suggestions city={trip.city} stops={trip.stops} onItems={onItems} />
      <div className="planner__map">
        <MapView
          city={trip.city}
          suggestions={suggested}
          stops={trip.stops}
          days={trip.stops.length > 0 ? (plan.data?.days ?? null) : null}
          activeDay={Math.min(activeDay, trip.days - 1)}
          focusedPoi={focusedPoi}
          onFocus={focusPoi}
          onAdd={(poi) => trip.addStop(poi, Math.min(activeDay, trip.days - 1))}
        />
      </div>
      <Itinerary plan={trip.stops.length > 0 ? plan.data : undefined} planLoading={plan.isFetching} />
    </div>
  )
}

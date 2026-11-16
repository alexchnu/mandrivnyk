import { useQuery } from '@tanstack/react-query'
import { SlidersHorizontal } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { ApiError, api } from '../lib/api'
import { CATEGORIES } from '../lib/categories'
import { useT } from '../lib/i18n'
import type { CategoryId, Poi } from '../lib/types'
import { type City, type Stop, useTrip } from '../store/trip'
import { useUi } from '../store/ui'
import { PoiCard } from './PoiCard'

interface Props {
  city: City
  stops: Stop[]
  onItems: (items: Poi[]) => void
}

const PAGE = 12

export function Suggestions({ city, stops, onItems }: Props) {
  const { t, lang } = useT()
  const addStop = useTrip((s) => s.addStop)
  const { activeDay, focusedPoi, focusPoi } = useUi()
  const [radius, setRadius] = useState(3)
  const [openOnly, setOpenOnly] = useState(false)
  const [categories, setCategories] = useState<CategoryId[]>([])
  const [showFilters, setShowFilters] = useState(false)
  const [hidden, setHidden] = useState<string[]>([])
  // A "round" is one request; pressing "show other places" starts the next round with
  // everything shown so far excluded and the current trip as context.
  const [round, setRound] = useState({ n: 0, exclude: [] as string[], selected: [] as string[], anchor: null as null | { lat: number; lon: number } })

  const cityKey = `${city.lat},${city.lon}`
  useEffect(() => {
    setHidden([])
    setRound({ n: 0, exclude: [], selected: [], anchor: null })
  }, [cityKey])

  const params = { radius, openOnly, categories: categories.join(','), lang }
  const query = useQuery({
    queryKey: ['recommend', cityKey, params, round.n],
    queryFn: () =>
      api.recommend({
        lat: city.lat,
        lon: city.lon,
        radius_km: radius,
        anchor: round.anchor,
        categories,
        preferences: {},
        exclude_ids: round.exclude,
        selected_ids: round.selected,
        limit: PAGE,
        lang,
        open_only: openOnly,
      }),
    staleTime: Infinity,
    retry: (count, error) => !(error instanceof ApiError && error.status === 503) && count < 1,
  })

  const inTrip = useMemo(() => new Set(stops.map((s) => s.poi.id)), [stops])
  const visible = useMemo(
    () => (query.data?.items ?? []).filter((p) => !inTrip.has(p.id) && !hidden.includes(p.id)),
    [query.data, inTrip, hidden],
  )
  useEffect(() => onItems(visible), [visible, onItems])

  // Wikidata enrichment finishes in the background shortly after a city is first loaded.
  const enriching = query.data?.enrichment === 'pending'
  useEffect(() => {
    if (!enriching) return
    const timer = setTimeout(() => query.refetch(), 20_000)
    return () => clearTimeout(timer)
  }, [enriching, query])

  function nextRound() {
    const shown = query.data?.items.map((p) => p.id) ?? []
    const last = [...stops].reverse().find((s) => s.day === activeDay) ?? stops.at(-1)
    setRound((r) => ({
      n: r.n + 1,
      exclude: [...new Set([...r.exclude, ...shown, ...hidden])],
      selected: stops.map((s) => s.poi.id),
      anchor: last ? { lat: last.poi.lat, lon: last.poi.lon } : null,
    }))
  }

  function toggle(cat: CategoryId) {
    setCategories((list) => (list.includes(cat) ? list.filter((c) => c !== cat) : [...list, cat]))
    setRound((r) => ({ ...r, n: 0, exclude: [] }))
  }

  function add(poi: Poi, rank: number) {
    addStop(poi, activeDay)
    api.feedback([{ poi_id: poi.id, action: 'added', rank }]).catch(() => undefined)
  }

  function hide(poi: Poi, rank: number) {
    setHidden((list) => [...list, poi.id])
    api.feedback([{ poi_id: poi.id, action: 'dismissed', rank }]).catch(() => undefined)
  }

  const unavailable = query.error instanceof ApiError && query.error.status === 503
  return (
    <section className="panel panel--left" aria-labelledby="suggest-title">
      <div className="panel__head">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <h2 id="suggest-title" className="panel__title">
            {t('suggest.title')}
          </h2>
          <button
            type="button"
            className="btn btn--quiet btn--small"
            aria-expanded={showFilters}
            onClick={() => setShowFilters((v) => !v)}
          >
            <SlidersHorizontal size={16} aria-hidden="true" />
            {t('suggest.filters')}
          </button>
        </div>
        <p className="panel__sub">
          {city.name}
          {round.anchor ? `, ${t('suggest.near')}` : ''}
        </p>
      </div>
      {showFilters && (
        <div className="filters">
          <div className="filters__chips">
            {CATEGORIES.map((cat) => (
              <button
                key={cat.id}
                type="button"
                className="chip"
                aria-pressed={categories.includes(cat.id)}
                onClick={() => toggle(cat.id)}
              >
                <span className="chip__dot" style={{ background: cat.color }} />
                {t(`cat.${cat.id}`)}
              </button>
            ))}
          </div>
          <label className="filters__row">
            {t('suggest.radius')}
            <input
              type="range"
              min={1}
              max={7}
              step={1}
              value={radius}
              onChange={(e) => {
                setRadius(Number(e.target.value))
                setRound((r) => ({ ...r, n: 0, exclude: [] }))
              }}
            />
            <span>{radius} {lang === 'uk' ? 'км' : 'km'}</span>
          </label>
          <label className="filters__check">
            <input type="checkbox" checked={openOnly} onChange={(e) => setOpenOnly(e.target.checked)} />
            {t('suggest.openOnly')}
          </label>
        </div>
      )}
      <div className="panel__body">
        {query.isPending && (
          <>
            <p className="notice">{t('suggest.loadingCity')}</p>
            <ul className="cards" aria-hidden="true">
              {Array.from({ length: 5 }, (_, i) => (
                <li key={i} className="skeleton" style={{ height: 150 }} />
              ))}
            </ul>
          </>
        )}
        {query.isError && (
          <div className="empty" role="alert">
            <h3>{unavailable ? t('suggest.unavailable') : t('common.error')}</h3>
            <button type="button" className="btn" onClick={() => query.refetch()}>
              {t('suggest.retry')}
            </button>
          </div>
        )}
        {query.isSuccess && (
          <>
            {enriching && <p className="notice">{t('suggest.enriching')}</p>}
            {query.data.data_status !== 'fresh' && (
              <p className="notice" role="status">
                {t(query.data.data_status === 'partial' ? 'suggest.partial' : 'suggest.stale')}
              </p>
            )}
            {visible.length > 0 ? (
              <ul className="cards">
                {visible.map((poi, rank) => (
                  <PoiCard
                    key={poi.id}
                    poi={poi}
                    active={focusedPoi === poi.id}
                    onAdd={() => add(poi, rank)}
                    onHide={() => hide(poi, rank)}
                    onHover={(hover) => focusPoi(hover ? poi.id : null)}
                  />
                ))}
              </ul>
            ) : (
              query.data.items.length === 0 && (
                <div className="empty">
                  <p>{t('suggest.empty')}</p>
                </div>
              )
            )}
            {query.data.items.length > 0 && (
              <div className="more">
                <button type="button" className="btn" onClick={nextRound} disabled={query.isFetching}>
                  {t('suggest.more')}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  )
}

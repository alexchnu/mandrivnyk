import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MapPinned, Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { useT } from '../lib/i18n'
import { useSession } from '../store/session'
import { useTrip } from '../store/trip'
import { useUi } from '../store/ui'

export function Trips() {
  const { t, lang } = useT()
  const user = useSession((s) => s.user)
  const { openAuth, toast } = useUi()
  const draft = useTrip()
  const queryClient = useQueryClient()
  const trips = useQuery({ queryKey: ['trips', lang, user?.id ?? 'anon'], queryFn: () => api.trips(lang) })
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteTrip(id),
    onSuccess: (_, id) => {
      if (draft.id === id) draft.reset()
      queryClient.invalidateQueries({ queryKey: ['trips'] })
      toast(t('trip.deleted'))
    },
    onError: () => toast(t('common.error'), 'error'),
  })
  const dateFormat = new Intl.DateTimeFormat(lang === 'uk' ? 'uk-UA' : 'en-GB', { day: 'numeric', month: 'long' })

  return (
    <main className="page">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <h1 className="page__title">{t('trips.title')}</h1>
        <Link to="/" className="btn btn--primary">
          {t('nav.newTrip')}
        </Link>
      </div>
      {!user && (
        <div className="page__note">
          <span>{t('trips.anonymous')}</span>
          <button type="button" className="btn btn--small" onClick={() => openAuth(true)}>
            {t('nav.signIn')}
          </button>
        </div>
      )}
      {trips.isPending && <p className="empty">{t('common.loading')}</p>}
      {trips.isError && (
        <div className="empty" role="alert">
          <p>{t('common.error')}</p>
          <button type="button" className="btn" onClick={() => trips.refetch()}>
            {t('suggest.retry')}
          </button>
        </div>
      )}
      {trips.data?.length === 0 && (
        <div className="empty">
          <h3>{t('trips.empty.title')}</h3>
          <p>{t('trips.empty.text')}</p>
        </div>
      )}
      {trips.data && trips.data.length > 0 && (
        <ul className="trip-grid">
          {trips.data.map((trip) => (
            <li key={trip.id} className="trip-card">
              {trip.cover ? (
                <img className="trip-card__cover" src={trip.cover} alt="" loading="lazy" />
              ) : (
                <div className="trip-card__cover trip-card__cover--empty" aria-hidden="true">
                  <MapPinned size={40} />
                </div>
              )}
              <div className="trip-card__body">
                <Link to={`/plan/${trip.id}`} className="trip-card__title">
                  {trip.title}
                </Link>
                <p className="trip-card__meta">
                  {trip.city}, {t('trip.stops', { n: trip.stop_count })}
                  {trip.n_days > 1 ? `, ${trip.n_days} ${t('trip.days').toLowerCase()}` : ''}
                </p>
                <p className="trip-card__meta">{t('trips.updated', { d: dateFormat.format(new Date(trip.updated_at)) })}</p>
              </div>
              <div className="trip-card__foot">
                {trip.share_slug ? (
                  <Link to={`/shared/${trip.share_slug}`} className="btn btn--quiet btn--small">
                    {t('trip.share')}
                  </Link>
                ) : (
                  <span />
                )}
                <button
                  type="button"
                  className="btn btn--quiet btn--small btn--danger"
                  onClick={() => confirm(t('trip.deleteConfirm', { title: trip.title })) && remove.mutate(trip.id)}
                >
                  <Trash2 size={15} aria-hidden="true" />
                  {t('trip.delete')}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </main>
  )
}

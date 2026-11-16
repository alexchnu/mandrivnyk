import { Clock, EyeOff, Footprints, Plus } from 'lucide-react'
import { CATEGORY } from '../lib/categories'
import { distance, duration } from '../lib/format'
import { type Translate, useT } from '../lib/i18n'
import type { Lang, Poi, Reason } from '../lib/types'

export function reasonText(reason: Reason, t: Translate, lang: Lang): string {
  if (reason.code === 'wiki_languages') return t('reason.wiki_languages', { n: reason.value ?? 0 })
  if (reason.code === 'close') return t('reason.close', { d: distance(reason.value ?? 0, lang) })
  return t(`reason.${reason.code}`)
}

interface Props {
  poi: Poi
  active: boolean
  onAdd: () => void
  onHide: () => void
  onHover: (hover: boolean) => void
}

export function PoiCard({ poi, active, onAdd, onHide, onHover }: Props) {
  const { t, lang } = useT()
  const style = CATEGORY[poi.category]
  const Glyph = style.icon
  // "close" is shown as a fact with an icon; the remaining reasons explain the ranking
  const reasons = poi.reasons.filter((r) => r.code !== 'close' && r.code !== 'open_now').slice(0, 2)
  return (
    <li
      className={`card${active ? ' card--active' : ''}`}
      onMouseEnter={() => onHover(true)}
      onMouseLeave={() => onHover(false)}
      data-poi={poi.id}
    >
      {poi.summary?.image ? (
        <img className="card__media" src={poi.summary.image} alt="" loading="lazy" />
      ) : (
        <div className="card__placeholder" style={{ background: style.color }} aria-hidden="true">
          <Glyph />
        </div>
      )}
      <div>
        <div className="card__cat" style={{ color: style.color }}>
          {t(`cat.${poi.category}`)}
        </div>
        <h3 className="card__name">{poi.name}</h3>
        {poi.summary?.extract && <p className="card__text">{poi.summary.extract}</p>}
        <ul className="card__facts">
          {poi.distance_m !== null && (
            <li>
              <Footprints aria-hidden="true" />
              {distance(poi.distance_m, lang)}
            </li>
          )}
          <li>
            <Clock aria-hidden="true" />
            {t('poi.visit', { t: duration(poi.visit_minutes, lang) })}
          </li>
          {poi.is_open !== null && (
            <li className={`status status--${poi.is_open ? 'open' : 'closed'}`}>
              {t(poi.is_open ? 'poi.open' : 'poi.closed')}
            </li>
          )}
          {reasons.map((r) => (
            <li key={r.code}>{reasonText(r, t, lang)}</li>
          ))}
        </ul>
      </div>
      <div className="card__actions">
        <button type="button" className="btn btn--primary btn--small" onClick={onAdd}>
          <Plus size={16} aria-hidden="true" />
          {t('suggest.add')}
        </button>
        <button type="button" className="btn btn--quiet btn--small" onClick={onHide}>
          <EyeOff size={15} aria-hidden="true" />
          {t('suggest.hide')}
        </button>
        <span className="card__links">
          {poi.summary?.url && (
            <a href={poi.summary.url} target="_blank" rel="noreferrer">
              {t('suggest.readMore')}
            </a>
          )}
          {poi.website && (
            <a href={poi.website} target="_blank" rel="noreferrer">
              {t('suggest.website')}
            </a>
          )}
        </span>
      </div>
    </li>
  )
}

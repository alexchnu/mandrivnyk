import { ArrowRight } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { CitySearch } from '../components/CitySearch'
import { Timeline, type TimelineItem } from '../components/Timeline'
import { useT } from '../lib/i18n'
import type { Poi, Visit } from '../lib/types'
import { type City, useTrip } from '../store/trip'

const POPULAR: { uk: string; en: string; lat: number; lon: number }[] = [
  { uk: 'Чернівці', en: 'Chernivtsi', lat: 48.2921, lon: 25.9358 },
  { uk: 'Львів', en: 'Lviv', lat: 49.8419, lon: 24.0315 },
  { uk: 'Київ', en: 'Kyiv', lat: 50.4501, lon: 30.5234 },
  { uk: 'Одеса', en: 'Odesa', lat: 46.4825, lon: 30.7233 },
  { uk: 'Кам’янець-Подільський', en: 'Kamianets-Podilskyi', lat: 48.6845, lon: 26.5853 },
  { uk: 'Ужгород', en: 'Uzhhorod', lat: 48.6208, lon: 22.2879 },
]

// A real timetable produced by the planner, frozen here as an illustration.
const SAMPLE: { uk: string; en: string; category: string; start: number; minutes: number; walk: number; meters: number }[] = [
  { uk: 'Резиденція митрополитів', en: 'Residence of Metropolitans', category: 'history', start: 600, minutes: 90, walk: 0, meters: 0 },
  { uk: 'Вірменська церква', en: 'Armenian Church', category: 'religion', start: 706, minutes: 20, walk: 16, meters: 1180 },
  { uk: 'Центральна площа і ратуша', en: 'Central Square and Town Hall', category: 'landmark', start: 733, minutes: 20, walk: 7, meters: 520 },
  { uk: 'Художній музей', en: 'Art Museum', category: 'culture', start: 755, minutes: 75, walk: 2, meters: 110 },
  { uk: 'Вулиця Ольги Кобилянської', en: 'Olha Kobylianska Street', category: 'landmark', start: 834, minutes: 30, walk: 4, meters: 290 },
]

function sampleItems(lang: 'uk' | 'en'): TimelineItem[] {
  return SAMPLE.map((s, i) => {
    const visit: Visit = {
      poi: { id: `sample${i}` } as Poi,
      arrive: s.start,
      start: s.start,
      leave: s.start + s.minutes,
      walk_minutes: s.walk,
      walk_meters: s.meters,
      optional: false,
    }
    return { id: `sample${i}`, name: s[lang], category: s.category, visitMinutes: s.minutes, visit }
  })
}

export function Home() {
  const { t, lang } = useT()
  const navigate = useNavigate()
  const draft = useTrip()

  function start(city: City) {
    const same = draft.city && Math.abs(draft.city.lat - city.lat) < 0.01 && Math.abs(draft.city.lon - city.lon) < 0.01
    if (!same || draft.stops.length === 0) draft.startIn(city)
    navigate('/plan')
  }

  return (
    <>
      <main className="home">
        <div className="home__top">
          <div>
            <h1 className="home__title">{t('home.title')}</h1>
            <p className="home__lead">{t('home.lead')}</p>
            <div className="home__search">
              <span id="home-search-label" className="home__search-label">
                {t('home.searchLabel')}
              </span>
              <CitySearch labelledBy="home-search-label" autoFocus onSelect={(p) => start({ name: p.name, lat: p.lat, lon: p.lon })} />
              <div className="home__popular">
                {t('home.popular')}:
                {POPULAR.map((c) => (
                  <button key={c.en} type="button" className="chip" onClick={() => start({ name: c[lang], lat: c.lat, lon: c.lon })}>
                    {c[lang]}
                  </button>
                ))}
              </div>
            </div>
            {draft.city && draft.stops.length > 0 && (
              <button type="button" className="btn home__continue" onClick={() => navigate('/plan')}>
                {t('home.continue')}: {draft.title || draft.city.name}
                <ArrowRight size={17} aria-hidden="true" />
              </button>
            )}
          </div>
          <figure className="home__sample" style={{ margin: 0 }}>
            <figcaption className="home__sample-caption">{t('home.sample.caption')}</figcaption>
            <div style={{ borderRadius: 8, overflow: 'hidden' }}>
              <Timeline day={0} items={sampleItems(lang)} warnings={[]} focused={null} />
            </div>
          </figure>
        </div>
        <ol className="home__how" style={{ listStyle: 'none', paddingLeft: 0, marginBottom: 0 }}>
          {([1, 2, 3] as const).map((n) => (
            <li key={n} className="home__how-step">
              <span className="stop__node" style={{ marginTop: 0, background: 'var(--route)' }} aria-hidden="true">
                {n}
              </span>
              <div>
                <h2>{t(`home.how${n}.title`)}</h2>
                <p>{t(`home.how${n}.text`)}</p>
              </div>
            </li>
          ))}
        </ol>
      </main>
      <footer className="footer">{t('footer.data')}</footer>
    </>
  )
}

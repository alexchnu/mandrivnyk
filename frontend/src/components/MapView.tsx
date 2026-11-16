import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useEffect, useMemo } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MapContainer, Marker, Polyline, Popup, TileLayer, useMap } from 'react-leaflet'
import { CATEGORY, dayColor } from '../lib/categories'
import { useT } from '../lib/i18n'
import type { PlanDay, Poi } from '../lib/types'
import type { City, Stop } from '../store/trip'

interface Props {
  city: City
  suggestions: Poi[]
  stops: Stop[]
  days: PlanDay[] | null
  activeDay: number
  focusedPoi: string | null
  onFocus: (id: string | null) => void
  onAdd?: (poi: Poi) => void
}

const iconCache = new Map<string, L.DivIcon>()

function suggestionIcon(poi: Poi, active: boolean): L.DivIcon {
  const key = `s:${poi.category}:${active}`
  let icon = iconCache.get(key)
  if (!icon) {
    const style = CATEGORY[poi.category]
    const Glyph = style.icon
    icon = L.divIcon({
      className: '',
      html: `<div class="pin${active ? ' pin--active' : ''}" style="background:${style.color}">${renderToStaticMarkup(<Glyph />)}</div>`,
      iconSize: [30, 30],
      iconAnchor: [15, 15],
      popupAnchor: [0, -14],
    })
    iconCache.set(key, icon)
  }
  return icon
}

function stopIcon(order: number, day: number, dim: boolean, active: boolean): L.DivIcon {
  const key = `t:${order}:${day}:${dim}:${active}`
  let icon = iconCache.get(key)
  if (!icon) {
    icon = L.divIcon({
      className: '',
      html: `<div class="pin pin--stop${dim ? ' pin--dim' : ''}${active ? ' pin--active' : ''}" style="background:${dayColor(day)}">${order}</div>`,
      iconSize: [32, 32],
      iconAnchor: [16, 16],
      popupAnchor: [0, -15],
    })
    iconCache.set(key, icon)
  }
  return icon
}

/** Keeps the viewport on what matters: the city first, then the whole trip. */
function Viewport({ city, stops }: { city: City; stops: Stop[] }) {
  const map = useMap()
  const cityKey = `${city.lat},${city.lon}`
  useEffect(() => {
    map.setView([city.lat, city.lon], 14)
    // only when the city changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cityKey])
  const stopKey = stops.map((s) => s.poi.id).join(',')
  useEffect(() => {
    if (stops.length < 2) return
    const bounds = L.latLngBounds(stops.map((s) => [s.poi.lat, s.poi.lon] as [number, number]))
    if (!map.getBounds().contains(bounds)) map.fitBounds(bounds, { padding: [60, 60], maxZoom: 16 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stopKey])
  useEffect(() => {
    const observer = new ResizeObserver(() => map.invalidateSize())
    observer.observe(map.getContainer())
    return () => observer.disconnect()
  }, [map])
  return null
}

export function MapView({ city, suggestions, stops, days, activeDay, focusedPoi, onFocus, onAdd }: Props) {
  const { t } = useT()
  const inTrip = useMemo(() => new Set(stops.map((s) => s.poi.id)), [stops])
  const order = useMemo(() => {
    const counters = new Map<number, number>()
    return new Map(
      stops.map((s) => {
        const n = (counters.get(s.day) ?? 0) + 1
        counters.set(s.day, n)
        return [s.poi.id, n]
      }),
    )
  }, [stops])

  return (
    <MapContainer className="map" center={[city.lat, city.lon]} zoom={14} zoomControl={false} attributionControl>
      <TileLayer
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        maxZoom={19}
      />
      <Viewport city={city} stops={stops} />
      {days?.map((day) =>
        day.geometry.length > 1 ? (
          <Polyline
            key={`${day.index}:${day.geometry.length}:${day.visits.map((v) => v.poi.id).join()}`}
            positions={day.geometry}
            pathOptions={{
              color: dayColor(day.index),
              weight: day.index === activeDay ? 5 : 3,
              opacity: day.index === activeDay ? 0.9 : 0.4,
              lineCap: 'round',
            }}
          />
        ) : null,
      )}
      {suggestions
        .filter((p) => !inTrip.has(p.id))
        .map((poi) => (
          <Marker
            key={poi.id}
            position={[poi.lat, poi.lon]}
            icon={suggestionIcon(poi, focusedPoi === poi.id)}
            title={poi.name}
            eventHandlers={{ click: () => onFocus(poi.id) }}
          >
            <Popup>
              <div className="map-popup">
                <div className="map-popup__name">{poi.name}</div>
                <div className="map-popup__meta">{t(`cat.${poi.category}`)}</div>
                {onAdd && (
                  <button type="button" className="btn btn--primary btn--small" onClick={() => onAdd(poi)}>
                    {t('suggest.add')}
                  </button>
                )}
              </div>
            </Popup>
          </Marker>
        ))}
      {stops.map((stop) => (
        <Marker
          key={stop.poi.id}
          position={[stop.poi.lat, stop.poi.lon]}
          icon={stopIcon(order.get(stop.poi.id) ?? 0, stop.day, stop.day !== activeDay, focusedPoi === stop.poi.id)}
          zIndexOffset={stop.day === activeDay ? 1000 : 500}
          title={stop.poi.name}
          eventHandlers={{ click: () => onFocus(stop.poi.id) }}
        >
          <Popup>
            <div className="map-popup">
              <div className="map-popup__name">{stop.poi.name}</div>
              <div className="map-popup__meta">{t(`cat.${stop.poi.category}`)}</div>
            </div>
          </Popup>
        </Marker>
      ))}
    </MapContainer>
  )
}

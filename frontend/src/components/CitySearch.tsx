import { useQuery } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { type KeyboardEvent, useEffect, useId, useState } from 'react'
import { api } from '../lib/api'
import { useT } from '../lib/i18n'
import type { Place } from '../lib/types'

interface Props {
  onSelect: (place: Place) => void
  compact?: boolean
  autoFocus?: boolean
  placeholder?: string
  labelledBy?: string
}

function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(timer)
  }, [value, delayMs])
  return debounced
}

export function CitySearch({ onSelect, compact, autoFocus, placeholder, labelledBy }: Props) {
  const { t, lang } = useT()
  const listId = useId()
  const [text, setText] = useState('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const query = useDebounced(text.trim(), 300)
  const enabled = query.length >= 2
  const { data, isFetching, isError } = useQuery({
    queryKey: ['places', query, lang],
    queryFn: ({ signal }) => api.places(query, lang, signal),
    enabled,
    staleTime: 10 * 60_000,
    retry: false,
  })
  const items = enabled ? (data ?? []) : []

  useEffect(() => setActive(0), [data])

  function choose(place: Place) {
    setText('')
    setOpen(false)
    onSelect(place)
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setOpen(true)
      setActive((i) => Math.min(i + 1, items.length - 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActive((i) => Math.max(i - 1, 0))
    } else if (event.key === 'Enter' && open && items[active]) {
      event.preventDefault()
      choose(items[active])
    } else if (event.key === 'Escape') {
      setOpen(false)
    }
  }

  const showList = open && enabled
  return (
    <div className={`search${compact ? ' search--compact' : ''}`}>
      <div className="search__box">
        <Search size={compact ? 17 : 21} aria-hidden="true" />
        <input
          role="combobox"
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-labelledby={labelledBy}
          aria-label={labelledBy ? undefined : (placeholder ?? t('home.searchLabel'))}
          aria-activedescendant={showList && items[active] ? `${listId}-${active}` : undefined}
          placeholder={placeholder ?? t('home.searchPlaceholder')}
          value={text}
          autoFocus={autoFocus}
          autoComplete="off"
          onChange={(e) => {
            setText(e.target.value)
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={onKeyDown}
        />
      </div>
      {showList && (
        <ul id={listId} className="search__list" role="listbox">
          {items.map((place, index) => (
            <li
              key={`${place.lat},${place.lon}`}
              id={`${listId}-${index}`}
              role="option"
              aria-selected={index === active}
              className="search__option"
              onMouseEnter={() => setActive(index)}
              onMouseDown={(e) => {
                e.preventDefault()
                choose(place)
              }}
            >
              <span className="search__option-name">{place.name}</span>
              <span className="search__option-rest">{place.label.split(', ').slice(1).join(', ')}</span>
            </li>
          ))}
          {items.length === 0 && (
            <li className="search__note" role="presentation">
              {isError ? t('search.error') : isFetching || query !== text.trim() ? t('search.searching') : t('search.empty')}
            </li>
          )}
        </ul>
      )}
    </div>
  )
}

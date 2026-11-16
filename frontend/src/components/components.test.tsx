import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Visit } from '../lib/types'
import { useSession } from '../store/session'
import { CitySearch } from './CitySearch'
import { Timeline, type TimelineItem } from './Timeline'

function wrap(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>)
}

function mockFetch(body: unknown, status = 200) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
  useSession.setState({ lang: 'uk' })
})

const PLACES = [
  { name: 'Чернівці', label: 'Чернівці, Чернівецька область, Україна', country: 'Україна', country_code: 'ua', kind: 'city', lat: 48.29, lon: 25.93 },
  { name: 'Чернівці', label: 'Чернівці, Вінницька область, Україна', country: 'Україна', country_code: 'ua', kind: 'village', lat: 48.54, lon: 28.11 },
]

describe('CitySearch', () => {
  it('searches after a pause and selects with the keyboard', async () => {
    const fetchMock = mockFetch(PLACES)
    const onSelect = vi.fn()
    wrap(<CitySearch onSelect={onSelect} />)
    const input = screen.getByRole('combobox')
    await userEvent.type(input, 'Чернів')
    const options = await screen.findAllByRole('option')
    expect(options).toHaveLength(2)
    expect(fetchMock).toHaveBeenCalledTimes(1) // one request for the whole word, not one per letter
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/v1/places?q=%D0%A7')
    await userEvent.keyboard('{ArrowDown}{Enter}')
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ lat: 48.54 }))
    expect(input).toHaveValue('')
  })

  it('does not search for a single letter', async () => {
    const fetchMock = mockFetch(PLACES)
    wrap(<CitySearch onSelect={() => undefined} />)
    await userEvent.type(screen.getByRole('combobox'), 'Ч')
    await new Promise((r) => setTimeout(r, 450))
    expect(fetchMock).not.toHaveBeenCalled()
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('explains an empty result and a failed search', async () => {
    mockFetch([])
    const { unmount } = wrap(<CitySearch onSelect={() => undefined} />)
    await userEvent.type(screen.getByRole('combobox'), 'йцукен')
    expect(await screen.findByText('Нічого не знайдено. Спробуйте іншу назву.')).toBeInTheDocument()
    unmount()
    mockFetch({ detail: 'down' }, 503)
    wrap(<CitySearch onSelect={() => undefined} />)
    await userEvent.type(screen.getByRole('combobox'), 'Львів')
    expect(await screen.findByText(/Пошук тимчасово недоступний/)).toBeInTheDocument()
  })
})

const visit = (start: number, minutes: number, walk: number): Visit => ({
  poi: {} as Visit['poi'],
  arrive: start,
  start,
  leave: start + minutes,
  walk_minutes: walk,
  walk_meters: walk * 75,
  optional: false,
})

const ITEMS: TimelineItem[] = [
  { id: 'n1', name: 'Ратуша', category: 'landmark', visitMinutes: 20, visit: visit(540, 20, 0) },
  { id: 'n2', name: 'Художній музей', category: 'culture', visitMinutes: 75, visit: visit(570, 75, 10) },
]

describe('Timeline', () => {
  it('shows times, walking legs, problems and the day total', () => {
    render(
      <Timeline
        day={0}
        items={ITEMS}
        focused={null}
        warnings={[
          { code: 'closed', poi_id: 'n2', day: 0, minutes: null },
          { code: 'waits', poi_id: 'n1', day: 0, minutes: 30 },
        ]}
      />,
    )
    expect(screen.getByText('09:00')).toBeInTheDocument()
    expect(screen.getByText('10:45')).toBeInTheDocument()
    expect(screen.getByText(/пішки 10 хв, 750 м/)).toBeInTheDocument()
    expect(screen.getByText('Цього дня зачинено')).toBeInTheDocument()
    expect(screen.getByText('Очікування відкриття: 30 хв')).toBeInTheDocument()
    expect(screen.getByText(/завершення о 10:45/)).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument() // read-only: no editing controls
  })

  it('offers editing controls and reports moves and removals', async () => {
    const onMove = vi.fn()
    const onRemove = vi.fn()
    render(<Timeline day={0} items={ITEMS} warnings={[]} focused={null} onMove={onMove} onRemove={onRemove} dayCount={1} />)
    const up = screen.getAllByRole('button', { name: 'Вище' })
    expect(up[0]).toBeDisabled()
    await userEvent.click(up[1])
    expect(onMove).toHaveBeenCalledWith(1, 0)
    await userEvent.click(screen.getAllByRole('button', { name: 'Прибрати з маршруту' })[0])
    expect(onRemove).toHaveBeenCalledWith('n1')
    await waitFor(() => expect(screen.queryByRole('combobox')).not.toBeInTheDocument()) // one day: no day selector
  })

  it('renders in English when the language is switched', () => {
    useSession.setState({ lang: 'en' })
    render(<Timeline day={0} items={ITEMS} warnings={[]} focused={null} />)
    expect(screen.getByText(/walk 10 min/)).toBeInTheDocument()
    expect(screen.getByText('Day total')).toBeInTheDocument()
  })
})

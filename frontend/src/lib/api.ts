import type { AuthResult, Lang, Place, Plan, Poi, RecommendResponse, Trip, TripSummary, User } from './types'

const BASE = '/api/v1'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

let identity: { clientId: string; token: string | null } = { clientId: '', token: null }

export function setIdentity(next: { clientId: string; token: string | null }) {
  identity = next
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { 'X-Client-Id': identity.clientId }
  if (init.body) headers['Content-Type'] = 'application/json'
  if (identity.token) headers.Authorization = `Bearer ${identity.token}`
  let response: Response
  try {
    response = await fetch(BASE + path, { ...init, headers })
  } catch {
    throw new ApiError(0, 'network')
  }
  if (response.status === 204) return undefined as T
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = body && typeof body.detail === 'string' ? body.detail : response.statusText
    throw new ApiError(response.status, detail)
  }
  return body as T
}

const post = <T>(path: string, data: unknown) => request<T>(path, { method: 'POST', body: JSON.stringify(data) })

export interface RecommendParams {
  lat: number
  lon: number
  radius_km: number
  anchor?: { lat: number; lon: number } | null
  categories: string[]
  preferences: Record<string, number>
  exclude_ids: string[]
  selected_ids: string[]
  limit: number
  lang: Lang
  open_only: boolean
}

export interface PlanParams {
  stops: { poi_id: string; visit_minutes?: number | null; day?: number }[]
  days: number
  start_date?: string | null
  day_start: string
  day_end: string
  mode: 'keep_order' | 'optimize'
}

export interface TripPayload {
  title: string
  city: string
  lat: number
  lon: number
  start_date: string | null
  n_days: number
  day_start_min: number
  day_end_min: number
  stops: { poi_id: string; day_index: number; visit_minutes: number | null; note: string }[]
}

export const api = {
  places: (q: string, lang: Lang, signal?: AbortSignal) =>
    request<Place[]>(`/places?q=${encodeURIComponent(q)}&lang=${lang}`, { signal }),
  recommend: (params: RecommendParams) => post<RecommendResponse>('/recommendations', params),
  plan: (params: PlanParams, lang: Lang) => post<Plan>(`/plans?lang=${lang}`, params),
  feedback: (items: { poi_id: string; action: string; rank?: number }[]) => post<void>('/feedback', items),
  trips: (lang: Lang) => request<TripSummary[]>(`/trips?lang=${lang}`),
  trip: (id: string, lang: Lang) => request<Trip>(`/trips/${id}?lang=${lang}`),
  sharedTrip: (slug: string, lang: Lang) => request<Trip>(`/trips/shared/${slug}?lang=${lang}`),
  createTrip: (data: TripPayload, lang: Lang) => post<Trip>(`/trips?lang=${lang}`, data),
  updateTrip: (id: string, data: TripPayload, lang: Lang) =>
    request<Trip>(`/trips/${id}?lang=${lang}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteTrip: (id: string) => request<void>(`/trips/${id}`, { method: 'DELETE' }),
  shareTrip: (id: string) => request<Trip>(`/trips/${id}/share`, { method: 'POST' }),
  unshareTrip: (id: string) => request<Trip>(`/trips/${id}/share`, { method: 'DELETE' }),
  register: (email: string, password: string, display_name: string) =>
    post<AuthResult>('/auth/register', { email, password, display_name }),
  login: (email: string, password: string) => post<AuthResult>('/auth/login', { email, password }),
  me: () => request<User>('/auth/me'),
}

export type { Poi }

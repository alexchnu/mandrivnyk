export type Lang = 'uk' | 'en'

export type CategoryId =
  | 'culture'
  | 'history'
  | 'landmark'
  | 'nature'
  | 'religion'
  | 'entertainment'
  | 'food'
  | 'nightlife'
  | 'shopping'

export interface Place {
  name: string
  label: string
  country: string
  country_code: string
  kind: string
  lat: number
  lon: number
}

export interface Summary {
  title: string
  extract: string
  image: string | null
  url: string | null
  lang: string
}

export type ReasonCode =
  | 'wiki_languages'
  | 'has_article'
  | 'close'
  | 'new_category'
  | 'open_now'
  | 'top_rated'
  | 'preference'

export interface Reason {
  code: ReasonCode
  value: number | null
}

export interface Poi {
  id: string
  name: string
  lat: number
  lon: number
  category: CategoryId
  subtype: string
  visit_minutes: number
  opening_hours: string | null
  is_open: boolean | null
  website: string | null
  wikidata: string | null
  sitelinks: number
  score: number | null
  distance_m: number | null
  reasons: Reason[]
  summary: Summary | null
}

export interface RecommendResponse {
  items: Poi[]
  total_candidates: number
  model: string
  data_status: 'fresh' | 'stale'
  enrichment: 'none' | 'pending' | 'done'
}

export type WarningCode = 'closed' | 'late' | 'waits' | 'unscheduled' | 'estimated_walk' | 'added'

export interface PlanWarning {
  code: WarningCode
  poi_id: string | null
  day: number | null
  minutes: number | null
}

export interface Visit {
  poi: Poi
  arrive: number
  start: number
  leave: number
  walk_minutes: number
  walk_meters: number
  optional: boolean
}

export interface PlanDay {
  index: number
  date: string | null
  visits: Visit[]
  walk_minutes: number
  walk_meters: number
  visit_minutes: number
  geometry: [number, number][]
}

export interface Plan {
  days: PlanDay[]
  warnings: PlanWarning[]
  unscheduled: string[]
  total_walk_minutes: number
  saved_walk_minutes: number | null
  routed: boolean
}

export interface TripStopOut {
  poi: Poi
  day_index: number
  position: number
  visit_minutes: number | null
  note: string
}

export interface TripSummary {
  id: string
  title: string
  city: string
  lat: number
  lon: number
  start_date: string | null
  n_days: number
  share_slug: string | null
  updated_at: string
  stop_count: number
  cover: string | null
}

export interface Trip extends TripSummary {
  day_start_min: number
  day_end_min: number
  stops: TripStopOut[]
  editable: boolean
}

export interface User {
  id: string
  email: string
  display_name: string
}

export interface AuthResult {
  token: string
  user: User
  claimed_trips: number
}

import {
  Camera,
  Castle,
  Church,
  Drama,
  Landmark,
  type LucideIcon,
  ShoppingBag,
  Trees,
  Utensils,
  Wine,
} from 'lucide-react'
import type { CategoryId } from './types'

export interface CategoryStyle {
  id: CategoryId
  color: string
  icon: LucideIcon
}

// Hues are spaced so that neighbours stay distinguishable on a light basemap.
export const CATEGORIES: CategoryStyle[] = [
  { id: 'culture', color: '#7A3FF2', icon: Landmark },
  { id: 'history', color: '#B4532A', icon: Castle },
  { id: 'landmark', color: '#D9306B', icon: Camera },
  { id: 'nature', color: '#2E8B4E', icon: Trees },
  { id: 'religion', color: '#4A5BD4', icon: Church },
  { id: 'entertainment', color: '#C026A8', icon: Drama },
  { id: 'food', color: '#D97A00', icon: Utensils },
  { id: 'nightlife', color: '#3B3F8C', icon: Wine },
  { id: 'shopping', color: '#0E8C9A', icon: ShoppingBag },
]

export const CATEGORY: Record<CategoryId, CategoryStyle> = Object.fromEntries(
  CATEGORIES.map((c) => [c.id, c]),
) as Record<CategoryId, CategoryStyle>

export const DAY_COLORS = ['#1F5FBF', '#D9306B', '#2E8B4E', '#D97A00', '#7A3FF2', '#0E8C9A', '#B4532A']

export const dayColor = (index: number) => DAY_COLORS[index % DAY_COLORS.length]

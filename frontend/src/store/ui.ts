import { create } from 'zustand'

export interface Toast {
  id: number
  text: string
  kind: 'info' | 'error'
}

interface UiState {
  toasts: Toast[]
  authOpen: boolean
  activeDay: number
  focusedPoi: string | null
  toast: (text: string, kind?: Toast['kind']) => void
  dismissToast: (id: number) => void
  openAuth: (open: boolean) => void
  setActiveDay: (day: number) => void
  focusPoi: (id: string | null) => void
}

let nextId = 1

export const useUi = create<UiState>((set, get) => ({
  toasts: [],
  authOpen: false,
  activeDay: 0,
  focusedPoi: null,
  toast: (text, kind = 'info') => {
    const id = nextId++
    set((s) => ({ toasts: [...s.toasts.slice(-2), { id, text, kind }] }))
    setTimeout(() => get().dismissToast(id), kind === 'error' ? 6000 : 3500)
  },
  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
  openAuth: (authOpen) => set({ authOpen }),
  setActiveDay: (activeDay) => set({ activeDay }),
  focusPoi: (focusedPoi) => set({ focusedPoi }),
}))

import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { setIdentity } from '../lib/api'
import type { Lang, User } from '../lib/types'

function newClientId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(18))
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

interface SessionState {
  lang: Lang
  clientId: string
  token: string | null
  user: User | null
  setLang: (lang: Lang) => void
  signIn: (token: string, user: User) => void
  signOut: () => void
}

export const useSession = create<SessionState>()(
  persist(
    (set) => ({
      lang: 'uk',
      clientId: newClientId(),
      token: null,
      user: null,
      setLang: (lang) => set({ lang }),
      signIn: (token, user) => set({ token, user }),
      signOut: () => set({ token: null, user: null }),
    }),
    { name: 'planner-session' },
  ),
)

const sync = (s: SessionState) => {
  setIdentity({ clientId: s.clientId, token: s.token })
  document.documentElement.lang = s.lang
}
sync(useSession.getState())
useSession.subscribe(sync)

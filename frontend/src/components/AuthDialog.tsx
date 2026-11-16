import { useQueryClient } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { type FormEvent, useEffect, useRef, useState } from 'react'
import { ApiError, api } from '../lib/api'
import { type MessageKey, useT } from '../lib/i18n'
import { useSession } from '../store/session'
import { useUi } from '../store/ui'

const ERRORS: Record<number, MessageKey> = {
  401: 'auth.wrong',
  409: 'auth.exists',
  422: 'auth.invalid',
  429: 'auth.tooMany',
  0: 'common.offline',
}

export function AuthDialog() {
  const { t } = useT()
  const open = useUi((s) => s.authOpen)
  const openAuth = useUi((s) => s.openAuth)
  const toast = useUi((s) => s.toast)
  const signIn = useSession((s) => s.signIn)
  const queryClient = useQueryClient()
  const ref = useRef<HTMLDialogElement>(null)
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const email = String(form.get('email'))
    const password = String(form.get('password'))
    setBusy(true)
    setError(null)
    try {
      const result =
        mode === 'login'
          ? await api.login(email, password)
          : await api.register(email, password, String(form.get('name')))
      signIn(result.token, result.user)
      await queryClient.invalidateQueries({ queryKey: ['trips'] })
      toast(t('auth.welcome', { name: result.user.display_name }))
      if (result.claimed_trips > 0) toast(t('auth.claimed', { n: result.claimed_trips }))
      openAuth(false)
    } catch (err) {
      const status = err instanceof ApiError ? err.status : -1
      setError(t(ERRORS[status] ?? 'common.error'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <dialog ref={ref} className="dialog" onClose={() => openAuth(false)} aria-labelledby="auth-title">
      <div className="dialog__head">
        <h2 id="auth-title" className="dialog__title">
          {t(mode === 'login' ? 'auth.signIn' : 'auth.register')}
        </h2>
        <button type="button" className="icon-btn" onClick={() => openAuth(false)} aria-label={t('common.close')}>
          <X size={20} />
        </button>
      </div>
      <form className="dialog__body" onSubmit={submit}>
        {error && (
          <p className="dialog__error" role="alert">
            {error}
          </p>
        )}
        {mode === 'register' && (
          <label className="field">
            {t('auth.name')}
            <input name="name" required maxLength={80} autoComplete="name" />
          </label>
        )}
        <label className="field">
          {t('auth.email')}
          <input name="email" type="email" required autoComplete="email" />
        </label>
        <label className="field">
          {t('auth.password')}
          <input
            name="password"
            type="password"
            required
            minLength={mode === 'register' ? 8 : 1}
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            aria-describedby={mode === 'register' ? 'password-hint' : undefined}
          />
          {mode === 'register' && <span id="password-hint">{t('auth.passwordHint')}</span>}
        </label>
        <button type="submit" className="btn btn--primary" disabled={busy}>
          {t(mode === 'login' ? 'auth.submitSignIn' : 'auth.submitRegister')}
        </button>
        <button
          type="button"
          className="dialog__switch"
          onClick={() => {
            setMode(mode === 'login' ? 'register' : 'login')
            setError(null)
          }}
        >
          {t(mode === 'login' ? 'auth.toRegister' : 'auth.toSignIn')}
        </button>
      </form>
    </dialog>
  )
}

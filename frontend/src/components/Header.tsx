import { LogOut, Route, UserRound } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useT } from '../lib/i18n'
import { useSession } from '../store/session'
import { useUi } from '../store/ui'

export function Header() {
  const { t, lang } = useT()
  const { user, setLang, signOut } = useSession()
  const openAuth = useUi((s) => s.openAuth)
  return (
    <header className="header">
      <Link to="/" className="brand">
        <span className="brand__blaze" aria-hidden="true" />
        {t('app.name')}
      </Link>
      <div className="header__spacer" />
      <Link to="/trips" className="btn btn--quiet btn--small">
        <Route size={17} aria-hidden="true" />
        <span>{t('nav.myTrips')}</span>
      </Link>
      <div className="lang" role="group" aria-label={t('common.language')}>
        <button type="button" aria-pressed={lang === 'uk'} onClick={() => setLang('uk')}>
          УКР
        </button>
        <button type="button" aria-pressed={lang === 'en'} onClick={() => setLang('en')}>
          ENG
        </button>
      </div>
      {user ? (
        <>
          <span className="header__user">{user.display_name}</span>
          <button type="button" className="icon-btn" onClick={signOut} aria-label={t('nav.signOut')} title={t('nav.signOut')}>
            <LogOut size={18} />
          </button>
        </>
      ) : (
        <button type="button" className="btn btn--small" onClick={() => openAuth(true)} aria-label={t('nav.signIn')}>
          <UserRound size={16} aria-hidden="true" />
          <span>{t('nav.signIn')}</span>
        </button>
      )}
    </header>
  )
}

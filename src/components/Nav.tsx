import { useEffect, useState } from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'
import Container from './Container'
import Icon from './Icon'
import Logo from './Logo'
import { navLinks } from '../data/site'

export default function Nav() {
  const [scrolled, setScrolled] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const { pathname } = useLocation()

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  useEffect(() => {
    setMenuOpen(false)
  }, [pathname])

  useEffect(() => {
    document.body.style.overflow = menuOpen ? 'hidden' : ''
    return () => {
      document.body.style.overflow = ''
    }
  }, [menuOpen])

  const solid = scrolled && !menuOpen

  return (
    <header
      className={`fixed inset-x-0 top-0 z-50 border-b transition-colors duration-300 ease-editorial ${
        solid
          ? 'border-ink/10 bg-paper/95 backdrop-blur'
          : `border-transparent on-dark ${menuOpen ? 'bg-ink' : 'bg-transparent'}`
      }`}
    >
      <Container>
        <div className="flex h-20 items-center justify-between gap-6 md:h-24">
          <Link
            to="/"
            aria-label="Synora Music Group — home"
            className="flex shrink-0 items-center py-2"
          >
            <Logo variant="primary" invert={!solid} className="hidden h-11 sm:block md:h-12" />
            <Logo variant="compact" invert={!solid} className="h-10 sm:hidden" />
          </Link>

          <nav aria-label="Primary" className="hidden lg:block">
            <ul className="flex items-center gap-7 xl:gap-9">
              {navLinks.map((link) => (
                <li key={link.to}>
                  <NavLink
                    to={link.to}
                    className={({ isActive }) =>
                      `border-b border-transparent pb-1 text-[11px] font-semibold uppercase tracking-[0.14em] transition-colors duration-200 ${
                        solid
                          ? `text-ink/70 hover:text-ink ${isActive ? 'border-ink text-ink' : ''}`
                          : `text-paper/75 hover:text-paper ${isActive ? 'border-paper text-paper' : ''}`
                      }`
                    }
                  >
                    {link.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>

          <button
            type="button"
            onClick={() => setMenuOpen((open) => !open)}
            aria-expanded={menuOpen}
            aria-controls="mobile-menu"
            aria-label={menuOpen ? 'Close menu' : 'Open menu'}
            className={`-mr-2 p-2 lg:hidden ${solid ? 'text-ink' : 'text-paper'}`}
          >
            <Icon name={menuOpen ? 'close' : 'menu'} className="h-6 w-6" />
          </button>
        </div>
      </Container>

      {menuOpen && (
        <div id="mobile-menu" className="on-dark h-[calc(100dvh-5rem)] overflow-y-auto bg-ink lg:hidden">
          <Container className="py-10">
            <ul className="flex flex-col gap-1">
              {navLinks.map((link) => (
                <li key={link.to}>
                  <NavLink
                    to={link.to}
                    className={({ isActive }) =>
                      `block border-b border-paper/10 py-5 text-2xl font-black tracking-[-0.02em] ${
                        isActive ? 'text-paper' : 'text-paper/70'
                      }`
                    }
                  >
                    {link.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </Container>
        </div>
      )}
    </header>
  )
}

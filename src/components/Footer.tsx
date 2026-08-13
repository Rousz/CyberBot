import { Link } from 'react-router-dom'
import Container from './Container'
import Icon from './Icon'
import Logo from './Logo'
import PulseMark from './PulseMark'
import { legalLinks, navLinks, site, socials } from '../data/site'

export default function Footer() {
  return (
    <footer className="on-dark bg-ink text-paper">
      <Container className="py-16 md:py-20">
        <div className="grid gap-12 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,1fr)]">
          <div>
            <Link to="/" aria-label="Synora Music Group — home" className="inline-block">
              <Logo variant="primary" invert className="h-14" />
            </Link>
            <p className="mt-6 max-w-xs text-sm leading-relaxed text-paper/70">
              A record label built on in-house production, disciplined release planning, and
              human-supervised technology.
            </p>
            <PulseMark className="mt-8 h-4 w-8 text-paper/40" />
          </div>

          <nav aria-label="Sitemap">
            <h2 className="eyebrow text-paper/50">Sitemap</h2>
            <ul className="mt-6 space-y-3">
              <li>
                <Link to="/" className="text-sm text-paper/75 transition-colors hover:text-paper">
                  Home
                </Link>
              </li>
              {navLinks.map((link) => (
                <li key={link.to}>
                  <Link
                    to={link.to}
                    className="text-sm text-paper/75 transition-colors hover:text-paper"
                  >
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>

          <div className="space-y-10">
            <div>
              <h2 className="eyebrow text-paper/50">Legal</h2>
              <ul className="mt-6 space-y-3">
                {legalLinks.map((link) => (
                  <li key={link.to}>
                    <Link
                      to={link.to}
                      className="text-sm text-paper/75 transition-colors hover:text-paper"
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>

            <div>
              <h2 className="eyebrow text-paper/50">Contact</h2>
              <a
                href={`mailto:${site.email}`}
                className="mt-6 inline-block text-sm text-paper/75 transition-colors hover:text-paper"
              >
                {site.email}
              </a>
              <ul className="mt-6 flex items-center gap-5">
                {socials.map((social) => (
                  <li key={social.label}>
                    <a
                      href={social.href}
                      target="_blank"
                      rel="noreferrer noopener"
                      aria-label={social.label}
                      className="block text-paper/60 transition-colors hover:text-paper"
                    >
                      <Icon name={social.icon} className="h-5 w-5" />
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>

        <div className="mt-16 flex flex-col gap-3 border-t border-paper/15 pt-8 text-xs text-paper/55 md:flex-row md:items-center md:justify-between">
          <p>
            {site.legalEntity} · {site.registration}
          </p>
          <p>
            © {new Date().getFullYear()} {site.name}. All rights reserved.
          </p>
        </div>
      </Container>
    </footer>
  )
}

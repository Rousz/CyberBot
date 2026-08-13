import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

type Variant = 'primary' | 'secondary'
type Tone = 'light' | 'dark'

type ButtonProps = {
  children: ReactNode
  to?: string
  href?: string
  type?: 'button' | 'submit'
  variant?: Variant
  tone?: Tone
  disabled?: boolean
  className?: string
}

const base =
  'inline-flex items-center justify-center gap-2.5 border px-7 py-3.5 text-xs font-semibold uppercase tracking-[0.16em] transition-colors duration-300 ease-editorial disabled:cursor-not-allowed disabled:opacity-50'

const styles: Record<Tone, Record<Variant, string>> = {
  light: {
    primary: 'border-ink bg-ink text-paper hover:bg-paper hover:text-ink',
    secondary: 'border-ink/25 bg-transparent text-ink hover:border-ink hover:bg-ink hover:text-paper',
  },
  dark: {
    primary: 'border-paper bg-paper text-ink hover:bg-transparent hover:text-paper',
    secondary: 'border-paper/30 bg-transparent text-paper hover:border-paper hover:bg-paper hover:text-ink',
  },
}

export default function Button({
  children,
  to,
  href,
  type = 'button',
  variant = 'primary',
  tone = 'light',
  disabled = false,
  className = '',
}: ButtonProps) {
  const classes = `${base} ${styles[tone][variant]} ${className}`

  if (to) {
    return (
      <Link to={to} className={classes}>
        {children}
      </Link>
    )
  }

  if (href) {
    const external = href.startsWith('http')
    return (
      <a
        href={href}
        className={classes}
        {...(external ? { target: '_blank', rel: 'noreferrer noopener' } : {})}
      >
        {children}
      </a>
    )
  }

  return (
    <button type={type} disabled={disabled} className={classes}>
      {children}
    </button>
  )
}

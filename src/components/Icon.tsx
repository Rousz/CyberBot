import type { ReactNode } from 'react'

export type IconName =
  | 'team'
  | 'ai'
  | 'globe'
  | 'network'
  | 'arrowRight'
  | 'arrowDown'
  | 'chevronDown'
  | 'download'
  | 'menu'
  | 'close'
  | 'mail'
  | 'spotify'
  | 'appleMusic'
  | 'youtube'
  | 'instagram'
  | 'x'
  | 'linkedin'

const strokeIcons: Partial<Record<IconName, ReactNode>> = {
  team: (
    <>
      <path d="M9 11a3.25 3.25 0 1 0 0-6.5A3.25 3.25 0 0 0 9 11Z" />
      <path d="M16.5 11.25a2.75 2.75 0 1 0 0-5.5" />
      <path d="M3 19.5v-.75A4.75 4.75 0 0 1 7.75 14h2.5A4.75 4.75 0 0 1 15 18.75v.75" />
      <path d="M17.25 14.25A4.25 4.25 0 0 1 21 18.45v1.05" />
    </>
  ),
  ai: (
    <>
      <rect x="7" y="7" width="10" height="10" rx="2" />
      <path d="M10.25 10.75h3.5v2.5h-3.5z" />
      <path d="M10 4v3M14 4v3M10 17v3M14 17v3M4 10h3M4 14h3M17 10h3M17 14h3" />
    </>
  ),
  globe: (
    <>
      <circle cx="12" cy="12" r="8.75" />
      <path d="M3.25 12h17.5" />
      <path d="M12 3.25c2.2 2.4 3.45 5.5 3.45 8.75S14.2 18.35 12 20.75c-2.2-2.4-3.45-5.5-3.45-8.75S9.8 5.65 12 3.25Z" />
    </>
  ),
  network: (
    <>
      <circle cx="12" cy="4.75" r="2.25" />
      <circle cx="4.75" cy="18" r="2.25" />
      <circle cx="19.25" cy="18" r="2.25" />
      <path d="M10.4 6.6 6.35 15.9M13.6 6.6l4.05 9.3M7 18h10" />
    </>
  ),
  arrowRight: <path d="M4.5 12h15m0 0-5.5-5.5M19.5 12 14 17.5" />,
  arrowDown: <path d="M12 4.5v15m0 0L6.5 14M12 19.5 17.5 14" />,
  chevronDown: <path d="m6 9.5 6 5.5 6-5.5" />,
  download: <path d="M12 3.75v11.5m0 0-4.5-4.5M12 15.25l4.5-4.5M4.5 19.5h15" />,
  menu: <path d="M3.5 7h17M3.5 12h17M3.5 17h17" />,
  close: <path d="M5.5 5.5l13 13M18.5 5.5l-13 13" />,
  mail: (
    <>
      <rect x="2.75" y="5.25" width="18.5" height="13.5" rx="2" />
      <path d="m3.5 6.5 8.5 6.25L20.5 6.5" />
    </>
  ),
  spotify: (
    <>
      <circle cx="12" cy="12" r="9.25" />
      <path d="M7.15 9.3c3.2-.85 6.6-.5 9.4 1.05" />
      <path d="M7.8 12.35c2.65-.65 5.45-.35 7.85.9" />
      <path d="M8.5 15.25c2.1-.5 4.3-.25 6.15.75" />
    </>
  ),
  appleMusic: (
    <>
      <rect x="3" y="3" width="18" height="18" rx="5.5" />
      <path d="M10.4 15.6V8.75l5-1.15v6.5" />
      <circle cx="8.9" cy="15.7" r="1.5" />
      <circle cx="13.9" cy="14.35" r="1.5" />
    </>
  ),
  youtube: (
    <>
      <rect x="2.5" y="5.25" width="19" height="13.5" rx="4" />
      <path d="M10.5 9.4l5.2 2.6-5.2 2.6z" />
    </>
  ),
  instagram: (
    <>
      <rect x="3.25" y="3.25" width="17.5" height="17.5" rx="5" />
      <circle cx="12" cy="12" r="4" />
      <circle cx="16.9" cy="7.1" r="1" />
    </>
  ),
}

const filledIcons: Partial<Record<IconName, ReactNode>> = {
  x: (
    <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231 5.451-6.231Zm-1.161 17.52h1.833L7.084 4.126H5.117l11.966 15.644Z" />
  ),
  linkedin: (
    <path d="M6.94 21.5H3.56V8.98h3.38V21.5ZM5.25 7.5a1.96 1.96 0 1 1 0-3.92 1.96 1.96 0 0 1 0 3.92ZM21.5 21.5h-3.37v-6.09c0-1.45-.03-3.32-2.02-3.32-2.03 0-2.34 1.58-2.34 3.21v6.2H10.4V8.98h3.24v1.71h.05a3.55 3.55 0 0 1 3.2-1.76c3.42 0 4.06 2.25 4.06 5.18v7.39Z" />
  ),
}

type IconProps = {
  name: IconName
  className?: string
  strokeWidth?: number
}

export default function Icon({ name, className = 'h-5 w-5', strokeWidth = 1.5 }: IconProps) {
  const filled = filledIcons[name]

  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      aria-hidden="true"
      focusable="false"
      fill={filled ? 'currentColor' : 'none'}
      stroke={filled ? 'none' : 'currentColor'}
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {filled ?? strokeIcons[name]}
    </svg>
  )
}

export const site = {
  name: 'Synora Music Group',
  shortName: 'SMG',
  tagline: 'Music, engineered with purpose.',
  url: 'https://synoramusicgroup.com',

  // Replace with the label's real domain addresses.
  email: 'contact@synoramusicgroup.com',
  copyrightEmail: 'copyright@synoramusicgroup.com',
  pressEmail: 'press@synoramusicgroup.com',

  // Placeholder legal entity line — replace with the registered company details.
  legalEntity: '[Legal Company Name]',
  registration: '[Country / Registration No.]',

  // Swap in the Formspree (or equivalent) form ID once the account is created.
  formEndpoint: 'https://formspree.io/f/YOUR_FORM_ID',

  pressKitUrl: '/press/synora-music-group-press-kit.pdf',

  // Placeholder values for the legal pages.
  legalUpdated: '[Month Year]',
  jurisdiction: '[Country / Jurisdiction]',
} as const

export type SocialLink = {
  label: string
  href: string
  icon: 'instagram' | 'x' | 'linkedin' | 'youtube'
}

export const socials: SocialLink[] = [
  { label: 'Instagram', href: 'https://instagram.com/', icon: 'instagram' },
  { label: 'X', href: 'https://x.com/', icon: 'x' },
  { label: 'LinkedIn', href: 'https://linkedin.com/', icon: 'linkedin' },
  { label: 'YouTube', href: 'https://youtube.com/', icon: 'youtube' },
]

export const navLinks = [
  { label: 'About', to: '/about' },
  { label: 'Production & Technology', to: '/production' },
  { label: 'Roster', to: '/roster' },
  { label: 'Label Partners', to: '/partners' },
  { label: 'Press', to: '/press' },
  { label: 'Contact', to: '/contact' },
]

export const legalLinks = [
  { label: 'Privacy Policy', to: '/privacy' },
  { label: 'Terms of Service', to: '/terms' },
  { label: 'Copyright Policy', to: '/copyright' },
]

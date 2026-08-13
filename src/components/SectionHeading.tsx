import type { ReactNode } from 'react'
import Reveal from './Reveal'

export default function SectionHeading({
  eyebrow,
  title,
  lead,
  tone = 'light',
  className = '',
  as: Heading = 'h2',
}: {
  eyebrow?: string
  title: ReactNode
  lead?: ReactNode
  tone?: 'light' | 'dark'
  className?: string
  as?: 'h1' | 'h2' | 'h3'
}) {
  const muted = tone === 'dark' ? 'text-paper/70' : 'text-steel'

  return (
    <Reveal className={`max-w-3xl ${className}`}>
      {eyebrow && <p className={`eyebrow mb-5 ${muted}`}>{eyebrow}</p>}
      <Heading className="text-display-md font-black">{title}</Heading>
      {lead && <p className={`mt-6 text-lead ${muted}`}>{lead}</p>}
    </Reveal>
  )
}

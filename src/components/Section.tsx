import type { ReactNode } from 'react'
import Container from './Container'

type Tone = 'paper' | 'mist' | 'ink'

const tones: Record<Tone, string> = {
  paper: 'bg-paper text-ink',
  mist: 'bg-mist text-ink',
  ink: 'bg-ink text-paper on-dark',
}

const spacings = {
  default: 'py-20 md:py-28 lg:py-32',
  tight: 'py-14 md:py-16',
}

export default function Section({
  children,
  id,
  tone = 'paper',
  spacing = 'default',
  className = '',
  bare = false,
}: {
  children: ReactNode
  id?: string
  tone?: Tone
  spacing?: keyof typeof spacings
  className?: string
  bare?: boolean
}) {
  return (
    <section id={id} className={`${tones[tone]} ${spacings[spacing]} ${className}`}>
      {bare ? children : <Container>{children}</Container>}
    </section>
  )
}

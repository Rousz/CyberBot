import type { ReactNode } from 'react'
import Container from './Container'
import PulseMark from './PulseMark'

export default function PageHeader({
  eyebrow,
  title,
  lead,
}: {
  eyebrow: string
  title: ReactNode
  lead?: ReactNode
}) {
  return (
    <section className="on-dark bg-ink pb-16 pt-32 text-paper md:pb-24 md:pt-44">
      <Container>
        <div className="flex items-center gap-4 text-paper/60">
          <PulseMark className="h-4 w-8" />
          <p className="eyebrow">{eyebrow}</p>
        </div>
        <h1 className="mt-8 max-w-4xl text-display-lg font-black">{title}</h1>
        {lead && <p className="mt-8 max-w-2xl text-lead text-paper/70">{lead}</p>}
      </Container>
    </section>
  )
}

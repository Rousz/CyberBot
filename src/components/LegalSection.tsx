import type { ReactNode } from 'react'
import Reveal from './Reveal'

export default function LegalSection({
  title,
  children,
}: {
  title: string
  children: ReactNode
}) {
  return (
    <Reveal as="section" className="border-t border-ink/12 pt-10">
      <h2 className="text-display-sm font-black">{title}</h2>
      <div className="mt-6 space-y-4 text-sm leading-relaxed text-steel">{children}</div>
    </Reveal>
  )
}

import type { ReactNode } from 'react'
import Reveal from './Reveal'

const columnClasses = {
  2: 'md:grid-cols-2',
  3: 'md:grid-cols-2 lg:grid-cols-3',
  4: 'md:grid-cols-2 lg:grid-cols-4',
}

export default function CardGrid({
  children,
  columns = 3,
  as = 'ul',
  className = '',
}: {
  children: ReactNode
  columns?: keyof typeof columnClasses
  as?: 'ul' | 'ol'
  className?: string
}) {
  const Tag = as as 'ul'

  return (
    <Reveal className={className}>
      <Tag className={`grid gap-px border border-ink/12 bg-ink/12 ${columnClasses[columns]}`}>
        {children}
      </Tag>
    </Reveal>
  )
}

import type { ReactNode } from 'react'

type Tone = 'light' | 'dark'
type Variant = 'framed' | 'flush'

const styles: Record<Tone, Record<Variant, string>> = {
  light: {
    framed: 'border border-ink/12 bg-paper text-ink transition-colors duration-500 ease-editorial hover:border-ink/40',
    flush: 'bg-paper text-ink',
  },
  dark: {
    framed: 'border border-paper/15 bg-ink text-paper transition-colors duration-500 ease-editorial hover:border-paper/40',
    flush: 'bg-ink text-paper',
  },
}

export default function Card({
  children,
  tone = 'light',
  variant = 'framed',
  as = 'div',
  className = '',
}: {
  children: ReactNode
  tone?: Tone
  variant?: Variant
  as?: 'div' | 'article'
  className?: string
}) {
  const Tag = as as 'div'

  return (
    <Tag className={`flex h-full flex-col p-8 md:p-10 ${styles[tone][variant]} ${className}`}>
      {children}
    </Tag>
  )
}

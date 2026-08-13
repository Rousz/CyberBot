import type { ReactNode } from 'react'

export default function Container({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <div className={`mx-auto w-full max-w-container px-6 md:px-10 lg:px-16 ${className}`}>
      {children}
    </div>
  )
}

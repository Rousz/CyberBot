import PulseMark from './PulseMark'

const ratios = {
  portrait: 'aspect-[3/4]',
  square: 'aspect-square',
  wide: 'aspect-[4/3]',
}

function initials(label: string) {
  return label
    .split(' ')
    .filter((word) => /[a-z]/i.test(word[0] ?? ''))
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase())
    .join('')
}

export default function MediaPlaceholder({
  src,
  label,
  ratio = 'portrait',
  className = '',
}: {
  src?: string
  label: string
  ratio?: keyof typeof ratios
  className?: string
}) {
  if (src) {
    return (
      <img
        src={src}
        alt={label}
        loading="lazy"
        decoding="async"
        className={`${ratios[ratio]} w-full object-cover grayscale ${className}`}
      />
    )
  }

  return (
    <div
      role="img"
      aria-label={`${label} — photograph placeholder`}
      className={`${ratios[ratio]} flex w-full flex-col items-center justify-center gap-3 bg-mist text-steel ${className}`}
    >
      <PulseMark className="h-5 w-10" />
      <span className="text-sm font-semibold tracking-[0.2em]">{initials(label)}</span>
    </div>
  )
}

const sources = {
  primary: { src: '/brand/synora-logo.png', width: 495, height: 320 },
  compact: { src: '/brand/synora-mark.png', width: 527, height: 320 },
}

export default function Logo({
  variant = 'primary',
  invert = false,
  className = '',
}: {
  variant?: 'primary' | 'compact'
  invert?: boolean
  className?: string
}) {
  const { src, width, height } = sources[variant]

  return (
    <img
      src={src}
      alt="Synora Music Group"
      width={width}
      height={height}
      className={`w-auto object-contain transition-[filter] duration-300 ${
        invert ? 'logo-invert' : ''
      } ${className}`}
    />
  )
}

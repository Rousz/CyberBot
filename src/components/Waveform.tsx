const BAR_COUNT = 96
const VIEW_WIDTH = 1200
const VIEW_HEIGHT = 400

const bars = Array.from({ length: BAR_COUNT }, (_, i) => {
  const t = i / BAR_COUNT
  const envelope = 0.35 + 0.65 * Math.sin(Math.PI * t) ** 0.6
  const detail =
    0.55 +
    0.24 * Math.sin(i * 0.9) +
    0.14 * Math.sin(i * 2.3 + 1.2) +
    0.09 * Math.sin(i * 5.1 + 0.4)
  const height = Math.max(0.06, Math.min(1, envelope * detail))
  return { x: (i / BAR_COUNT) * VIEW_WIDTH, height }
})

export default function Waveform({ className = '' }: { className?: string }) {
  const barWidth = (VIEW_WIDTH / BAR_COUNT) * 0.34

  return (
    <svg
      viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
      preserveAspectRatio="none"
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient id="waveform-fade" x1="0" x2="1">
          <stop offset="0" stopColor="white" stopOpacity="0" />
          <stop offset="0.28" stopColor="white" stopOpacity="0.85" />
          <stop offset="0.72" stopColor="white" stopOpacity="0.85" />
          <stop offset="1" stopColor="white" stopOpacity="0" />
        </linearGradient>
        <mask id="waveform-mask">
          <rect width={VIEW_WIDTH} height={VIEW_HEIGHT} fill="url(#waveform-fade)" />
        </mask>
      </defs>

      <g mask="url(#waveform-mask)" fill="currentColor">
        {bars.map((bar, i) => {
          const h = bar.height * VIEW_HEIGHT * 0.86
          return (
            <rect
              key={i}
              x={bar.x}
              y={(VIEW_HEIGHT - h) / 2}
              width={barWidth}
              height={h}
              opacity={0.25 + (i % 4) * 0.12}
            />
          )
        })}
      </g>
    </svg>
  )
}

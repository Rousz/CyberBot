export default function PulseMark({ className = 'h-4 w-8' }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 48 26"
      className={className}
      aria-hidden="true"
      focusable="false"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
    >
      <circle cx="24" cy="23" r="1.75" fill="currentColor" stroke="none" />
      <path d="M17.5 22.5a6.5 6.5 0 0 1 13 0" />
      <path d="M11 22.5a13 13 0 0 1 26 0" />
      <path d="M4.5 22.5a19.5 19.5 0 0 1 39 0" />
    </svg>
  )
}

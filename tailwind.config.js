/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#0A0A0A',
        paper: '#FFFFFF',
        mist: '#F4F4F4',
        steel: '#6E6E6E',
      },
      fontFamily: {
        sans: [
          'Inter',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'Helvetica Neue',
          'Arial',
          'sans-serif',
        ],
      },
      fontSize: {
        'display-xl': ['clamp(2.75rem, 7vw, 6.25rem)', { lineHeight: '0.94', letterSpacing: '-0.035em' }],
        'display-lg': ['clamp(2.25rem, 5vw, 4.25rem)', { lineHeight: '1', letterSpacing: '-0.03em' }],
        'display-md': ['clamp(1.75rem, 3.2vw, 2.75rem)', { lineHeight: '1.06', letterSpacing: '-0.02em' }],
        'display-sm': ['clamp(1.375rem, 2vw, 1.75rem)', { lineHeight: '1.15', letterSpacing: '-0.015em' }],
        lead: ['clamp(1.0625rem, 1.35vw, 1.25rem)', { lineHeight: '1.6' }],
        eyebrow: ['0.75rem', { lineHeight: '1', letterSpacing: '0.18em' }],
      },
      maxWidth: {
        container: '1440px',
      },
      transitionTimingFunction: {
        editorial: 'cubic-bezier(0.16, 1, 0.3, 1)',
      },
    },
  },
  plugins: [],
}

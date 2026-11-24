/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // Neutral greys only so photos are judged without a colour cast; orange marks the one
        // primary action, the active state and focus.
        camera: {
          bg: '#0b0b0b',
          surface: '#151515',
          raised: '#1d1d1d',
          hover: '#272727',
          border: '#3a3a3a',
          subtle: '#262626',
          text: '#ececec',
          muted: '#a3a3a3',
          faint: '#737373',
          accent: '#f97316', // THE accent colour: the only place it is defined (CSS uses theme('colors.camera.accent'))
          'accent-hover': '#fb8a3c',
          'accent-press': '#e8650c',
          overlay: 'rgba(21, 21, 21, 0.82)',
          'accent-ink': '#160a02',
          ok: '#4ade80',
          warn: '#facc15',
          danger: '#f87171',
          'danger-fill': '#dc2626',
          cold: '#60a5fa',
          // Legacy aliases, kept so existing views keep working
          success: '#4ade80',
          error: '#f87171',
          warning: '#facc15',
        },
      },
      borderRadius: {
        control: '6px',
        inner: '8px',
        card: '10px',
      },
      fontFamily: {
        sans: ['system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
    },
  },
  plugins: [],
}

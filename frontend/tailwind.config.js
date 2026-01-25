/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Dark theme optimized for photography
        'camera': {
          'bg': '#0a0a0a',
          'surface': '#141414',
          'border': '#2a2a2a',
          'text': '#e5e5e5',
          'muted': '#737373',
          'accent': '#f97316', // Orange accent
          'success': '#22c55e',
          'error': '#ef4444',
          'warning': '#eab308',
        },
      },
    },
  },
  plugins: [],
}

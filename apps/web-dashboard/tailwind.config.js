/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        /* GeoSentinel core palette */
        base:      '#06070D', // page background
        surface:   '#12162A', // card surface
        elevated:  '#1B2038', // elevated / hover
        hairline:  '#262C48', // borders
        accent: {
          DEFAULT: '#38BDF8',
          light:   '#7DD3FC',
        },
        hazard: {
          stable:    '#22C55E',
          watch:     '#EAB308',
          warning:   '#F97316',
          critical:  '#EF4444',
        },
        ink: {
          DEFAULT: '#F1F5F9', // primary text
          dim:     '#94A3B8', // secondary
          muted:   '#566178', // muted / timestamps
        },
        primary: {
          50: '#f0fdf4',
          100: '#dcfce7',
          200: '#bbf7d0',
          300: '#86efac',
          400: '#4ade80',
          500: '#22c55e',
          600: '#16a34a',
          700: '#15803d',
          800: '#166534',
          900: '#14532d',
        },
        risk: {
          very_low: '#1a9850',
          low: '#91cf60',
          moderate: '#ffffbf',
          high: '#fc8d59',
          very_high: '#d73027',
          watch: '#fee08b',
          warning: '#fc8d59',
          evacuation: '#d73027',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
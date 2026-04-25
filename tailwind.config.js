/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        navy: {
          950: '#060d18',
          900: '#0b1525',
          850: '#0f1d30',
          800: '#142338',
          750: '#1a2d45',
          700: '#203554',
          600: '#2c4a6e',
          500: '#3d6491',
        },
        gold: {
          400: '#e2b96f',
          500: '#c9973a',
          600: '#a87830',
        },
        steel: {
          100: '#e8edf4',
          200: '#c8d4e0',
          300: '#a0b4c8',
          400: '#7a96b0',
          500: '#567898',
          600: '#3d5f7a',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      animation: {
        'fade-in':    'fadeIn 0.18s ease-out',
        'slide-down': 'slideDown 0.18s ease-out',
        'scale-in':   'scaleIn 0.15s ease-out',
      },
      keyframes: {
        fadeIn:    { '0%': { opacity: '0' }, '100%': { opacity: '1' } },
        slideDown: { '0%': { opacity: '0', transform: 'translateY(-6px)' }, '100%': { opacity: '1', transform: 'translateY(0)' } },
        scaleIn:   { '0%': { opacity: '0', transform: 'scale(0.97)' }, '100%': { opacity: '1', transform: 'scale(1)' } },
      },
    },
  },
  plugins: [],
}

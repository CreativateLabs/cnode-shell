/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Light-Theme (zur c:node-Landingpage). `ink` = Canvas UND Text-auf-Primary
        // (near-white → gut lesbar auf dem blauen Primary #4B6EF5). `paper` = Haupttext (dunkel).
        ink: '#F7F8FC',        // heller Canvas / Text auf farbigen Buttons
        surface: '#FFFFFF',    // Panels
        surface2: '#F1F3F9',   // raised cards / bubbles
        surface3: '#E8EBF3',   // hover / inputs
        line: '#E2E5EF',       // borders
        line2: '#CFD4E1',
        // Tenant-konfigurierbar: RGB-Triplet-CSS-Vars (App setzt sie aus brand.primary/secondary).
        // RGB-Triplet erhält die /opacity-Utilities (primary/15 etc.).
        primary: 'rgb(var(--c-primary) / <alpha-value>)',
        secondary: 'rgb(var(--c-secondary) / <alpha-value>)',
        primaryDim: '#3B57D6',
        paper: '#181B26',      // Haupttext (dunkel auf hell)
        muted: '#5C6273',      // secondary text
        faint: '#868D9E',      // tertiary text
        cmint: '#22A37D',      // etwas dunkler → lesbar auf hell
        crose: '#DB2777',
        cviolet: '#7C5CE0',
        cblue: '#3B82F6',      // Gemini (Cloud)
      },
      fontFamily: {
        display: ['"Bricolage Grotesque"', 'system-ui', 'sans-serif'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'monospace'],
      },
      keyframes: {
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(6px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'fade-down': {
          '0%': { opacity: '0', transform: 'translateY(-8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'panel-in': {
          '0%': { opacity: '0', transform: 'translateX(24px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
        'overlay-in': {
          '0%': { opacity: '0', transform: 'scale(0.97)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
        'fade-in': {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        blink: { '0%,100%': { opacity: '1' }, '50%': { opacity: '0' } },
      },
      animation: {
        'fade-up': 'fade-up 0.32s cubic-bezier(0.22,1,0.36,1) both',
        'fade-down': 'fade-down 0.32s cubic-bezier(0.22,1,0.36,1) both',
        'panel-in': 'panel-in 0.34s cubic-bezier(0.22,1,0.36,1) both',
        'overlay-in': 'overlay-in 0.24s cubic-bezier(0.22,1,0.36,1) both',
        'fade-in': 'fade-in 0.2s ease both',
        blink: 'blink 1s step-end infinite',
      },
    },
  },
  plugins: [],
}

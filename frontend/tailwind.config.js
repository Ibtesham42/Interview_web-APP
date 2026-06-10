/** @type {import('tailwindcss').Config} */
module.exports = {
  // Dual theme: light is the design default; `.dark` on <html> opts into dark.
  // Driven by CSS variables (see index.css :root / :root.dark) so every
  // utility that maps to a token flips automatically with the theme.
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  corePlugins: {
    // Preflight (Tailwind's global reset) is OFF during the migration so it
    // never clobbers the existing index.css base while both systems coexist.
    // Re-enable in the final migration phase once components are ported.
    preflight: false,
  },
  theme: {
    extend: {
      colors: {
        // Surfaces
        canvas: 'var(--bg-primary)',
        surface: 'var(--bg-secondary)',
        'surface-2': 'var(--bg-tertiary)',
        elevated: 'var(--bg-elevated)',
        field: 'var(--bg-input)',
        // Brand
        primary: {
          DEFAULT: 'var(--primary)',
          light: 'var(--primary-light)',
          dark: 'var(--primary-dark)',
          subtle: 'var(--primary-subtle)',
        },
        accent: 'var(--accent)',
        // Text (ink)
        ink: {
          DEFAULT: 'var(--text-primary)',
          muted: 'var(--text-secondary)',
          subtle: 'var(--text-tertiary)',
          disabled: 'var(--text-disabled)',
        },
        // Semantic state tokens (surface / text / border per state)
        success: {
          DEFAULT: 'var(--color-success)',
          surface: 'var(--color-success-surface)',
          border: 'var(--color-success-border)',
        },
        warning: {
          DEFAULT: 'var(--color-warning)',
          surface: 'var(--color-warning-surface)',
          border: 'var(--color-warning-border)',
        },
        danger: {
          DEFAULT: 'var(--color-danger)',
          surface: 'var(--color-danger-surface)',
          border: 'var(--color-danger-border)',
        },
        info: {
          DEFAULT: 'var(--color-info)',
          surface: 'var(--color-info-surface)',
          border: 'var(--color-info-border)',
        },
      },
      borderColor: {
        DEFAULT: 'var(--border-default)',
        subtle: 'var(--border-subtle)',
        strong: 'var(--border-strong)',
        focus: 'var(--border-focus)',
      },
      borderRadius: {
        sm: 'var(--radius-sm)',
        md: 'var(--radius-md)',
        lg: 'var(--radius-lg)',
        xl: 'var(--radius-xl)',
      },
      boxShadow: {
        sm: 'var(--shadow-sm)',
        md: 'var(--shadow-md)',
        lg: 'var(--shadow-lg)',
        focus: 'var(--shadow-focus)',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
      maxWidth: {
        app: 'var(--max-width)',
      },
    },
  },
  plugins: [],
};

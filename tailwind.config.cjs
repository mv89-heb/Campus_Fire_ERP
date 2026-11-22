/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/templates/**/*.html",
    "./app/static/**/*.js"
  ],
  prefix: "tw-",
  corePlugins: {
    preflight: false
  },
  theme: {
    extend: {
      colors: {
        brand: "var(--color-primary)",
        surface: "var(--color-surface)",
        canvas: "var(--color-bg)",
        ink: "var(--color-text)",
        muted: "var(--color-text-muted)",
        success: "var(--color-success)",
        warning: "var(--color-warning)",
        danger: "var(--color-danger)"
      },
      fontFamily: {
        sans: ["Heebo", "Assistant", "system-ui", "sans-serif"]
      }
    }
  },
  plugins: []
};

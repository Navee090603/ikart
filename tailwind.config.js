// Built by scripts/build_css.sh (Tailwind 3.4.17 standalone CLI) into
// storefront/static/storefront/css/tailwind.css. Tailwind handles layout utilities
// only; every colour, radius and font comes from the IKart tokens in ikart.css.
module.exports = {
  content: [
    "./storefront/templates/**/*.html",
    "./templates/**/*.html",
    "./storefront/static/storefront/js/**/*.js",
    "./storefront/*.py",
  ],
  corePlugins: { preflight: true },
  theme: {
    extend: {
      colors: {
        brand: "var(--brand)", "brand-soft": "var(--brand-soft)", "brand-strong": "var(--brand-strong)", accent: "var(--accent)",
        ink: "var(--ink)", muted: "var(--ink-muted)", surface: "var(--surface)", raised: "var(--surface-raised)", line: "var(--border)",
        success: "var(--success)", "success-soft": "var(--success-soft)", danger: "var(--danger)", "danger-soft": "var(--danger-soft)",
      },
      fontFamily: { sans: ["DM Sans", "DM Sans Ext", "Nunito Sans", "system-ui", "sans-serif"] },
    },
  },
};

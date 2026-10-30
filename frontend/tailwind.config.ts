import typography from "@tailwindcss/typography";
import type { Config } from "tailwindcss";

const v = (name: string) => `var(--${name})`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: v("bg"),
        panel: v("panel"),
        text: v("text"),
        muted: v("muted"),
        border: v("border"),
        bubble: v("bubble"),
        surface: v("surface"),
        accent: v("accent"),
        "on-accent": v("on-accent"),
        dialogue: v("dialogue"),
        "key-bg": v("key-bg"),
        "note-bg": v("note-bg"),
        "note-bar": v("note-bar"),
        "warn-bg": v("warn-bg"),
        "warn-bar": v("warn-bar"),
        caution: v("caution"),
      },
      keyframes: {
        shimmer: { "0%": { transform: "translateX(-100%)" }, "100%": { transform: "translateX(100%)" } },
        "dot-pulse": { "0%, 100%": { opacity: "0.25" }, "50%": { opacity: "1" } },
        "sketch-pulse": { "0%, 100%": { opacity: "1" }, "50%": { opacity: "0.45" } },
      },
      animation: {
        // The delay holds the sweep back until the sketch has finished building up.
        shimmer: "shimmer 2.2s ease-in-out 1.2s infinite",
        "dot-pulse": "dot-pulse 1.2s ease-in-out infinite",
        // Backwards fill keeps pieces solid until their staggered delay, after the build-up.
        "sketch-pulse": "sketch-pulse 1.6s ease-in-out infinite backwards",
      },
      boxShadow: {
        soft: v("shadow"),
        lift: v("shadow-lift"),
      },
      borderRadius: {
        lg: "8px",
        xl: "10px",
        "2xl": "12px",
      },
      fontFamily: {
        sans: ['"Instrument Sans"', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'sans-serif'],
        display: ['"Instrument Sans"', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'sans-serif'],
        serif: ['Literata', 'Georgia', '"Times New Roman"', 'serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'Menlo', 'monospace'],
      },
      typography: {
        DEFAULT: {
          css: {
            maxWidth: "none",
            color: v("text"),
            fontFamily: '"Literata", Georgia, "Times New Roman", serif',
            fontSize: "1.125rem",
            lineHeight: "1.7",
            "--tw-prose-body": v("text"),
            "--tw-prose-headings": v("text"),
            "--tw-prose-bold": v("text"),
            // The plugin default (#111827) is unreadable on the dark code background.
            "--tw-prose-code": v("text"),
            "--tw-prose-links": v("accent"),
            "--tw-prose-counters": v("muted"),
            "--tw-prose-bullets": v("muted"),
            "--tw-prose-hr": v("border"),
            "--tw-prose-quotes": v("muted"),
            "--tw-prose-quote-borders": v("border"),
            "--tw-prose-th-borders": v("border"),
            "--tw-prose-td-borders": v("border"),
            h1: { fontSize: "1.75rem", fontWeight: "600", letterSpacing: "-0.02em", lineHeight: "1.2", marginTop: "1.6em", marginBottom: "0.6em" },
            h2: { fontSize: "1.4rem", fontWeight: "600", letterSpacing: "-0.015em", lineHeight: "1.2", marginTop: "1.5em", marginBottom: "0.5em" },
            h3: { fontSize: "1.15rem", fontWeight: "600", letterSpacing: "-0.01em", lineHeight: "1.2", marginTop: "1.4em", marginBottom: "0.4em" },
            "blockquote p:first-of-type::before": { content: "none" },
            "blockquote p:last-of-type::after": { content: "none" },
            blockquote: { fontStyle: "normal", fontWeight: "400" },
            "code::before": { content: "none" },
            "code::after": { content: "none" },
            code: {
              fontWeight: "400",
              fontSize: "0.88em",
              backgroundColor: v("bubble"),
              padding: "0.1em 0.35em",
              borderRadius: "4px",
            },
            table: { display: "block", overflowX: "auto" },
            "th, td": { border: `1px solid ${v("border")}`, padding: "0.3rem 0.7rem" },
            pre: { margin: "0", padding: "0", backgroundColor: "#1f1b16", color: "#e7dfd0", borderRadius: "0" },
            "pre code": {
              backgroundColor: "transparent",
              padding: "1rem",
              display: "block",
              fontSize: "0.85rem",
              borderRadius: "0",
              color: "inherit",
            },
          },
        },
      },
    },
  },
  plugins: [typography],
} satisfies Config;

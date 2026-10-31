export const cx = (...parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(" ");

export const focusRing = "focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent";

// The background is chosen per use (bg-bg on the page, bg-surface inside a card), so it is not part of the base.
export const fieldBase = `rounded-xl border border-border px-3 py-2 data-[invalid]:border-warn-bar ${focusRing}`;

// A ready-made text field on the page background, for controls that take a className (the model combobox).
export const fieldClass = `${fieldBase} bg-bg`;

export const buttonVariants = {
  primary: `inline-flex items-center justify-center gap-1.5 rounded-xl bg-accent px-3.5 py-2 font-semibold text-on-accent shadow-soft disabled:opacity-50 ${focusRing} focus-visible:outline-offset-2`,
  secondary: `rounded-xl border border-border bg-surface px-3.5 py-2 text-muted shadow-soft hover:text-text disabled:opacity-50 ${focusRing}`,
  // The confirm button of a destructive action; tinted rather than filled so it reads in both themes.
  destructive: `inline-flex items-center justify-center gap-1.5 rounded-xl border border-warn-bar bg-warn-bg px-3.5 py-2 font-semibold text-warn-bar disabled:opacity-50 ${focusRing}`,
  ghost: `rounded px-2 py-1 text-muted hover:text-text disabled:opacity-50 ${focusRing}`,
  danger: `inline-flex items-center justify-center gap-1.5 rounded px-2 py-1 text-warn-bar disabled:opacity-50 ${focusRing}`,
  link: `rounded text-[12px] text-accent underline ${focusRing}`,
  // Only the focus ring, for buttons that bring their own look (icon buttons, banner actions).
  bare: focusRing,
  // Nothing at all, for buttons that bring their own focus style as well (the dark code-block controls).
  none: "",
} as const;

export type ButtonVariant = keyof typeof buttonVariants;

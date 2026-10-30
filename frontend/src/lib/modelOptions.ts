export interface ModelGroup {
  vendor: string;
  items: string[];
}

export const OTHER_GROUP = "Other";

const byText = (a: string, b: string) => a.localeCompare(b, "en", { sensitivity: "base" });

/** Groups by the text before the first "/"; ids without one share a trailing "Other" group. */
export function groupModels(models: readonly string[], query = ""): ModelGroup[] {
  const q = query.trim().toLowerCase();
  const byVendor = new Map<string, string[]>();
  for (const m of new Set(models)) {
    if (q && !m.toLowerCase().includes(q)) continue;
    const slash = m.indexOf("/");
    const vendor = slash > 0 ? m.slice(0, slash) : OTHER_GROUP;
    byVendor.set(vendor, [...(byVendor.get(vendor) ?? []), m]);
  }
  const groups = [...byVendor].map(([vendor, items]) => ({ vendor, items: items.sort(byText) }));
  // A real vendor literally named "Other" sorts with the rest; only the ungrouped bucket goes last.
  return groups.sort((a, b) => Number(a.vendor === OTHER_GROUP) - Number(b.vendor === OTHER_GROUP) || byText(a.vendor, b.vendor));
}

/** The typed text, when it is not a listed id, so providers with partial /models can still be used. */
export function customCandidate(models: readonly string[], query: string): string | null {
  const typed = query.trim();
  if (!typed || models.includes(typed)) return null;
  return typed;
}

interface AutoFetchInput {
  baseUrl: string;
  needsKey: boolean;
  /** A key was typed and the field was left; never fetch mid-typing. */
  keyCommitted: boolean;
  /** Set when editing a saved profile, whose stored key the server may use. */
  saved: { baseUrl: string } | null;
}

function isHttpUrl(value: string): boolean {
  try {
    const u = new URL(value);
    const web = u.protocol === "http:" || u.protocol === "https:";
    return web && (u.hostname.includes(".") || u.hostname === "localhost");
  } catch {
    return false;
  }
}

/**
 * The saved key is only ever used for the saved URL, so editing the URL never ships it
 * somewhere new without the user pressing the button themselves.
 */
export function shouldAutoFetch({ baseUrl, needsKey, keyCommitted, saved }: AutoFetchInput): boolean {
  const url = baseUrl.trim();
  if (!isHttpUrl(url)) return false;
  if (!needsKey || keyCommitted) return true;
  return saved !== null && saved.baseUrl.trim() === url;
}

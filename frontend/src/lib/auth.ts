import { ApiError } from "../api";

// These mirror Username and Password in models.py as hints only; the server stays authoritative.
const USERNAME = /^[a-z0-9_-]{3,32}$/;
export const PASSWORD_MIN = 10;
export const PASSWORD_MAX = 128;

// The server lowercases names, so the form does too and the hint judges what will actually be sent.
export const normalizeUsername = (raw: string) => raw.trim().toLowerCase();

export function usernameHint(raw: string): string | null {
  return USERNAME.test(normalizeUsername(raw)) ? null : "3-32 characters: letters, digits, _ or -";
}

export function passwordHint(password: string): string | null {
  if (password.length < PASSWORD_MIN) return `At least ${PASSWORD_MIN} characters`;
  if (password.length > PASSWORD_MAX) return `At most ${PASSWORD_MAX} characters`;
  return null;
}

export function retryMessage(seconds: number | undefined): string {
  if (!seconds) return "Too many attempts, try again later";
  if (seconds < 90) return `Too many attempts, try again in ${seconds} ${seconds === 1 ? "second" : "seconds"}`;
  const minutes = Math.ceil(seconds / 60);
  return `Too many attempts, try again in ${minutes} minutes`;
}

// The server words 401/403/409/422 for the form (and keeps them generic on purpose), so those pass through.
export function authErrorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.status === 429 ? retryMessage(err.retryAfter) : err.message;
  return "Could not reach the server. Check your connection and try again.";
}

// Entries under this prefix hold one user's data and are removed on sign-out. Device settings such as
// the theme deliberately stay outside it.
export const USER_STORAGE_PREFIX = "lumio:user:";

export function clearUserStorage(stores: Storage[] = [localStorage, sessionStorage]) {
  for (const store of stores) {
    try {
      for (const key of Object.keys(store)) if (key.startsWith(USER_STORAGE_PREFIX)) store.removeItem(key);
    } catch {
      /* storage unavailable: nothing was written either */
    }
  }
}

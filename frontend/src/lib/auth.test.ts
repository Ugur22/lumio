import { describe, expect, it } from "vitest";
import { ApiError } from "../api";
import {
  authErrorMessage,
  clearUserStorage,
  normalizeUsername,
  passwordHint,
  retryMessage,
  USER_STORAGE_PREFIX,
  usernameHint,
} from "./auth";

describe("usernameHint", () => {
  it("accepts what the server accepts, after lowercasing", () => {
    expect(usernameHint("Ada_Lovelace-1")).toBeNull();
    expect(usernameHint("abc")).toBeNull();
    expect(usernameHint("a".repeat(32))).toBeNull();
  });

  it("flags length and characters", () => {
    expect(usernameHint("ab")).not.toBeNull();
    expect(usernameHint("a".repeat(33))).not.toBeNull();
    expect(usernameHint("has space")).not.toBeNull();
    expect(usernameHint("dots.no")).not.toBeNull();
  });
});

describe("normalizeUsername", () => {
  it("trims and lowercases like the server", () => {
    expect(normalizeUsername("  Alice ")).toBe("alice");
  });
});

describe("passwordHint", () => {
  it("enforces 10 to 128 characters", () => {
    expect(passwordHint("123456789")).toMatch(/10/);
    expect(passwordHint("1234567890")).toBeNull();
    expect(passwordHint("x".repeat(128))).toBeNull();
    expect(passwordHint("x".repeat(129))).toMatch(/128/);
  });
});

describe("retryMessage", () => {
  it("counts seconds, then minutes", () => {
    expect(retryMessage(1)).toBe("Too many attempts, try again in 1 second");
    expect(retryMessage(30)).toBe("Too many attempts, try again in 30 seconds");
    expect(retryMessage(89)).toBe("Too many attempts, try again in 89 seconds");
    expect(retryMessage(90)).toBe("Too many attempts, try again in 2 minutes");
    expect(retryMessage(900)).toBe("Too many attempts, try again in 15 minutes");
  });

  it("still reads well without a Retry-After", () => {
    expect(retryMessage(undefined)).toBe("Too many attempts, try again later");
  });
});

describe("authErrorMessage", () => {
  it("passes the server's wording through", () => {
    expect(authErrorMessage(new ApiError("Invalid username or password", 401))).toBe("Invalid username or password");
    expect(authErrorMessage(new ApiError("That username is taken", 409))).toBe("That username is taken");
  });

  it("words a 429 from Retry-After rather than the server text", () => {
    expect(authErrorMessage(new ApiError("Too many failed attempts; try again later", 429, 45))).toBe(
      "Too many attempts, try again in 45 seconds",
    );
  });

  it("explains a network failure", () => {
    expect(authErrorMessage(new TypeError("Failed to fetch"))).toMatch(/reach the server/);
  });
});

function fakeStorage(entries: Record<string, string>) {
  const data = { ...entries };
  return Object.assign(data, { removeItem: (k: string) => void delete data[k] }) as unknown as Storage;
}

describe("clearUserStorage", () => {
  it("removes per-user entries and leaves device settings", () => {
    const local = fakeStorage({ theme: "dark", [`${USER_STORAGE_PREFIX}draft`]: "secret" });
    const session = fakeStorage({ [`${USER_STORAGE_PREFIX}x`]: "1", other: "2" });
    clearUserStorage([local, session]);
    expect(Object.keys(local)).toEqual(["theme", "removeItem"]);
    expect(Object.keys(session)).toEqual(["other", "removeItem"]);
  });
});

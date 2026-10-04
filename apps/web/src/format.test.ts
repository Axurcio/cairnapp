import { describe, expect, it } from "vitest";

import { formatBytes, formatValue, humanize, safeNext } from "./format";

describe("safeNext", () => {
  it("keeps same-site paths", () => {
    expect(safeNext("/journeys/abc")).toBe("/journeys/abc");
  });

  it.each([null, "", "https://evil.example", "//evil.example", "/\\evil.example", "journeys"])(
    "falls back to / for %s",
    (next) => {
      expect(safeNext(next)).toBe("/");
    },
  );
});

describe("formatting", () => {
  it("humanizes identifiers", () => {
    expect(humanize("hand_shaking.duration")).toBe("Hand shaking duration");
  });

  it("formats sizes", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(3 * 1024 * 1024)).toBe("3.0 MB");
  });

  it("formats observation values", () => {
    expect(formatValue(null)).toBe("—");
    expect(formatValue(["a", "b"])).toBe("a, b");
    expect(formatValue(true)).toBe("Yes");
    expect(formatValue(3)).toBe("3");
  });
});

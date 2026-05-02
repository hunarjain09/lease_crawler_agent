import { describe, expect, it } from "vitest";
import { addLeaks, type Leak } from "../../src/state.js";

const leak = (id: string, title = id): Leak => ({
  id,
  source_url: "https://example.com",
  title,
  severity: "med",
  detail: title,
});

describe("addLeaks", () => {
  it("returns incoming when state is empty", () => {
    const incoming = [leak("a"), leak("b")];
    expect(addLeaks([], incoming)).toEqual(incoming);
  });

  it("dedupes by id and keeps the existing entry", () => {
    const existing = leak("a", "first");
    const updated = leak("a", "second");
    const result = addLeaks([existing], [updated, leak("b")]);
    expect(result.map((l) => l.id)).toEqual(["a", "b"]);
    expect(result[0]?.title).toBe("first");
  });

  it("preserves first-seen order", () => {
    const result = addLeaks(
      [leak("a"), leak("b")],
      [leak("c"), leak("a"), leak("d")],
    );
    expect(result.map((l) => l.id)).toEqual(["a", "b", "c", "d"]);
  });
});

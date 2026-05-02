import { describe, expect, it } from "vitest";
import {
  addLeaks,
  appendTurn,
  emptyState,
  HISTORY_LIMIT,
  type ChatTurn,
  type Leak,
} from "../../src/state.js";

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

describe("emptyState", () => {
  it("returns a fresh blank session", () => {
    const s = emptyState();
    expect(s).toEqual({ leaks: [], summary: "", lastUrl: null, history: [], roundCount: 0 });
  });

  it("resets roundCount to 0", () => {
    const s = emptyState();
    expect(s.roundCount).toBe(0);
  });
});

describe("appendTurn", () => {
  const turn = (role: "user" | "assistant", content: string): ChatTurn => ({ role, content });

  it("appends in order", () => {
    const result = appendTurn([turn("user", "a")], turn("assistant", "b"));
    expect(result.map((t) => t.content)).toEqual(["a", "b"]);
  });

  it("trims to the most recent HISTORY_LIMIT entries", () => {
    let history: ChatTurn[] = [];
    for (let i = 0; i < HISTORY_LIMIT + 5; i++) {
      history = appendTurn(history, turn("user", `m${i}`));
    }
    expect(history).toHaveLength(HISTORY_LIMIT);
    expect(history[0]?.content).toBe(`m${5}`);
    expect(history[history.length - 1]?.content).toBe(`m${HISTORY_LIMIT + 4}`);
  });
});

import { describe, expect, it } from "vitest";
import { classify } from "../../src/classifier.js";

describe("classify", () => {
  it("detects bare URL", () => {
    expect(classify("https://example.com/foo")).toEqual({
      kind: "url",
      url: "https://example.com/foo",
    });
  });

  it("classifies walkthrough requests", () => {
    expect(classify("make me a walkthrough")).toEqual({ kind: "walkthrough" });
    expect(classify("can I get a video recap")).toEqual({ kind: "walkthrough" });
  });

  it("falls through to chat", () => {
    expect(classify("hi")).toEqual({ kind: "chat" });
  });

  it("URL inside larger text still classifies as url", () => {
    expect(
      classify("check this out https://avalon.com/sunnyvale please"),
    ).toEqual({
      kind: "url",
      url: "https://avalon.com/sunnyvale",
    });
  });
});

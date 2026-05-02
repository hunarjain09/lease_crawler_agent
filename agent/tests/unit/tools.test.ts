import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { analyze, ask, crawl } from "../../src/tools.js";

const baseUrl = "http://127.0.0.1:8000";

describe("tools", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("crawl posts to /crawl with the url and returns the body", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          content: "<html>ok</html>",
          metadata: { url: "https://x.com", status: 200, fetched_at: "2026-05-02T00:00:00Z" },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );

    const result = await crawl("https://x.com");
    expect(result.content).toBe("<html>ok</html>");

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe(`${baseUrl}/crawl`);
    expect(JSON.parse(init.body)).toEqual({ url: "https://x.com" });
  });

  it("analyze posts content + context and returns leaks", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          leaks: [
            {
              id: "abc",
              source_url: "https://x.com",
              title: "Furnished premium",
              severity: "med",
              detail: "$1,281/mo",
            },
          ],
          summary: "Base rent $3,415",
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );

    const result = await analyze("<html/>", []);
    expect(result.leaks).toHaveLength(1);
    expect(result.summary).toContain("3,415");

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe(`${baseUrl}/analyze`);
    expect(JSON.parse(init.body)).toEqual({ content: "<html/>", context: [] });
  });

  it("ask posts question + grounding context", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({ answer: "Base rent is $3,415." }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );

    const result = await ask("What's the rent?", [], "Avalon SV", [
      { role: "user", content: "Tell me about Avalon" },
      { role: "assistant", content: "It's a 1bd at $3,415" },
    ]);
    expect(result.answer).toContain("3,415");

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe(`${baseUrl}/ask`);
    const body = JSON.parse(init.body);
    expect(body.question).toBe("What's the rent?");
    expect(body.summary).toBe("Avalon SV");
    expect(body.history).toHaveLength(2);
  });

  it("throws on non-2xx", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: "boom" }), {
        status: 502,
        headers: { "content-type": "application/json" },
      }),
    );

    await expect(crawl("https://x.com")).rejects.toThrow(/POST \/crawl failed: 502/);
  });
});

import type { Leak } from "./state.js";

const BASE = process.env.SERVER_BASE_URL ?? "http://127.0.0.1:8000";

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`POST ${path} failed: ${res.status} ${text}`);
  }
  return (await res.json()) as T;
}

export type CrawlMetadata = { url: string; status: number; fetched_at: string };
export type CrawlResponse = { content: string; metadata: CrawlMetadata };

export async function crawl(url: string): Promise<CrawlResponse> {
  return postJson<CrawlResponse>("/crawl", { url });
}

export type AnalyzeResponse = { leaks: Leak[]; summary: string };

export async function analyze(content: string, context: Leak[]): Promise<AnalyzeResponse> {
  return postJson<AnalyzeResponse>("/analyze", { content, context });
}

export const _internals = { BASE };

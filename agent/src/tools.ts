import type { Leak } from "./state.js";

const BASE = process.env.SERVER_BASE_URL ?? "http://127.0.0.1:8000";

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const bodyStr = JSON.stringify(body);
  const start = performance.now();
  console.log(`[tools] -> POST ${path} body_chars=${bodyStr.length}`);
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: bodyStr,
  });
  const text = await res.text().catch(() => "");
  const ms = (performance.now() - start).toFixed(1);
  const reqId = res.headers.get("x-request-id") ?? "-";
  console.log(
    `[tools] <- POST ${path} status=${res.status} ms=${ms} req_id=${reqId} resp_chars=${text.length}`,
  );
  if (!res.ok) {
    throw new Error(`POST ${path} failed: ${res.status} ${text}`);
  }
  return JSON.parse(text) as T;
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

export type ChatTurn = { role: "user" | "assistant"; content: string };
export type AskResponse = { answer: string };

export async function ask(
  question: string,
  leaks: Leak[],
  summary: string,
  history: ChatTurn[],
): Promise<AskResponse> {
  return postJson<AskResponse>("/ask", { question, leaks, summary, history });
}

export const _internals = { BASE };

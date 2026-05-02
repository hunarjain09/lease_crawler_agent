export type Severity = "low" | "med" | "high";

export type Leak = {
  id: string;
  source_url: string;
  title: string;
  severity: Severity;
  detail: string;
  evidence?: string;
};

export type ChatTurn = { role: "user" | "assistant"; content: string };

export type SessionState = {
  leaks: Leak[];
  summary: string;
  lastUrl: string | null;
  history: ChatTurn[];
  /** Count of handled inbound messages this session. Caps at MAX_ROUNDS_PER_SESSION. */
  roundCount: number;
};

export const HISTORY_LIMIT = 20;
export const MAX_ROUNDS_PER_SESSION = 10;

export function emptyState(): SessionState {
  return { leaks: [], summary: "", lastUrl: null, history: [], roundCount: 0 };
}

export function addLeaks(state: Leak[], incoming: Leak[]): Leak[] {
  const seen = new Set(state.map((l) => l.id));
  const merged = [...state];
  for (const leak of incoming) {
    if (seen.has(leak.id)) continue;
    seen.add(leak.id);
    merged.push(leak);
  }
  return merged;
}

export function appendTurn(history: ChatTurn[], turn: ChatTurn): ChatTurn[] {
  const next = [...history, turn];
  if (next.length <= HISTORY_LIMIT) return next;
  return next.slice(next.length - HISTORY_LIMIT);
}

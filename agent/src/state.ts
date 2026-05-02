export type Severity = "low" | "med" | "high";

export type Leak = {
  id: string;
  source_url: string;
  title: string;
  severity: Severity;
  detail: string;
  evidence?: string;
};

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

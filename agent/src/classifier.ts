export type Intent =
  | { kind: "url"; url: string }
  | { kind: "walkthrough" }
  | { kind: "chat" };

const URL_RE = /\bhttps?:\/\/[^\s<>"']+/i;
const WALKTHROUGH_RE = /\b(walkthrough|video|recap)\b/i;

export function classify(text: string): Intent {
  const url = text.match(URL_RE);
  if (url) return { kind: "url", url: url[0] };
  if (WALKTHROUGH_RE.test(text)) return { kind: "walkthrough" };
  return { kind: "chat" };
}

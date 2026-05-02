/**
 * Mock-Photon harness: drives the agent's request handler without spectrum-ts.
 * Reads messages from argv (one per arg) or stdin (one per line). Maintains
 * per-sender state in-memory across the messages in a single invocation.
 *
 * Usage:
 *   pnpm mock --sender +15551234567 https://www.avaloncommunities.com/...
 *   pnpm mock --sender +15551234567 "what's the rent" "is parking extra"
 *   echo -e "https://x.com\nwhat's the rent" | pnpm mock --sender +15551234567
 *
 * Logs the same lines the live agent does — `[mock] inbound`, `[tools] -> POST`,
 * `[tools] <- POST`, `[mock] reply`. The req_id from the server is included so
 * you can grep one ID across both server and mock logs.
 */
import { classify } from "../src/classifier.js";
import {
  addLeaks,
  appendTurn,
  emptyState,
  MAX_ROUNDS_PER_SESSION,
  type SessionState,
} from "../src/state.js";
import { analyze, ask, crawl } from "../src/tools.js";

function parseArgs(argv: string[]): { sender: string; messages: string[] } {
  let sender = "+15550000000";
  const messages: string[] = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--sender" && i + 1 < argv.length) {
      sender = argv[++i]!;
    } else if (a === "--help" || a === "-h") {
      console.log(
        "Usage: pnpm mock --sender +1xxx <message1> <message2> ...\n" +
          "       echo -e 'msg1\\nmsg2' | pnpm mock --sender +1xxx",
      );
      process.exit(0);
    } else {
      messages.push(a!);
    }
  }
  return { sender, messages };
}

async function readStdin(): Promise<string[]> {
  if (process.stdin.isTTY) return [];
  const chunks: Buffer[] = [];
  for await (const chunk of process.stdin) chunks.push(chunk as Buffer);
  return Buffer.concat(chunks)
    .toString("utf8")
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l.length > 0);
}

async function handle(
  text: string,
  senderId: string,
  stateMap: Map<string, SessionState>,
): Promise<{ reply: string }> {
  console.log(`[mock] inbound sender=${senderId} text="${text.slice(0, 200)}"`);
  const intent = classify(text);
  console.log(`[mock] intent: ${intent.kind}`);

  // New URL = fresh session for this sender.
  if (intent.kind === "url") {
    if (stateMap.has(senderId)) {
      console.log(`[mock] session.reset reason=new_url sender=${senderId}`);
    }
    stateMap.set(senderId, emptyState());
  }
  let state = stateMap.get(senderId);
  if (!state) {
    state = emptyState();
    stateMap.set(senderId, state);
  }

  let reply: string;
  if (intent.kind === "url") {
    const { content } = await crawl(intent.url);
    const result = await analyze(content, state.leaks);
    state.leaks = addLeaks(state.leaks, result.leaks);
    state.summary = result.summary;
    state.lastUrl = intent.url;

    const suggestQ =
      "Based on the listing data, suggest exactly 3 short questions a renter would want answered next. Reply with ONLY the 3 questions, one per line, no numbering or bullets or preamble.";
    const { answer: rawSuggestions } = await ask(suggestQ, result.leaks, result.summary, []);
    const suggestions = rawSuggestions
      .split("\n")
      .map((l) => l.trim().replace(/^[-*•\d.)\s]+/, "").trim())
      .filter((l) => l.length > 0)
      .slice(0, 3);
    const bullets = suggestions.map((s) => `• ${s}`).join("\n");
    reply = `${result.summary}\n\nAsk me about:\n${bullets}\n\n(round 1/10)`;
  } else if (intent.kind === "walkthrough") {
    reply =
      state.leaks.length === 0
        ? "No listings discussed yet. Send me a URL first."
        : `Walkthrough video isn't wired yet (F1). Tracking ${state.leaks.length} leaks.`;
  } else {
    if (state.leaks.length === 0 && !state.summary) {
      reply = "Send me a listing URL to get started.";
    } else {
      const { answer } = await ask(text, state.leaks, state.summary, state.history);
      state.history = appendTurn(state.history, { role: "user", content: text });
      state.history = appendTurn(state.history, { role: "assistant", content: answer });
      reply = `${answer}\n\n(round ${state.roundCount + 1}/10)`;
    }
  }

  state.roundCount += 1;
  console.log(
    `[mock] reply -> ${senderId} round=${state.roundCount}/${MAX_ROUNDS_PER_SESSION}: ${reply.replace(/\n/g, " ").slice(0, 400)}`,
  );

  if (state.roundCount >= MAX_ROUNDS_PER_SESSION) {
    stateMap.delete(senderId);
    console.log(
      `[mock] session.reset reason=cap_reached sender=${senderId} cap=${MAX_ROUNDS_PER_SESSION}`,
    );
  }

  return { reply };
}

async function main() {
  const { sender, messages: argMessages } = parseArgs(process.argv.slice(2));
  const stdinMessages = await readStdin();
  const messages = [...argMessages, ...stdinMessages];

  if (messages.length === 0) {
    console.error("error: no messages supplied (pass via args or pipe via stdin).");
    console.error("       pnpm mock --sender +1234 'https://...' 'follow-up question'");
    process.exit(1);
  }

  console.log(
    `[mock] starting session sender=${sender} messages=${messages.length} server=${
      process.env.SERVER_BASE_URL ?? "http://127.0.0.1:8000"
    }`,
  );

  const stateMap = new Map<string, SessionState>();
  for (const msg of messages) {
    try {
      await handle(msg, sender, stateMap);
      const s = stateMap.get(sender);
      if (s) {
        console.log(
          `[mock] state.leaks=${s.leaks.length} state.history_turns=${s.history.length} state.summary_chars=${s.summary.length} state.roundCount=${s.roundCount}`,
        );
      } else {
        console.log(`[mock] state: <none — session reset>`);
      }
      console.log("---");
    } catch (err) {
      console.error(`[mock] error on message "${msg.slice(0, 80)}":`, err instanceof Error ? err.message : err);
      console.log("---");
    }
  }

  const final = stateMap.get(sender);
  console.log(
    `[mock] session done. final: ${final ? `leaks=${final.leaks.length} history_turns=${final.history.length} round=${final.roundCount}` : "no state (was reset)"}`,
  );
}

main().catch((err) => {
  console.error("[mock] fatal:", err);
  process.exit(1);
});

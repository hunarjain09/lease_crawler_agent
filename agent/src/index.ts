import { Spectrum } from "spectrum-ts";
import { terminal } from "spectrum-ts/providers/terminal";
import { imessage } from "spectrum-ts/providers/imessage";

import { classify } from "./classifier.js";
import {
  addLeaks,
  appendTurn,
  emptyState,
  MAX_ROUNDS_PER_SESSION,
  type SessionState,
} from "./state.js";
import { analyze, ask, crawl } from "./tools.js";

const projectId = process.env.SPECTRUM_PROJECT_ID;
const projectSecret = process.env.SPECTRUM_PROJECT_SECRET;
const useIMessage = Boolean(projectId && projectSecret);

const app = useIMessage
  ? await Spectrum({
      projectId: projectId!,
      projectSecret: projectSecret!,
      providers: [imessage.config()],
    })
  : await Spectrum({
      providers: [terminal.config()],
    });

console.log(
  useIMessage
    ? `[agent] iMessage provider ready (cloud mode). Text your Photon number to talk to me.`
    : `[agent] Terminal provider ready. Type below.`,
);

const stateByUser = new Map<string, SessionState>();
function getState(userId: string): SessionState {
  let s = stateByUser.get(userId);
  if (!s) {
    s = emptyState();
    stateByUser.set(userId, s);
  }
  return s;
}

for await (const [space, message] of app.messages) {
  console.log(
    `[agent] inbound platform=${message.platform} sender=${message.sender.id} type=${message.content.type}`,
  );
  let text: string;
  if (message.content.type === "text") {
    text = message.content.text;
  } else if (message.content.type === "richlink") {
    // iMessage delivers bare URLs as richlinks. Treat the url as the message text.
    text = message.content.url;
  } else {
    continue;
  }
  const userId = message.sender.id;
  console.log(`[agent] text: ${text.slice(0, 200)}`);
  const intent = classify(text);
  console.log(`[agent] intent: ${intent.kind}`);

  // A new URL starts a fresh session for this user (different listing = different convo).
  if (intent.kind === "url") {
    if (stateByUser.has(userId)) {
      console.log(`[agent] session.reset reason=new_url sender=${userId}`);
    }
    stateByUser.set(userId, emptyState());
  }
  const state = getState(userId);

  await space.responding(async () => {
    try {
      let reply: string;

      if (intent.kind === "url") {
        const { content } = await crawl(intent.url);
        const result = await analyze(content, state.leaks);
        state.leaks = addLeaks(state.leaks, result.leaks);
        state.summary = result.summary;
        state.lastUrl = intent.url;

        // Ask GMI to propose 3 follow-up questions a renter would care about.
        // One extra /ask call; cheap and seeds the conversation.
        const suggestQ =
          "Based on the listing data, suggest exactly 3 short questions a renter would want answered next. Reply with ONLY the 3 questions, one per line, no numbering or bullets or preamble.";
        const { answer: rawSuggestions } = await ask(
          suggestQ,
          result.leaks,
          result.summary,
          [],
        );
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
            : `Walkthrough video isn't wired yet (F1). I'm tracking ${state.leaks.length} leaks across this conversation.`;
      } else {
        if (state.leaks.length === 0 && !state.summary) {
          reply = "Send me a listing URL to get started, then ask me anything about it.";
        } else {
          const { answer } = await ask(text, state.leaks, state.summary, state.history);
          state.history = appendTurn(state.history, { role: "user", content: text });
          state.history = appendTurn(state.history, { role: "assistant", content: answer });
          // Show the round counter so the user knows where they are in the 10-cap.
          reply = `${answer}\n\n(round ${state.roundCount + 1}/10)`;
        }
      }

      // Increment after a successful handle. We count BOTH URL messages and
      // follow-up questions toward the cap (URL = round 1, then 9 more).
      state.roundCount += 1;
      console.log(
        `[agent] reply -> ${userId} round=${state.roundCount}/${MAX_ROUNDS_PER_SESSION}: ${reply.replace(/\n/g, " ").slice(0, 200)}`,
      );
      await message.reply(reply);
      console.log(`[agent] reply.sent sender=${userId} chars=${reply.length} round=${state.roundCount}`);

      // Silent reset: at the cap, drop this user's state so the next message
      // starts a fresh session. No extra reply sent.
      if (state.roundCount >= MAX_ROUNDS_PER_SESSION) {
        stateByUser.delete(userId);
        console.log(
          `[agent] session.reset reason=cap_reached sender=${userId} cap=${MAX_ROUNDS_PER_SESSION}`,
        );
      }
    } catch (err) {
      console.error("[agent] error:", err);
      const fallback = `Sorry, something broke. ${err instanceof Error ? err.message : String(err)}`;
      console.log(`[agent] reply.error -> ${userId}: ${fallback.slice(0, 200)}`);
      await message.reply(fallback);
    }
  });
}

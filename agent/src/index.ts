import { Spectrum } from "spectrum-ts";
import { terminal } from "spectrum-ts/providers/terminal";
import { imessage } from "spectrum-ts/providers/imessage";

import { classify } from "./classifier.js";
import { addLeaks, appendTurn, emptyState, type SessionState } from "./state.js";
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
  const state = getState(userId);
  console.log(`[agent] text: ${text.slice(0, 200)}`);
  const intent = classify(text);
  console.log(`[agent] intent: ${intent.kind}`);

  await space.responding(async () => {
    try {
      let reply: string;

      if (intent.kind === "url") {
        const { content } = await crawl(intent.url);
        const result = await analyze(content, state.leaks);
        state.leaks = addLeaks(state.leaks, result.leaks);
        state.summary = result.summary;
        state.lastUrl = intent.url;
        reply = `${result.summary}\n\n(${result.leaks.length} new, ${state.leaks.length} total)`;
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
          reply = answer;
        }
      }

      await message.reply(reply);
    } catch (err) {
      console.error("[agent] error:", err);
      await message.reply(
        `Sorry, something broke. ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  });
}

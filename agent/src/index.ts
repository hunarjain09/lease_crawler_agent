import { Spectrum } from "spectrum-ts";
import { terminal } from "spectrum-ts/providers/terminal";
import { imessage } from "spectrum-ts/providers/imessage";

import { classify } from "./classifier.js";
import { addLeaks, type Leak } from "./state.js";
import { analyze, crawl } from "./tools.js";

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

const stateByUser = new Map<string, { leaks: Leak[] }>();

for await (const [space, message] of app.messages) {
  if (message.content.type !== "text") continue;
  const userId = message.sender.id;
  const state = stateByUser.get(userId) ?? { leaks: [] };
  const intent = classify(message.content.text);

  await space.responding(async () => {
    try {
      if (intent.kind === "url") {
        const { content } = await crawl(intent.url);
        const { leaks, summary } = await analyze(content, state.leaks);
        state.leaks = addLeaks(state.leaks, leaks);
        const totals = `\n\n(${leaks.length} new, ${state.leaks.length} total)`;
        await message.reply(summary + totals);
      } else if (intent.kind === "walkthrough") {
        await message.reply(
          state.leaks.length === 0
            ? "No listings discussed yet. Send me a URL first."
            : `Walkthrough video isn't wired yet — that's the F1 follow-up. ${state.leaks.length} leaks tracked across this conversation.`,
        );
      } else {
        await message.reply("Send me a listing URL or ask for a walkthrough.");
      }
    } catch (err) {
      console.error("[agent] error:", err);
      await message.reply(
        `Sorry, something broke. ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  });

  stateByUser.set(userId, state);
}

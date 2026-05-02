import { Spectrum } from "spectrum-ts";
import { terminal } from "spectrum-ts/providers/terminal";
import { imessage } from "spectrum-ts/providers/imessage";

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

for await (const [, message] of app.messages) {
  switch (message.content.type) {
    case "text":
      await message.reply(`echo: ${message.content.text}`);
      break;
    case "attachment":
      await message.reply(
        `got attachment: ${message.content.name} (${message.content.mimeType})`,
      );
      break;
    default:
      // "custom" or unknown — skip silently
      break;
  }
}

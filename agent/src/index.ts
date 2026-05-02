import { Spectrum } from "spectrum-ts";
import { terminal } from "spectrum-ts/providers/terminal";

const app = await Spectrum({
  providers: [terminal.config()],
});

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

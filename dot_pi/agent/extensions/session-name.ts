/**
 * Session Name Extension
 *
 * Auto-names a session from its first user prompt, so the session selector
 * (/resume) shows something meaningful instead of raw message text. Manual
 * override stays available via /session-name.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

function deriveName(prompt: string): string | undefined {
	const firstLine = prompt
		.split("\n")
		.map((line) => line.trim())
		.find((line) => line.length > 0);
	if (!firstLine) return undefined;

	const cleaned = firstLine.replace(/\s+/g, " ").trim();
	if (!cleaned) return undefined;
	return cleaned.length > 60 ? `${cleaned.slice(0, 57)}...` : cleaned;
}

export default function (pi: ExtensionAPI) {
	pi.on("before_agent_start", async (event) => {
		if (pi.getSessionName()) return;
		const name = deriveName(event.prompt);
		if (name) pi.setSessionName(name);
	});

	pi.registerCommand("session-name", {
		description: "Set or show the session name (usage: /session-name [new name])",
		handler: async (args, ctx) => {
			const name = args.trim();
			if (name) {
				pi.setSessionName(name);
				ctx.ui.notify(`Session named: ${name}`, "info");
			} else {
				const current = pi.getSessionName();
				ctx.ui.notify(current ? `Session: ${current}` : "No session name set", "info");
			}
		},
	});
}

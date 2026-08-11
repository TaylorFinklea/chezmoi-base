# TmuxAI

This repo manages `~/.config/tmuxai/config.yaml`.

Configured models:

- `codex` — OpenAI Responses API using `${OPENAI_API_KEY}` with model `gpt-5.4`
- `copilot` — GitHub Copilot provider using the authenticated `copilot` CLI session with model `claude-sonnet-4.6`

Notes:

- TmuxAI's upstream provider set supports `github-copilot` directly, but not a dedicated Codex CLI subprocess provider. The `codex` profile here uses the OpenAI provider with a Codex model name instead.
- The Copilot profile intentionally omits `api_key`; tmuxai's upstream example documents that GitHub Copilot auth can come from the `copilot` CLI login state.
- From inside TmuxAI, use `/model` to list profiles and `/model codex` or `/model copilot` to switch.
- The tmux config in this repo adds popup launchers for both profiles from the current pane directory.

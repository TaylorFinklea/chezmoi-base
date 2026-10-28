# Vector H: Dangerous Sandbox Configurations

AI action sandbox or safety configurations are set to values that disable protections entirely, giving the AI agent unrestricted shell access, filesystem access, or approval-free execution. These are configuration-level weaknesses that amplify the impact of any prompt injection vector -- turning "attacker can influence AI text output" into "attacker achieves RCE on the CI runner."

## Applicable Actions

| Action | Applicable | Notes |
|--------|-----------|-------|
| OpenAI Codex | Yes | `sandbox: danger-full-access` and `safety-strategy: unsafe` disable protections |
| GitHub AI Inference | No | Inference-only API with no sandbox/tool configuration -- no shell access to restrict |

## Trigger Events

Any event -- this vector is about the action's configuration, not the trigger. The trigger determines whether attacker input reaches the AI; this vector determines the blast radius if prompt injection succeeds.

## Data Flow

No direct data flow -- this is a configuration weakness. The danger:

```
ANY prompt injection vector (A-F) succeeds
  + sandbox/safety protections disabled (this vector)
  = unrestricted code execution on the runner
```

Without dangerous configs, a successful prompt injection may still be contained by tool restrictions and sandbox boundaries. With dangerous configs, the AI agent has full access to shell, filesystem, environment variables, and network.

## What to Look For
**OpenAI Codex (`openai/codex-action`):**

- `with.sandbox: danger-full-access` -- disables all filesystem restrictions, the AI can read/write anywhere on the runner
- `with.safety-strategy: unsafe` -- disables safety enforcement for all operations
- Both together represent maximum exposure: unrestricted filesystem + no safety checks

## Where to Look

The `with:` block of AI action steps:

- **Codex:** Check `with.sandbox` and `with.safety-strategy` field values directly

## Why It Matters

Dangerous sandbox configs turn prompt injection from a text-influence attack into full remote code execution. Without sandbox restrictions, the AI agent can:

- Execute arbitrary shell commands on the runner
- Read/write all files on the runner filesystem
- Access environment variables including `GITHUB_TOKEN` and repository secrets
- Make outbound network requests (data exfiltration)
- Modify repository contents, create releases, or push code

## False Positives

- **Codex workspace-scoped sandbox:** `sandbox: workspace-write` allows writes but within a workspace boundary, not full system access

See [foundations.md](foundations.md) for AI action field mappings.

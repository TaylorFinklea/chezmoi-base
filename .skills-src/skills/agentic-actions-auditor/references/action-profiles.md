# Action Security Profiles

Security-relevant configuration fields, default behaviors, dangerous configuration patterns, and remediation guidance for each supported AI action. Referenced by SKILL.md Step 5 for action-specific remediation.

## OpenAI Codex

### Default Security Posture

- Sandbox defaults to `workspace-write` (read/edit in workspace, run commands locally, no network)
- Safety strategy defaults to `drop-sudo` (removes sudo privileges before running Codex)
- Empty `allow-users` permits only write-access repository members (default)
- `allow-bots: false` by default
- Network off by default (must be explicitly enabled)
- Protected paths: `.git`, `.agents/`, `.codex/` directories are read-only even in writable sandbox

### Dangerous Configurations

| Configuration | Risk |
|--------------|------|
| `sandbox: danger-full-access` | No sandbox, no approvals, unrestricted filesystem and network access |
| `safety-strategy: unsafe` | Disables all safety enforcement including sudo restrictions |
| `allow-users: "*"` | Any GitHub user can trigger the action |
| `allow-bots: true` | Any bot can trigger, enables automated attack chains |
| `danger-full-access` + `unsafe` combined | Maximum exposure: no sandbox, no safety, full system access |

### Remediation Patterns

**Restrict sandbox:** Use the default or a more restrictive mode:

```yaml
sandbox: workspace-write    # default: workspace access only, no network
sandbox: read-only          # for analysis-only tasks
```

**Restrict safety strategy:** Use the default or a stricter option:

```yaml
safety-strategy: drop-sudo          # default: removes sudo privileges
safety-strategy: unprivileged-user  # stronger: runs as unprivileged user
```

**Restrict user access:** Remove wildcard or replace with explicit user list:

```yaml
allow-users: "maintainer1,maintainer2"
```

**Restrict bot access:** Keep `allow-bots: false` (default) unless specific trusted bots need access.

**Organization-level enforcement:** Use `requirements.toml` to block `danger-full-access` at the organization level, preventing individual repos from weakening sandbox policy.

## GitHub AI Inference

### Default Security Posture

- Inference-only API call -- no shell access, no filesystem access, no sandbox to configure
- Access controlled by GitHub token scope
- Primary risks: prompt injection via untrusted event data (Vector B), and AI output flowing to `eval` in subsequent workflow steps (Vector G)

### Dangerous Configurations

| Configuration | Risk |
|--------------|------|
| `prompt` containing `${{ github.event.* }}` | Attacker-controlled event contexts injected directly into AI prompt (Vector B) |
| Overly scoped `token` parameter | Grants more permissions than needed, expanding blast radius of any exploitation |
| AI output consumed by `eval`/`exec` in subsequent steps | Converts inference-only action into code execution vector (Vector G) |

### Remediation Patterns

**Sanitize prompt inputs:** Validate and sanitize event data before including in prompts. Do not pass raw `${{ github.event.issue.body }}` or similar attacker-controlled fields.

**Minimize token scope:** Use minimum-scope tokens following the principle of least privilege. Only grant permissions the inference call actually needs.

**Protect AI output consumption:** Never pass AI output through `eval`, `exec`, or unquoted `$()` in subsequent workflow steps:

```yaml
# DANGEROUS: AI output executed as code
- run: eval "${{ steps.inference.outputs.result }}"

# SAFE: AI output stored and validated before use
- run: |
    RESULT='${{ steps.inference.outputs.result }}'
    echo "$RESULT"  # display only, no execution
```

**Validate structured output:** If structured output (JSON) is needed from the AI, validate against a schema before using in shell commands.

## Per-Action Remediation Quick Reference

| Remediation Need | OpenAI Codex | GitHub AI Inference |
|-----------------|--------------|---------------------|
| Restrict shell access | `sandbox: workspace-write` | N/A (no shell) |
| Restrict user access | `allow-users: "user1,user2"` | Control via token scope |
| Disable dangerous mode | Remove `danger-full-access` from `sandbox` | N/A |
| Sandbox enforcement | `sandbox: read-only` | N/A (no execution) |
| Block bot triggers | Set `allow-bots: false` | Control via token scope |
| Protect output/logs | N/A | Never `eval` AI output |

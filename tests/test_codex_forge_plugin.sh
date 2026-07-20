#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git -C "$(dirname "${BASH_SOURCE[0]}")/.." rev-parse --show-toplevel)"
chezmoi_executable="$(command -v chezmoi)"
codex_executable="$(command -v codex)"
fixture="$(mktemp -d)"
trap 'rm -rf "$fixture"' EXIT

[[ -x "$chezmoi_executable" && -x "$codex_executable" ]]

home="$fixture/home"
codex_home="$home/.codex"
marketplace_root="$home/.local/share/codex-forge-marketplace"
at_sign="$(printf '\x40')"
unrelated_plugin_selector="plugins.unrelated${at_sign}other"
managed_plugin_selector="codex-forge${at_sign}local-managed"
mkdir -p "$home" "$codex_home" "$fixture/rendered" "$fixture/unrelated-marketplace/.agents/plugins"
cat > "$fixture/unrelated-marketplace/.agents/plugins/marketplace.json" <<'EOF'
{
  "name": "unrelated",
  "plugins": []
}
EOF

cat > "$codex_home/config.toml" <<EOF
# unrelated Codex configuration
[marketplaces.unrelated]
source_type = "local"
source = "$fixture/unrelated-marketplace"

["$unrelated_plugin_selector"]
enabled = false
EOF
cp "$codex_home/config.toml" "$fixture/unrelated-before.toml"

rendered_script="$fixture/rendered/install-codex-forge.sh"
"$chezmoi_executable" execute-template \
  --source "$repo_root" \
  --destination "$home" \
  --file "$repo_root/.chezmoiscripts/run_onchange_after_install-codex-forge.sh.tmpl" \
  > "$rendered_script"
chmod +x "$rendered_script"

mkdir -p "$marketplace_root/.agents/plugins" "$marketplace_root/plugins"
cp -R "$repo_root/dot_local/share/codex-forge-marketplace/dot_agents/plugins/marketplace.json" \
  "$marketplace_root/.agents/plugins/marketplace.json"
cp -R "$repo_root/dot_local/share/codex-forge-marketplace/plugins/codex-forge" \
  "$marketplace_root/plugins/codex-forge"
mv "$marketplace_root/plugins/codex-forge/dot_codex-plugin" "$marketplace_root/plugins/codex-forge/.codex-plugin"

run_installer() {
  HOME="$home" CODEX_HOME="$codex_home" "$rendered_script" > "$fixture/installer.log"
}

run_installer

HOME="$home" CODEX_HOME="$codex_home" "$codex_executable" plugin marketplace list --json > "$fixture/marketplaces.json"
HOME="$home" CODEX_HOME="$codex_home" "$codex_executable" plugin list --marketplace local-managed --json > "$fixture/plugins-first.json"

python3 - "$fixture/marketplaces.json" "$fixture/plugins-first.json" "$codex_home/config.toml" "$fixture/unrelated-before.toml" "$repo_root/dot_local/share/codex-forge-marketplace/plugins/codex-forge/dot_codex-plugin/plugin.json" "$rendered_script" "$unrelated_plugin_selector" "$managed_plugin_selector" <<'PY'
import json
import re
import sys
from pathlib import Path

marketplaces = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
plugins = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
config = Path(sys.argv[3]).read_text(encoding="utf-8")
unrelated_before = Path(sys.argv[4]).read_text(encoding="utf-8")
source_manifest = json.loads(Path(sys.argv[5]).read_text(encoding="utf-8"))
installer = Path(sys.argv[6]).read_text(encoding="utf-8")
unrelated_selector = sys.argv[7]
managed_selector = sys.argv[8]
expected_version = "0.1.0"
installer_version = re.search(r"codex-forge version\s+([0-9]+\.[0-9]+\.[0-9]+)", installer)
if installer_version is None:
    raise SystemExit("rendered installer does not embed plugin version")
if source_manifest.get("version") != expected_version or installer_version.group(1) != expected_version:
    raise SystemExit(f"manifest/installer version mismatch: {source_manifest.get('version')!r} / {installer_version.group(1)!r}")

def named_values(value, name):
    if isinstance(value, dict):
        result = [value] if value.get("name") == name else []
        for child in value.values():
            result.extend(named_values(child, name))
        return result
    if isinstance(value, list):
        result = []
        for child in value:
            result.extend(named_values(child, name))
        return result
    return []

marketplace_names = marketplaces if isinstance(marketplaces, list) else named_values(marketplaces, "local-managed")
if (marketplace_names.count("local-managed") if isinstance(marketplace_names, list) and all(isinstance(item, str) for item in marketplace_names) else len(named_values(marketplaces, "local-managed"))) != 1:
    raise SystemExit(f"local-managed marketplace is not registered exactly once: {marketplaces!r}")
installed = [item for item in plugins.get("installed", []) if item.get("name") == "codex-forge"]
if len(installed) != 1:
    raise SystemExit(f"codex-forge is not installed exactly once: {plugins!r}")
plugin = installed[0]
if plugin.get("version") != expected_version or not plugin.get("enabled"):
    raise SystemExit(f"unexpected plugin install: {plugin!r}")

header = re.compile(r"(?m)^\[[^\n]+\]\n")
def table(text, name):
    match = re.search(rf"(?ms)^\[{re.escape(name)}\]\n.*?(?=^\[|\Z)", text)
    if match is None:
        raise SystemExit(f"missing config table {name}")
    return match.group(0).strip("\n") + "\n"

for name in ("marketplaces.unrelated", f'"{unrelated_selector}"'):
    before = table(unrelated_before, name)
    after = table(config, name)
    if before != after:
        raise SystemExit(f"unrelated config table changed: {name!r}: {before!r} != {after!r}")
if config.count("[marketplaces.local-managed]") != 1:
    raise SystemExit("marketplace registration was duplicated")
if config.count(f'[plugins."{managed_selector}"]') != 1:
    raise SystemExit("plugin enablement was duplicated")

cache_manifest = Path(sys.argv[3]).parent / f"plugins/cache/local-managed/codex-forge/{expected_version}/.codex-plugin/plugin.json"
manifest = json.loads(cache_manifest.read_text(encoding="utf-8"))
if manifest.get("version") != expected_version:
    raise SystemExit(f"cached manifest has wrong version: {manifest!r}")
if manifest.get("skills") != "./skills/" or manifest.get("hooks") != "./hooks/hooks.json":
    raise SystemExit(f"cached manifest does not resolve Forge bundle: {manifest!r}")
if not (cache_manifest.parent.parent / "skills/forge/SKILL.md").is_file():
    raise SystemExit("cached Forge skill is missing")
if not (cache_manifest.parent.parent / "hooks/hooks.json").is_file():
    raise SystemExit("cached Forge hooks are missing")
PY

run_installer
HOME="$home" CODEX_HOME="$codex_home" "$codex_executable" plugin list --marketplace local-managed --json > "$fixture/plugins-second.json"
cmp "$fixture/plugins-first.json" "$fixture/plugins-second.json"

echo "Codex Forge plugin installer fixture passed"

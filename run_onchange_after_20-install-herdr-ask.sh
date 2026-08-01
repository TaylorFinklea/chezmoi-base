#!/bin/sh
set -eu

version=0.1.0
formula=taylorfinklea/tap/herdr-ask
plugin_id=dev.herdr-ask
plugin_repo=TaylorFinklea/herdr-ask

if ! command -v brew >/dev/null 2>&1; then
  printf 'install-herdr-ask: Homebrew is required; install it first\n' >&2
  exit 1
fi

if ! command -v herdr >/dev/null 2>&1; then
  printf 'install-herdr-ask: Herdr is required; install it first\n' >&2
  exit 1
fi

installed_formula_version=$(brew list --versions herdr-ask 2>/dev/null | awk 'NR == 1 { print $NF }')
if [ -z "$installed_formula_version" ]; then
  brew install "$formula"
elif [ "$installed_formula_version" != "$version" ]; then
  brew upgrade "$formula"
fi

plugin_json=$(herdr plugin list --plugin "$plugin_id" --json)
if ! printf '%s\n' "$plugin_json" | grep -Fq "\"plugin_id\":\"$plugin_id\"" ||
  ! printf '%s\n' "$plugin_json" | grep -Fq "\"version\":\"$version\""; then
  herdr plugin install "$plugin_repo" --ref "v$version" --yes
fi

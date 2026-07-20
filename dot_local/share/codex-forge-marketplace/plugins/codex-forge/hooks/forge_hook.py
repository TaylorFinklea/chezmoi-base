#!/usr/bin/env python3
"""Thin stdin/stdout entrypoint for the Codex Forge lifecycle hooks."""

import json
from pathlib import Path
import sys

LIB = Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(LIB))

from codex_forge.hooks import HookError, handle_hook  # noqa: E402


def main() -> int:
    raw = sys.stdin.read()
    decoder = json.JSONDecoder()
    try:
        event, end = decoder.raw_decode(raw)
        if raw[end:].strip() or not isinstance(event, dict):
            raise ValueError("stdin must contain exactly one JSON object")
        result = handle_hook(event)
        sys.stdout.write(json.dumps(result.as_dict(), sort_keys=True, separators=(",", ":")) + "\n")
        return 2 if result.blocked else 0
    except (ValueError, TypeError, HookError, json.JSONDecodeError) as exc:
        sys.stdout.write(json.dumps({"decision": "block", "reason": str(exc)}, separators=(",", ":")) + "\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

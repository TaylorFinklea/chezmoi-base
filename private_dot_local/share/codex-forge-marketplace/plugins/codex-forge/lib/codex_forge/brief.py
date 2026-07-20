"""Validation and canonical representation of a Codex Forge execution brief."""

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Any, Mapping


@dataclass(frozen=True)
class DecisionEnvelope:
    autonomous: tuple[str, ...]
    escalate: tuple[str, ...]


@dataclass(frozen=True)
class Phase:
    name: str
    tier_floor: str
    verify: str


@dataclass(frozen=True)
class Brief:
    version: int
    goal: str
    scope: tuple[str, ...]
    non_goals: tuple[str, ...]
    decisions: tuple[str, ...]
    acceptance: tuple[str, ...]
    patterns: tuple[str, ...]
    verification: tuple[str, ...]
    assumptions: tuple[str, ...]
    decision_envelope: DecisionEnvelope
    phases: tuple[Phase, ...]
    dispatcher: str


_KEYS = frozenset({
    "version", "goal", "scope", "non_goals", "decisions", "acceptance",
    "patterns", "verification", "assumptions", "decision_envelope", "phases",
    "dispatcher",
})
_ENVELOPE_KEYS = frozenset({"autonomous", "escalate"})
_PHASE_KEYS = frozenset({"name", "tier_floor", "verify"})
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _string(value: Any, field: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value) or _CONTROL.search(value):
        raise ValueError(f"{field} must be a non-empty string without control characters")
    return value


def _strings(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    return tuple(_string(item, f"{field}[]") for item in value)


def parse_brief(raw: Mapping[str, Any]) -> Brief:
    if not isinstance(raw, Mapping):
        raise ValueError("brief must be an object")
    if set(raw) != _KEYS:
        raise ValueError("brief has missing or unknown keys")
    if type(raw["version"]) is not int or raw["version"] != 1:
        raise ValueError("unsupported brief version")
    envelope = raw["decision_envelope"]
    if not isinstance(envelope, Mapping) or set(envelope) != _ENVELOPE_KEYS:
        raise ValueError("decision_envelope has missing or unknown keys")
    phases_raw = raw["phases"]
    if not isinstance(phases_raw, list):
        raise ValueError("phases must be a list")
    phases = []
    for index, phase in enumerate(phases_raw):
        if not isinstance(phase, Mapping) or set(phase) != _PHASE_KEYS:
            raise ValueError(f"phases[{index}] has missing or unknown keys")
        tier = phase["tier_floor"]
        if tier not in ("senior", "junior"):
            raise ValueError("phase tier_floor must be senior or junior")
        phases.append(Phase(_string(phase["name"], f"phases[{index}].name"), tier,
                            _string(phase["verify"], f"phases[{index}].verify")))
    dispatcher = raw["dispatcher"]
    if dispatcher not in ("direct", "ralph"):
        raise ValueError("invalid dispatcher")
    return Brief(
        version=1,
        goal=_string(raw["goal"], "goal"),
        scope=_strings(raw["scope"], "scope"),
        non_goals=_strings(raw["non_goals"], "non_goals"),
        decisions=_strings(raw["decisions"], "decisions"),
        acceptance=_strings(raw["acceptance"], "acceptance"),
        patterns=_strings(raw["patterns"], "patterns"),
        verification=_strings(raw["verification"], "verification"),
        assumptions=_strings(raw["assumptions"], "assumptions"),
        decision_envelope=DecisionEnvelope(
            _strings(envelope["autonomous"], "decision_envelope.autonomous"),
            _strings(envelope["escalate"], "decision_envelope.escalate"),
        ),
        phases=tuple(phases),
        dispatcher=dispatcher,
    )


def _brief_dict(brief: Brief) -> dict[str, Any]:
    if not isinstance(brief, Brief):
        raise TypeError("expected Brief")
    return asdict(brief)


def canonical_brief_bytes(brief: Brief) -> bytes:
    return json.dumps(_brief_dict(brief), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def brief_digest(brief: Brief) -> str:
    return hashlib.sha256(canonical_brief_bytes(brief)).hexdigest()

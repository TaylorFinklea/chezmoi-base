import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "lib"))

from codex_forge.brief import brief_digest, canonical_brief_bytes, parse_brief


VALID = {
    "version": 1,
    "goal": "Ship the feature",
    "scope": ["src"],
    "non_goals": ["docs"],
    "decisions": ["Use stdlib"],
    "acceptance": ["Tests pass"],
    "patterns": ["Mirror existing parser"],
    "verification": ["python3 -m unittest discover -s tests -p 'test_*.py'"],
    "assumptions": ["Working tree is available"],
    "decision_envelope": {"autonomous": ["formatting"], "escalate": ["security"]},
    "phases": [{"name": "Implement", "tier_floor": "senior", "verify": "python3 -m unittest"}],
    "dispatcher": "direct",
}


class BriefTests(unittest.TestCase):
    def test_parses_contract_into_frozen_domain_objects(self):
        brief = parse_brief(VALID)
        self.assertEqual(brief.version, 1)
        self.assertEqual(brief.scope, ("src",))
        self.assertEqual(brief.decision_envelope.autonomous, ("formatting",))
        self.assertEqual(brief.phases[0].tier_floor, "senior")
        with self.assertRaises(AttributeError):
            brief.goal = "changed"

    def test_rejects_missing_wrong_type_and_unknown_keys(self):
        for key in ("goal", "scope", "verification", "decision_envelope", "phases"):
            value = dict(VALID)
            del value[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                parse_brief(value)
        value = dict(VALID)
        value["unknown"] = True
        with self.assertRaises(ValueError):
            parse_brief(value)
        value = dict(VALID)
        value["version"] = 2
        with self.assertRaises(ValueError):
            parse_brief(value)

    def test_rejects_newlines_and_control_characters_in_structural_strings(self):
        for field in ("goal", "scope", "verification", "assumptions"):
            value = dict(VALID)
            value[field] = ["bad\nvalue"] if isinstance(VALID[field], list) else "bad\x00value"
            with self.subTest(field=field), self.assertRaises(ValueError):
                parse_brief(value)
        value = dict(VALID)
        value["phases"] = [{"name": "bad\nname", "tier_floor": "senior", "verify": "ok"}]
        with self.assertRaises(ValueError):
            parse_brief(value)

    def test_validates_phase_and_dispatcher_values(self):
        for tier in ("lead", "", "Senior"):
            value = dict(VALID)
            value["phases"] = [{"name": "x", "tier_floor": tier, "verify": "ok"}]
            with self.subTest(tier=tier), self.assertRaises(ValueError):
                parse_brief(value)
        value = dict(VALID)
        value["dispatcher"] = "shell"
        with self.assertRaises(ValueError):
            parse_brief(value)
        value = dict(VALID)
        value["phases"] = [{"name": "x", "tier_floor": "junior", "verify": ""}]
        with self.assertRaises(ValueError):
            parse_brief(value)

    def test_canonical_bytes_and_digest_are_deterministic(self):
        first = parse_brief(VALID)
        reordered = {key: VALID[key] for key in reversed(list(VALID))}
        second = parse_brief(reordered)
        expected = json.dumps(VALID, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        self.assertEqual(canonical_brief_bytes(first), expected)
        self.assertEqual(canonical_brief_bytes(first), canonical_brief_bytes(second))
        self.assertEqual(brief_digest(first), brief_digest(second))
        self.assertEqual(len(brief_digest(first)), 64)


if __name__ == "__main__":
    unittest.main()

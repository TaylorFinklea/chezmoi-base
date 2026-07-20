import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "lib"))

from codex_forge.state import ForgeState
from codex_forge.verification import (
    PREVIEW_BYTES, VerificationError, missing_verification_commands,
    record_verification, verification_complete,
)


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = Path(self.tmp.name).resolve()
        self.state = ForgeState("session", self.cwd, None, "executing", 1, "0.1.0",
                                "brief-digest", ("python3 -m unittest", "git diff --check"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_records_exact_passing_evidence_and_digest(self):
        response = {"exit_code": 0, "output": "ok"}
        updated = record_verification(self.state, "python3 -m unittest", response)
        self.assertEqual(self.state.verification_records, ())
        evidence = updated.verification_records[0]
        self.assertEqual(evidence["session_id"], "session")
        self.assertEqual(evidence["cwd"], str(self.cwd))
        self.assertEqual(evidence["brief_digest"], "brief-digest")
        self.assertEqual(evidence["response_sha256"], hashlib.sha256(b'{"exit_code":0,"output":"ok"}').hexdigest())
        self.assertEqual(evidence["head"], "ok")
        self.assertEqual(evidence["tail"], "ok")
        self.assertTrue(isinstance(evidence["timestamp"], float))

    def test_rejects_lookalikes_stale_binding_and_missing_exit(self):
        for command in ("python3 -m unittest ", "python3 -m unittest; echo bad", "git diff"):
            with self.subTest(command=command), self.assertRaises(VerificationError):
                record_verification(self.state, command, {"exit_code": 0, "output": ""})
        stale = ForgeState("other", self.cwd, None, "executing", 1, "0.1.0",
                           "brief-digest", self.state.verification_commands)
        with self.assertRaises(VerificationError):
            record_verification(stale, "python3 -m unittest", {})
        with self.assertRaises(VerificationError):
            record_verification(self.state, "python3 -m unittest", {"output": "missing"})

    def test_failed_attempt_is_retained_but_does_not_complete_until_later_pass(self):
        failed = record_verification(self.state, "python3 -m unittest", {"exit_code": 1, "output": "failed"})
        self.assertFalse(verification_complete(failed))
        self.assertEqual(missing_verification_commands(failed), ("python3 -m unittest", "git diff --check"))
        passed = record_verification(failed, "python3 -m unittest", {"exit_code": 0, "output": "passed"})
        complete = record_verification(passed, "git diff --check", {"exit_code": 0, "output": "passed"})
        self.assertEqual(len(complete.verification_records), 3)
        self.assertTrue(verification_complete(complete))

    def test_previews_are_bounded_at_utf8_boundaries_and_preserve_digest(self):
        cases = (
            "x" * PREVIEW_BYTES,
            "x" * (PREVIEW_BYTES - 3) + "😀" + "tail",
            "x" * (PREVIEW_BYTES - 1) + "€" + "tail",
            "replacement � content " * 500,
            "😀" * 25_000,
        )
        for output in cases:
            with self.subTest(output=output[:20]):
                response = {"exit_code": 0, "output": output}
                updated = record_verification(self.state, "python3 -m unittest", response)
                evidence = updated.verification_records[0]
                self.assertLessEqual(len(evidence["head"].encode("utf-8")), PREVIEW_BYTES)
                self.assertLessEqual(len(evidence["tail"].encode("utf-8")), PREVIEW_BYTES)
                self.assertEqual(
                    evidence["head"], evidence["head"].encode("utf-8").decode("utf-8")
                )
                self.assertEqual(
                    evidence["tail"], evidence["tail"].encode("utf-8").decode("utf-8")
                )
                expected = hashlib.sha256(
                    ('{"exit_code":0,"output":' + json.dumps(output, ensure_ascii=False, separators=(",", ":")) + '}').encode("utf-8")
                ).hexdigest()
                self.assertEqual(evidence["response_sha256"], expected)


if __name__ == "__main__":
    unittest.main()

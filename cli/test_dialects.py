#!/usr/bin/env python3
"""Every provider dialect probed with the RIGHT wire shape.

The Oct 23 → Nov 5 gap exposed a real bug: the probe sent a Chat Completions
body to the Codex Responses endpoint, which reports a WORKING model as broken
("Input must be a list", "Stream must be set to true"). A gate that lies is
worse than no gate — it would have you chasing a healthy provider.

Run: python3 cli/test_dialects.py
"""
import json
import unittest
from pathlib import Path

import importlib.machinery
import importlib.util

HERE = Path(__file__).resolve().parent
loader = importlib.machinery.SourceFileLoader("upb_cli", str(HERE / "upb"))
spec = importlib.util.spec_from_loader("upb_cli", loader)
upb = importlib.util.module_from_spec(spec)
loader.exec_module(upb)

sys_path = HERE.parent / "tools"
import sys
sys.path.insert(0, str(sys_path))
entitlement = importlib.import_module("entitlement")


class TestDialects(unittest.TestCase):
    """The three wire dialects must each build the body their endpoint wants."""

    def _capture(self, dialect):
        """Run probe() against a fake urlopen and return the request it built."""
        import urllib.request
        seen = {}

        def spy(req, *a, **kw):
            seen["url"] = req.full_url
            seen["body"] = json.loads(req.data.decode())
            seen["headers"] = dict(req.headers)
            raise urllib.error.HTTPError(req.full_url, 500, "stop", {}, None)

        real = urllib.request.urlopen
        urllib.request.urlopen = spy
        try:
            entitlement.probe("https://x.test/v1", "KEY", "m", dialect)
        except Exception:
            pass
        finally:
            urllib.request.urlopen = real
        return seen

    def test_chat_completions_shape(self):
        seen = self._capture("chat_completions")
        self.assertTrue(seen["url"].endswith("/chat/completions"))
        self.assertEqual(seen["body"]["model"], "m")
        self.assertEqual(seen["body"]["max_tokens"], 1)
        self.assertIn("messages", seen["body"])

    def test_anthropic_messages_shape(self):
        seen = self._capture("anthropic_messages")
        self.assertTrue(seen["url"].endswith("/messages"))
        # urllib title-cases header names on the wire
        hdrs = {k.lower(): v for k, v in seen["headers"].items()}
        self.assertIn("anthropic-version", hdrs)
        self.assertIn("x-api-key", hdrs)
        self.assertIn("max_tokens", seen["body"])

    def test_codex_responses_shape(self):
        """The one that was wrong: list-shaped input + stream:true."""
        seen = self._capture("codex_responses")
        self.assertTrue(seen["url"].endswith("/responses"))
        self.assertIsInstance(seen["body"]["input"], list,
                              "codex_responses needs a LIST-shaped input")
        self.assertTrue(seen["body"]["stream"],
                        "codex_responses rejects a non-streaming request")
        self.assertEqual(seen["body"]["input"][0]["role"], "user")
        self.assertEqual(seen["body"]["input"][0]["content"][0]["type"], "input_text")

    def test_dialects_are_distinct(self):
        shapes = {d: self._capture(d)["body"] for d in
                  ("chat_completions", "anthropic_messages", "codex_responses")}
        self.assertNotEqual(shapes["chat_completions"], shapes["codex_responses"])
        self.assertNotEqual(shapes["anthropic_messages"], shapes["codex_responses"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

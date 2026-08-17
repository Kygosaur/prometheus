import unittest

from planning_agent.local_llm import LocalLLM, _strip_reasoning, validate_loopback_url


class LocalLlmPrivacyTests(unittest.TestCase):
    def test_ipv4_loopback_is_allowed(self):
        self.assertEqual(
            validate_loopback_url("http://127.0.0.1:11434/v1"),
            "http://127.0.0.1:11434/v1",
        )

    def test_ipv6_loopback_is_allowed(self):
        client = LocalLLM("http://[::1]:8000/v1", "kimi")
        self.assertEqual(client.model, "kimi")

    def test_remote_endpoint_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Remote LLM endpoints are disabled"):
            LocalLLM("http://203.0.113.10:8000/v1", "kimi")

    def test_https_endpoint_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "http:// loopback"):
            LocalLLM("https://127.0.0.1:8000/v1", "kimi")

    def test_hostname_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "explicit loopback IP"):
            LocalLLM("http://localhost:11434/v1", "kimi")

    def test_credentials_in_url_are_rejected(self):
        with self.assertRaises(ValueError):
            LocalLLM("http://user:secret@127.0.0.1:11434/v1", "kimi")

    def test_private_reasoning_tags_are_removed(self):
        self.assertEqual(_strip_reasoning("◁think▷private work◁/think▷Final answer"), "Final answer")
        self.assertEqual(_strip_reasoning("<think>private work</think>Final answer"), "Final answer")


if __name__ == "__main__":
    unittest.main()

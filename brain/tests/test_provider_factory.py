import unittest

from brain.planning import LocalOpenAICompatibleProvider, PlanningError
from brain.provider_factory import build_reasoning_provider


class ProviderFactoryTests(unittest.TestCase):
    def test_builds_explicit_local_openai_compatible_provider(self):
        provider = build_reasoning_provider({
            "provider_type": "openai_compatible_local",
            "endpoint": "http://127.0.0.1:8788/v1/chat/completions",
            "model": "qwen-local",
            "timeout_seconds": 9,
        })
        self.assertIsInstance(provider, LocalOpenAICompatibleProvider)
        self.assertEqual(provider.model, "qwen-local")
        self.assertEqual(provider.timeout_seconds, 9.0)

    def test_rejects_non_mapping_config(self):
        with self.assertRaisesRegex(PlanningError, "mapping"):
            build_reasoning_provider(None)

    def test_rejects_unknown_provider_without_fallback(self):
        with self.assertRaisesRegex(PlanningError, "unsupported"):
            build_reasoning_provider({
                "provider_type": "claude",
                "endpoint": "http://127.0.0.1:8788/v1/chat/completions",
                "model": "anything",
            })

    def test_rejects_implicit_or_unknown_config_fields(self):
        with self.assertRaisesRegex(PlanningError, "unknown"):
            build_reasoning_provider({
                "provider_type": "openai_compatible_local",
                "endpoint": "http://127.0.0.1:8788/v1/chat/completions",
                "model": "qwen-local",
                "api_key_env": "SECRET_ENV",
            })

    def test_rejects_remote_endpoint(self):
        with self.assertRaisesRegex(PlanningError, "loopback"):
            build_reasoning_provider({
                "provider_type": "openai_compatible_local",
                "endpoint": "https://api.example.com/v1/chat/completions",
                "model": "remote-model",
            })

    def test_rejects_missing_explicit_endpoint_or_model(self):
        with self.assertRaisesRegex(PlanningError, "explicit"):
            build_reasoning_provider({"provider_type": "openai_compatible_local", "model": "local"})


if __name__ == "__main__":
    unittest.main()

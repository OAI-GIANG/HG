"""WP1: configured provider selection is wired into the MAEP ModelPlanner."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hg.assistant import config as cfg
from hg.brain.planner import ModelPlanner
from hg.brain.providers import ModelProvider, ProviderError


class StubLocal(ModelProvider):
    name = "stub-local"
    model = "stub:1b"
    offline = True
    cost_per_mtok = (0.0, 0.0)

    def complete(self, request):
        return {"text": "{\"steps\":[]}", "provider": self.name, "model": self.model,
                "usage": {"input_tokens": 1, "output_tokens": 1}, "finish_reason": "stop"}


class PlannerConfigTests(unittest.TestCase):
    def test_default_planner_is_local_and_built_by_the_config_factory(self):
        local = StubLocal()
        with mock.patch.object(cfg, "ollama", return_value=local):
            planner = cfg.build_planner(dict(cfg.DEFAULTS))
        self.assertIsInstance(planner, ModelPlanner)
        self.assertEqual(planner._router.available("planning"), ["stub-local"])
        self.assertEqual(planner._max_attempts, 3)

    def test_configured_deepseek_provider_is_selected_without_network_fallback(self):
        config = dict(cfg.DEFAULTS, planner_provider="deepseek")
        planner = cfg.build_planner(config)
        self.assertIsInstance(planner, ModelPlanner)
        self.assertEqual(planner._router.available("planning"), ["deepseek"])
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ProviderError) as ctx:
                planner._router.complete({
                    "system": "test", "messages": [{"role": "user", "content": "test"}],
                    "max_tokens": 10,
                }, kind="planning")
        self.assertEqual(ctx.exception.kind, "UNAVAILABLE")
        self.assertIn("NOT_CONFIGURED", str(ctx.exception))

    def test_remote_provider_endpoint_error_is_mapped_to_config_error(self):
        config = dict(cfg.DEFAULTS, deepseek_base_url="http://api.example.invalid")
        with self.assertRaises(cfg.ConfigError):
            cfg.router(config, provider_choice="deepseek")

    def test_unknown_planner_provider_is_rejected_when_loading_config(self):
        with tempfile.TemporaryDirectory(prefix="hg-planner-config-") as tmp:
            Path(tmp, "config.json").write_text(json.dumps({"planner_provider": "unknown"}), encoding="utf-8")
            with self.assertRaisesRegex(cfg.ConfigError, "planner_provider"):
                cfg.load(tmp)

    def test_explicit_provider_choice_overrides_config_without_changing_it(self):
        config = dict(cfg.DEFAULTS, planner_provider="deepseek")
        local = StubLocal()
        with mock.patch.object(cfg, "ollama", return_value=local):
            planner = cfg.build_planner(config, provider_choice="local", max_attempts=2)
        self.assertEqual(planner._router.available("planning"), ["stub-local"])
        self.assertEqual(planner._max_attempts, 2)
        self.assertEqual(config["planner_provider"], "deepseek")


if __name__ == "__main__":
    unittest.main()

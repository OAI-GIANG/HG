import contextlib
import io
import os
import sys
import types
import unittest
from unittest.mock import patch

from runtime import service


class RuntimeServiceEntrypointTests(unittest.TestCase):
    def test_missing_factory_blocks_without_starting_service(self):
        stderr = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stderr(stderr):
            result = service.main()
        self.assertEqual(result, service.BLOCKED_EXIT)
        self.assertIn("HG_RUNTIME_FACTORY is required", stderr.getvalue())

    def test_factory_spec_requires_module_callable_syntax(self):
        for value in ("", "runtime", ":create", "runtime:", "runtime:build:extra", "bad-name:build"):
            with self.subTest(value=value), self.assertRaises(service.RuntimeStartupError):
                service.load_factory(value)

    def test_factory_must_be_callable(self):
        module = types.ModuleType("hg_test_runtime_config")
        module.not_a_factory = 42
        with patch.dict(sys.modules, {module.__name__: module}):
            with self.assertRaisesRegex(service.RuntimeStartupError, "missing or not callable"):
                service.load_factory("hg_test_runtime_config:not_a_factory")

    def test_factory_import_failure_is_reported_without_provider_details(self):
        with self.assertRaisesRegex(service.RuntimeStartupError, "could not be imported") as caught:
            service.load_factory("hg_missing_runtime_config_20261024:create_service")
        self.assertNotIn("Traceback", str(caught.exception))

    def test_factory_result_must_be_hg_http_server(self):
        module = types.ModuleType("hg_test_runtime_config_wrong_type")
        module.create_service = lambda: object()
        with patch.dict(sys.modules, {module.__name__: module}):
            with patch.dict(os.environ, {service.FACTORY_ENV: module.__name__ + ":create_service"}):
                with self.assertRaisesRegex(service.RuntimeStartupError, "must return runtime.http_server.HGHTTPServer"):
                    service.create_service()

    def test_factory_startup_error_message_is_kept_other_errors_are_redacted(self):
        def blocked():
            raise service.RuntimeStartupError("actionable blocker")

        def leaky():
            raise ValueError("provider detail that must not be printed")

        module = types.ModuleType("hg_test_runtime_config_errors")
        module.blocked, module.leaky = blocked, leaky
        with patch.dict(sys.modules, {module.__name__: module}):
            with self.assertRaisesRegex(service.RuntimeStartupError, "^actionable blocker$"):
                service.create_service(module.__name__ + ":blocked")
            with self.assertRaises(service.RuntimeStartupError) as caught:
                service.create_service(module.__name__ + ":leaky")
        self.assertIn("failed closed (ValueError)", str(caught.exception))
        self.assertNotIn("provider detail", str(caught.exception))


if __name__ == "__main__":
    unittest.main()

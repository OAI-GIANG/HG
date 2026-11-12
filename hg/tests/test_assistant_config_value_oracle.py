"""Oracle: config.json is used only if every value is one HG can act on (WS-04).

The documented contract (hg/assistant/cli.py, docs/HG_V1_GUIDE.md): an unusable config.json is
refused with exit 78 by the CLI and 503 by `hg serve` chat, before the model is contacted. Before
this oracle `config.load` checked only the key names, so a wrong value was accepted and failed
later, differently in each place: a traceback (`model_digest` or `ollama_service_dir` not a
string), a chat answer blamed on a damaged notes ledger (`max_tokens` not an integer), a string
"no" sent to Ollama as `think`, an empty `model_digest` that silently turned the pin off.

Oracle: the value types each consumer needs (OllamaProvider, ModelRouter.make_request, the
listener attestation, the digest pin) and the values `hg model use` / `save()` can write.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from hg.assistant import config as cfg
from hg.chat import ChatService
from hg.http_api import HTTPBoundaryError
from hg.tests.test_chat_service import DIGEST, MODEL, FakeOllama

ROOT = Path(__file__).resolve().parents[2]

# key -> values a consumer cannot use (each one a separate case)
BAD = {
    "model_digest": [5, "", True, ["x"], "d" * 64 + "\n"],
    "ollama_service_dir": [1, True, "", ["/x"]],
    "ollama_url": [5, "", None],
    "model": [5, "", None, "qwen3:1.7b\n"],
    "max_tokens": ["400", 0, True, 64001, 1.5, None],
    "num_ctx": ["4096", 0, True, -1, None],
    "num_thread": [-1, 0, "4", False],
    "timeout_s": [-1, 0, "x", True, None, "NaN", "Infinity"],
    "think": ["no", 1, 0],
    "keep_alive": [[], True, "", {"m": 30}],
    "anthropic_model": [3, "", None],
}
# values that are usable (controls)
GOOD = {
    "model_digest": [None, DIGEST, "sha256:" + "a" * 64],
    "ollama_service_dir": [None, "/data/data/com.termux/files/usr/var/service/ollama"],
    "max_tokens": [1, 400, 64000],
    "num_ctx": [1, 4096, 32768],
    "num_thread": [1, 8],
    "timeout_s": [0.5, 10, 240],
    "think": [None, True, False],
    "keep_alive": [None, "30m", 0, -1, 300],
}


def _cases(table):
    for key, values in table.items():
        for value in values:
            yield key, value


def _raw(config, key, value):
    """config.json text; "NaN"/"Infinity" are written as the bare JSON tokens Python's json accepts."""
    if value in ("NaN", "Infinity"):
        config = dict(config, **{key: "@@"})
        return json.dumps(config).replace('"@@"', value)
    return json.dumps(dict(config, **{key: value}))


class ConfigValueOracleBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hg-cfg-oracle-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.home.mkdir(mode=0o700)
        self.ollama = FakeOllama()
        self.addCleanup(self.ollama.close)
        saved = os.environ.pop("HG_MODEL", None)
        self.addCleanup(lambda: saved is not None and os.environ.__setitem__("HG_MODEL", saved))
        self.base = {"ollama_url": self.ollama.url, "model": MODEL, "model_digest": DIGEST, "timeout_s": 10}

    def write(self, text):
        path = self.home / "config.json"
        path.write_text(text, encoding="utf-8")
        path.chmod(0o600)


class LoadRefusesUnusableValues(ConfigValueOracleBase):
    def test_every_unusable_value_is_refused_naming_the_key(self):
        for key, value in _cases(BAD):
            with self.subTest(key=key, value=value):
                self.write(_raw(self.base, key, value))
                with self.assertRaises(cfg.ConfigError) as ctx:
                    cfg.load(self.home)
                self.assertIn(key, str(ctx.exception))

    def test_usable_values_load_unchanged(self):
        for key, value in _cases(GOOD):
            with self.subTest(key=key, value=value):
                self.write(_raw(self.base, key, value))
                self.assertEqual(cfg.load(self.home)[key], value)

    def test_absent_file_and_explicit_defaults_load(self):
        self.assertEqual(cfg.load(self.home), cfg.DEFAULTS)
        self.write(json.dumps(cfg.DEFAULTS))
        self.assertEqual(cfg.load(self.home), cfg.DEFAULTS)

    def test_env_model_override_still_unpins(self):
        self.write(json.dumps(self.base))
        os.environ["HG_MODEL"] = "llama3.2:1b"
        try:
            conf = cfg.load(self.home)
        finally:
            del os.environ["HG_MODEL"]
        self.assertEqual((conf["model"], conf["model_digest"]), ("llama3.2:1b", None))


class SaveWritesOnlyUsableValues(ConfigValueOracleBase):
    def test_save_refuses_unusable_value_and_writes_nothing(self):
        for key, value in _cases(BAD):
            if value in ("NaN", "Infinity"):
                value = float(value.lower().replace("infinity", "inf"))
            with self.subTest(key=key, value=value):
                with self.assertRaises(cfg.ConfigError):
                    cfg.save(self.home, dict(cfg.DEFAULTS, **{key: value}))
                self.assertFalse((self.home / "config.json").exists())
                self.assertFalse((self.home / "config.json.tmp").exists())

    def test_save_then_load_round_trips(self):
        conf = dict(cfg.DEFAULTS, model="llama3.2:1b", model_digest=DIGEST, ollama_service_dir="/svc/ollama",
                    keep_alive=0, think=True, timeout_s=12.5)
        cfg.save(self.home, conf)
        self.assertEqual(cfg.load(self.home), conf)


class ChatRefusesBeforeTheModel(ConfigValueOracleBase):
    """`hg serve` chat: 503 assistant_unavailable, the model is never asked, no receipt written."""

    def test_chat_reports_unusable_config_not_a_damaged_ledger_or_a_crash(self):
        service = ChatService(self.home, release_id="r" * 64)
        for key, value in _cases(BAD):
            if key in ("ollama_url",):
                continue     # the fake model's URL is what the base config points at
            with self.subTest(key=key, value=value):
                self.write(_raw(self.base, key, value))
                with self.assertRaises(HTTPBoundaryError) as ctx:
                    service("Thủ đô của Pháp là gì?", general=True)
                self.assertEqual((ctx.exception.status, ctx.exception.code), (503, "assistant_unavailable"))
                self.assertIn("config.json", str(ctx.exception))
        self.assertEqual(self.ollama.chat_requests, [])
        self.assertEqual(list(self.home.glob("asks-*.jsonl")), [])

    def test_control_valid_config_answers(self):
        self.write(json.dumps(dict(self.base, keep_alive=0, think=False, max_tokens=64)))
        result = ChatService(self.home, release_id="r" * 64)("Thủ đô của Pháp là gì?", general=True)
        self.assertEqual(result["outcome"], "ANSWERED")
        sent = self.ollama.chat_requests[0]
        self.assertEqual((sent["think"], sent["keep_alive"], sent["options"]["num_predict"]), (False, 0, 64))


class CliExitsSeventyEight(ConfigValueOracleBase):
    """The owner's `hg ask` / `hg model status`: exit 78 with HG's message, never a traceback."""

    CASES = [("model_digest", 5), ("ollama_service_dir", 1), ("max_tokens", "400"), ("think", "no"),
             ("timeout_s", "NaN"), ("model_digest", "")]

    def run_hg(self, *argv):
        env = dict(os.environ, HG_HOME=str(self.home), NO_COLOR="1", PYTHONPATH=str(ROOT))
        env.pop("HG_MODEL", None)
        return subprocess.run([sys.executable, "-m", "hg", *argv], cwd=ROOT, env=env, capture_output=True,
                              text=True, timeout=60, stdin=subprocess.DEVNULL)

    def test_cli_refuses_with_exit_78(self):
        for key, value in self.CASES:
            for argv in (("ask", "--general", "Thủ đô của Pháp là gì?"), ("model", "status")):
                with self.subTest(key=key, value=value, argv=argv[0]):
                    self.write(_raw(self.base, key, value))
                    proc = self.run_hg(*argv)
                    self.assertEqual(proc.returncode, 78, proc.stdout + proc.stderr)
                    self.assertNotIn("Traceback", proc.stderr)
                    self.assertIn(key, proc.stdout)
        self.assertEqual(self.ollama.chat_requests, [])

    def test_control_valid_config_status_ready(self):
        self.write(json.dumps(self.base))
        proc = self.run_hg("model", "status")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("READY", proc.stdout)


if __name__ == "__main__":
    unittest.main()

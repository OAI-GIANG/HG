"""Assistant settings and the local-model connection.

Settings live in $HG_HOME/config.json (strict keys, optional). Defaults keep everything on
the phone: Ollama on 127.0.0.1, no paid provider. A paid provider is used only for the one
call where the owner passes `--provider anthropic` (and the key is set): it is never a
silent fallback, because the router is built with exactly the chosen provider.

Local-model integrity, as far as Android allows:
- /proc/net/tcp is unreadable for apps on Android 10+, so HG cannot ask the kernel who owns
  port 11434. When `ollama_service_dir` is configured (the deploy sets it), HG requires that
  the runit-supervised Ollama process is alive, is the ollama binary and runs as this user;
  anything else -> refused. That is process evidence only: it does not show the process holds
  the port (finding F-1), so receipts carry "listener": "UNVERIFIED". The five-layer check that
  does test listener ownership is hg.assistant.attest (not yet wired into this path).
- `model_digest` pins the exact model weights: another app on the phone can replace a model
  through Ollama's unauthenticated API, so before each call HG compares /api/tags with the pin.
"""
import json
import os
import stat
from pathlib import Path

from hg.brain.providers import AnthropicProvider, ModelRouter, OllamaProvider, ProviderError

DEFAULTS = {
    "ollama_url": "http://127.0.0.1:11434",
    "model": "qwen3:1.7b",
    "model_digest": None,
    "ollama_service_dir": None,
    "num_ctx": 4096,
    "num_thread": 4,
    "keep_alive": "30m",
    "think": False,
    "timeout_s": 240,
    "max_tokens": 400,
    "anthropic_model": "claude-sonnet-5-5",
}


class ConfigError(Exception):
    """Unusable settings or an untrusted local model (exit 78)."""


def load(home):
    path = Path(home) / "config.json"
    config = dict(DEFAULTS)
    if path.exists():
        st = path.lstat()
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
            raise ConfigError("config.json must be a regular file owned by this user")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ConfigError(f"config.json is not valid JSON: {exc}") from exc
        if not isinstance(data, dict) or set(data) - set(DEFAULTS):
            raise ConfigError("config.json keys must be among: " + ", ".join(sorted(DEFAULTS)))
        config.update(data)
    env_model = os.environ.get("HG_MODEL")
    if env_model and env_model != config["model"]:
        config["model"], config["model_digest"] = env_model, None     # a pin belongs to one model
    return config


def save(home, config):
    data = {k: v for k, v in config.items() if k in DEFAULTS and v != DEFAULTS[k]}
    path = Path(home) / "config.json"
    tmp = path.with_suffix(".json.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    os.replace(tmp, path)
    return path


def ollama(config):
    try:
        return OllamaProvider(config["model"], base_url=config["ollama_url"], timeout=config["timeout_s"],
                              options={"num_ctx": config["num_ctx"], "num_thread": config["num_thread"]},
                              think=config["think"], keep_alive=config["keep_alive"])
    except Exception as exc:
        raise ConfigError(str(exc)) from exc


def attest_listener(config, *, proc=Path("/proc")):
    """Return {"status": VERIFIED_PROCESS|UNVERIFIED, ...}; raise ConfigError when required and failing."""
    service = config.get("ollama_service_dir")
    if not service:
        return {"status": "UNVERIFIED", "reason": "ollama_service_dir not configured"}
    try:
        pid = int((Path(service) / "supervise" / "pid").read_text().strip())
        exe = os.readlink(proc / str(pid) / "exe")
        owner = (proc / str(pid)).stat().st_uid
    except (OSError, ValueError) as exc:
        raise ConfigError(f"supervised Ollama is not running ({exc.__class__.__name__}); start it: sv up ollama") from exc
    if os.path.basename(exe) != "ollama" or owner != os.getuid():
        raise ConfigError("the process on the Ollama service is not this user's ollama binary")
    # A live supervised process does not prove it holds the port: while another process holds it,
    # runit keeps restarting Ollama and each attempt is briefly alive (finding F-1,
    # docs/architecture/HG_LISTENER_ATTESTATION_V2.md). Listener ownership is hg.assistant.attest's L5.
    return {"status": "VERIFIED_PROCESS", "pid": pid, "listener": "UNVERIFIED",
            "reason": "runit-supervised ollama alive as this user; listener ownership not verified (F-1)"}


def check_model(config, provider, *, tags=None):
    """Confirm the configured model is present and, if pinned, has the pinned digest."""
    try:
        models = provider.tags() if tags is None else tags
    except ProviderError as exc:
        return {"status": "UNAVAILABLE", "reason": str(exc)}
    match = next((m for m in models if m["name"] == config["model"]
                  or m["name"] == f"{config['model']}:latest"), None)
    if match is None:
        return {"status": "MISSING", "reason": f"model {config['model']} is not pulled",
                "available": [m["name"] for m in models]}
    if config.get("model_digest") and match["digest"] != config["model_digest"]:
        raise ConfigError(f"model {config['model']} digest changed (pinned {config['model_digest'][:12]}…, "
                          f"found {str(match['digest'])[:12]}…); re-pin with: hg model use {config['model']}")
    return {"status": "READY", "model": match["name"], "digest": match["digest"], "size": match["size"],
            "pinned": bool(config.get("model_digest"))}


def router(config, *, provider_choice="local", event_log=None):
    """Exactly one provider; local calls are never retried (the owner is waiting on a phone CPU)."""
    if provider_choice == "local":
        return ModelRouter([ollama(config)], max_retries=0, event_log=event_log)
    if provider_choice == "anthropic":
        return ModelRouter([AnthropicProvider(config["anthropic_model"])], max_retries=1, event_log=event_log)
    raise ConfigError("provider must be 'local' or 'anthropic'")

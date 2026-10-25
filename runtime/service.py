"""Explicit, fail-closed entrypoint for the standalone HG runtime.

No providers, identity, trust roots, policy, storage paths, credentials, or test
adapters are created here. An operator must explicitly configure a factory that
constructs HG's existing composition and authenticated loopback HTTP boundary.
"""
from __future__ import annotations

import importlib
import os
import signal
import sys
import threading
from typing import Callable

from runtime.http_server import HGHTTPServer

FACTORY_ENV = "HG_RUNTIME_FACTORY"
BLOCKED_EXIT = 78


class RuntimeStartupError(RuntimeError):
    """Safe-to-report startup/configuration failure."""


def load_factory(spec: str | None = None) -> Callable[[], HGHTTPServer]:
    """Load an explicitly selected ``module:callable`` factory.

    Importing the configured module executes its Python code; the value must
    therefore be set only to an operator-approved HG configuration module.
    No implicit/default module is searched for.
    """
    value = spec if spec is not None else os.environ.get(FACTORY_ENV)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeStartupError(f"{FACTORY_ENV} is required; no runtime configuration is implicit")
    if value.count(":") != 1:
        raise RuntimeStartupError(f"{FACTORY_ENV} must use module:callable syntax")
    module_name, attr_name = (part.strip() for part in value.split(":", 1))
    if (not module_name or not attr_name
            or not all(part.isidentifier() for part in module_name.split("."))
            or not attr_name.isidentifier()):
        raise RuntimeStartupError(f"{FACTORY_ENV} has invalid module:callable syntax")
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        raise RuntimeStartupError(f"configured HG runtime factory could not be imported ({type(exc).__name__})") from exc
    factory = getattr(module, attr_name, None)
    if not callable(factory):
        raise RuntimeStartupError("configured HG runtime factory is missing or not callable")
    return factory


def create_service(spec: str | None = None) -> HGHTTPServer:
    """Build the service through an explicitly approved HG-only factory."""
    factory = load_factory(spec)
    try:
        service = factory()
    except Exception as exc:
        raise RuntimeStartupError(f"HG runtime composition failed closed ({type(exc).__name__})") from exc
    if not isinstance(service, HGHTTPServer):
        raise RuntimeStartupError("factory must return runtime.http_server.HGHTTPServer")
    address = service.address
    if not (isinstance(address, tuple) and len(address) >= 2
            and address[0] == "127.0.0.1" and isinstance(address[1], int)):
        try:
            service.shutdown()
        finally:
            raise RuntimeStartupError("HG runtime must bind to IPv4 loopback only")
    return service


def main() -> int:
    """Run the explicitly configured service; missing trust/config blocks startup."""
    try:
        service = create_service()
    except RuntimeStartupError as exc:
        print(f"HG_BLOCKED: {exc}", file=sys.stderr)
        return BLOCKED_EXIT
    except Exception as exc:
        # Avoid printing provider exceptions, request data, paths or credentials.
        print(f"HG_BLOCKED: unexpected startup failure ({type(exc).__name__})", file=sys.stderr)
        return BLOCKED_EXIT

    shutdown_started = threading.Event()

    def request_shutdown(signum, frame):
        if shutdown_started.is_set():
            return
        shutdown_started.set()
        threading.Thread(target=service.shutdown, name="hg-runtime-shutdown", daemon=True).start()

    previous_handlers = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[sig] = signal.signal(sig, request_shutdown)
    print(f"HG_RUNTIME_READY host={service.address[0]} port={service.address[1]}", flush=True)
    try:
        service.serve_forever()
    except KeyboardInterrupt:
        request_shutdown(signal.SIGINT, None)
    finally:
        if not shutdown_started.is_set():
            try:
                service.shutdown()
            except Exception:
                pass
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""ActionGateway: the tool execution boundary (RT-02, RT-05; MAEP-003, 005, 018, 019, 023).

Immediately before every side effect the gateway: reads the planned step from the
task-state owner `maep.task_store.TaskStore` (never from its caller), checks the task is RUNNING and has no
unreconciled action, enforces the execution mode, confirms the adapter's real effect
matches the planned action/resource, has the adapter check scope independently, and
asks PolicyEvaluator for a fresh decision. Any failure denies the effect.

Outcome taxonomy (MIID §10): SUCCEEDED (adapter post-check passed),
SUCCEEDED_UNVERIFIED, FAILED (known failure, no effect), UNKNOWN (effect may have
happened), DENIED, BLOCKED, TOOL_UNAVAILABLE, INVALID_INPUT.

An action that started but did not finish with a known outcome stays pending, across
restarts (rebuilt from the ledger), and blocks further effects on that task until
reconcile() inspects live state.
"""
import concurrent.futures
import hashlib
import os
import tempfile
from pathlib import Path, PurePosixPath

from maep.core import MAEPError, POLICY_VERSION, enforce_execution_mode, recovery_decision
from hg.brain.plan import step_request

OUTCOMES = {"SUCCEEDED", "SUCCEEDED_UNVERIFIED", "FAILED", "UNKNOWN", "DENIED", "BLOCKED",
            "TOOL_UNAVAILABLE", "INVALID_INPUT"}
SETTLED = {"SUCCEEDED", "SUCCEEDED_UNVERIFIED", "FAILED"}


class AdapterInputError(ValueError):
    """Parameters are invalid; nothing was attempted."""


class AdapterFailure(RuntimeError):
    """The operation failed in a way known to have produced no effect."""


class AdapterRefused(AdapterFailure):
    """The adapter refused to act: no valid permit from its gateway. Nothing was attempted."""


class _Permit:
    """Single-use authority for one effect, minted only by ActionGateway after ALLOW (RT-06).

    Bound to the minting gateway's key and to the exact resource. An adapter performs an
    effect only with a matching, unused permit, so calling an adapter directly -- outside
    the gateway's checks -- does nothing. In-process limit: code that reaches private
    attributes could still mint one.
    """
    __slots__ = ("_key", "resource", "action_id", "_used")

    def __init__(self, key, resource, action_id):
        self._key, self.resource, self.action_id, self._used = key, resource, action_id, False


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


class ToolAdapter:
    """Contract every adapter declares (MIID §10). Subclasses override the methods."""

    name = None
    version = None
    action = None            # one of maep.policy.GRANT_ACTIONS
    idempotent = False
    risk = "LOW"
    timeout_s = 10.0
    description = ""
    params_schema = {}       # param name -> python type
    _gateway_key = None      # set once by the ActionGateway the adapter is registered with

    def bind(self, key):
        if self._gateway_key is not None and self._gateway_key is not key:
            raise MAEPError(f"tool {self.name} is already registered with another gateway")
        self._gateway_key = key

    def execute(self, params, permit=None):
        """Perform the effect only with an unused permit from this adapter's own gateway."""
        if (not isinstance(permit, _Permit) or self._gateway_key is None
                or permit._key is not self._gateway_key):
            raise AdapterRefused("effect requires a permit from the gateway this tool is registered with")
        if permit._used or permit.resource != self.resource_for(params):
            raise AdapterRefused("permit already used or issued for another resource")
        permit._used = True
        return self._perform(params)

    def describe(self):
        return {"name": self.name, "version": self.version, "action": self.action,
                "idempotent": self.idempotent, "risk": self.risk, "timeout_s": self.timeout_s,
                "description": self.description,
                "params": {k: t.__name__ for k, t in self.params_schema.items()}}

    def validate_params(self, params):
        if not isinstance(params, dict) or set(params) != set(self.params_schema):
            raise AdapterInputError("params must have exactly: " + ", ".join(sorted(self.params_schema)))
        for key, kind in self.params_schema.items():
            if not isinstance(params[key], kind):
                raise AdapterInputError(f"param {key} must be {kind.__name__}")

    def resource_for(self, params):
        raise NotImplementedError

    def in_scope(self, params, scope):
        raise NotImplementedError

    def intent(self, params):
        """Small, secret-free description of the intended effect, kept for reconciliation."""
        raise NotImplementedError

    def _perform(self, params):
        raise NotImplementedError

    def verify(self, params, observed):
        return False

    def reconcile(self, intent):
        """Inspect live state: APPLIED, NOT_APPLIED or UNKNOWN."""
        return "UNKNOWN"


class _RootedFileAdapter(ToolAdapter):
    """Paths are relative POSIX paths confined to one root directory."""

    def __init__(self, root):
        self._root = Path(root).resolve()

    def _rel(self, raw):
        path = PurePosixPath(raw)
        if not raw or path.is_absolute() or ".." in path.parts or "\\" in raw:
            raise AdapterInputError("path must be relative, inside the root, without '..'")
        full = (self._root / path).resolve()
        if full != self._root and self._root not in full.parents:
            raise AdapterInputError("path escapes the adapter root")
        return path.as_posix(), full

    def resource_for(self, params):
        return "file:" + self._rel(params["path"])[0]

    def in_scope(self, params, scope):
        rel = self._rel(params["path"])[0]
        for prefix in scope:
            base = prefix.rstrip("/")
            if rel == base or rel.startswith(base + "/"):
                return True
        return False


class LocalFileWriteAdapter(_RootedFileAdapter):
    name = "fs.write"
    version = "1.0"
    action = "WRITE"
    idempotent = True        # atomic replace with the same content gives the same state
    risk = "MEDIUM"
    description = "Atomically write UTF-8 text to a file under the adapter root."
    params_schema = {"path": str, "content": str}

    def intent(self, params):
        data = params["content"].encode("utf-8")
        return {"path": self._rel(params["path"])[0], "sha256": _sha256(data), "bytes": len(data)}

    def _perform(self, params):
        rel, full = self._rel(params["path"])
        data = params["content"].encode("utf-8")
        full.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(full.parent), prefix=".hg-tmp-")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, full)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        return {"path": rel, "sha256": _sha256(data), "bytes": len(data)}

    def verify(self, params, observed):
        _rel, full = self._rel(params["path"])
        return full.is_file() and _sha256(full.read_bytes()) == observed.get("sha256")

    def reconcile(self, intent):
        try:
            _rel, full = self._rel(intent["path"])
        except (AdapterInputError, KeyError):
            return "UNKNOWN"
        if full.is_file() and _sha256(full.read_bytes()) == intent.get("sha256"):
            return "APPLIED"
        return "NOT_APPLIED"


class LocalFileReadAdapter(_RootedFileAdapter):
    name = "fs.read"
    version = "1.0"
    action = "READ"
    idempotent = True
    risk = "LOW"
    description = "Read a UTF-8 text file under the adapter root."
    params_schema = {"path": str}

    def intent(self, params):
        return {"path": self._rel(params["path"])[0]}

    def _perform(self, params):
        rel, full = self._rel(params["path"])
        if not full.is_file():
            raise AdapterFailure("file does not exist")
        data = full.read_bytes()
        return {"path": rel, "sha256": _sha256(data), "bytes": len(data),
                "content": data.decode("utf-8", errors="replace")}

    def verify(self, params, observed):
        return True

    def reconcile(self, intent):
        return "APPLIED"     # reads have no effect to reconcile


def pending_from_events(events):
    """Actions started but neither settled nor reconciled to a known outcome (MAEP-018)."""
    pending = {}
    for event in events:
        payload = event["payload"]
        if event["kind"] == "ACTION_STARTED":
            pending[payload["action_id"]] = {
                "action_id": payload["action_id"], "task_id": event["task_id"],
                "step_id": payload["step_id"], "tool": payload["tool"], "intent": payload["intent"]}
        elif event["kind"] == "ACTION_COMPLETED" and payload["status"] in SETTLED:
            pending.pop(payload["action_id"], None)
        elif event["kind"] == "ACTION_RECONCILED" and payload["finding"] != "UNKNOWN":
            pending.pop(payload["action_id"], None)
    return pending


class ActionGateway:
    def __init__(self, store, evaluator, event_log, adapters, *, principal, mode="AUTHORIZED_EXECUTION",
                 policy_version=POLICY_VERSION):
        enforce_execution_mode(mode, "READ")       # rejects an unknown mode up front
        if not isinstance(principal, str) or not principal.strip():
            raise MAEPError("gateway principal must be non-empty")
        self._principal = principal
        self._snapshot = store.snapshot            # read access only; the gateway never mutates tasks
        self._evaluator = evaluator
        self._log = event_log
        self._mode = mode
        self._policy_version = policy_version
        self._key = object()
        self._adapters = {}
        for adapter in adapters:
            if adapter.name in self._adapters:
                raise MAEPError("duplicate tool name in registry")
            self._adapters[adapter.name] = adapter
        for adapter in self._adapters.values():
            adapter.bind(self._key)
        self._pending = self._rebuild_pending()

    # ---------- registry / introspection ----------

    def now(self):
        return self._log.now()

    def registry(self):
        return [a.describe() for a in self._adapters.values()]

    def pending_actions(self, task_id=None):
        return [dict(p) for p in self._pending.values() if task_id is None or p["task_id"] == task_id]

    def _rebuild_pending(self):
        return pending_from_events(self._log.events())

    # ---------- execution ----------

    def preflight(self, task_id):
        """Policy decisions for every planned step, evaluated now, with no effect and no record.

        Lets the coordinator refuse to start a plan that could only be partially executed.
        Execution still re-checks each step immediately before its effect (MAEP-003).
        """
        snapshot = self._snapshot(task_id)
        now = self._log.now()
        return [{"step_id": step["step_id"],
                 "decision": self._evaluator.evaluate(
                     step_request(step, self._principal, task_id, self._policy_version), now=now)}
                for step in (snapshot["plan"] or [])]

    def _outcome(self, task_id, step_id, status, reason, **extra):
        outcome = {"task_id": task_id, "step_id": step_id, "status": status, "reason": reason}
        outcome.update(extra)
        if status in {"DENIED", "BLOCKED", "TOOL_UNAVAILABLE", "INVALID_INPUT"}:
            try:
                self._log.append("ACTION_REFUSED", task_id, {k: v for k, v in outcome.items() if k != "task_id"})
            except Exception:
                pass    # nothing was executed; a refusal that cannot be logged is still a refusal
        return outcome

    def execute(self, task_id, step_id):
        try:
            snapshot = self._snapshot(task_id)
        except MAEPError as exc:
            return self._outcome(task_id, step_id, "BLOCKED", str(exc))
        if snapshot["task"]["state"] != "RUNNING":
            return self._outcome(task_id, step_id, "BLOCKED", "task is not RUNNING")
        if self.pending_actions(task_id):
            return self._outcome(task_id, step_id, "BLOCKED", "unreconciled action on this task")
        steps = {s["step_id"]: s for s in (snapshot["plan"] or [])}
        if step_id not in steps:
            return self._outcome(task_id, step_id, "BLOCKED", "step is not in the recorded plan")
        step = steps[step_id]
        adapter = self._adapters.get(step["tool"])
        if adapter is None:
            return self._outcome(task_id, step_id, "TOOL_UNAVAILABLE", f"no tool named {step['tool']}")
        params = step["params"]
        try:
            adapter.validate_params(params)
            resource = adapter.resource_for(params)
            in_scope = adapter.in_scope(params, step["scope"])
            intent = adapter.intent(params)
        except AdapterInputError as exc:
            return self._outcome(task_id, step_id, "INVALID_INPUT", str(exc))
        try:
            enforce_execution_mode(self._mode, adapter.action)
        except MAEPError as exc:
            return self._outcome(task_id, step_id, "DENIED", str(exc))
        if adapter.action != step["action"] or resource != step["resource"]:
            return self._outcome(task_id, step_id, "DENIED", "tool effect does not match the planned action/resource")
        if not in_scope:
            return self._outcome(task_id, step_id, "DENIED", "adapter scope check failed")
        request = step_request(step, self._principal, task_id, self._policy_version)
        decision = self._evaluator.evaluate(request, now=self._log.now())
        if decision["decision"] != "ALLOW":
            return self._outcome(task_id, step_id, "DENIED", decision["reason"], decision=decision)

        action_id = f"{task_id}:{step_id}:{self._log.next_seq()}"
        try:
            self._log.append("ACTION_STARTED", task_id, {
                "action_id": action_id, "step_id": step_id, "tool": adapter.name,
                "tool_version": adapter.version, "request": request, "decision": decision,
                "intent": intent})
        except Exception as exc:
            return self._outcome(task_id, step_id, "BLOCKED", f"evidence capture failed before effect: {exc}")
        self._pending[action_id] = {"action_id": action_id, "task_id": task_id, "step_id": step_id,
                                    "tool": adapter.name, "intent": intent}

        status, reason, observed = self._run(adapter, params, _Permit(self._key, resource, action_id))
        record = {"action_id": action_id, "step_id": step_id, "status": status, "reason": reason,
                  "observed": {k: v for k, v in observed.items() if k != "content"}}
        try:
            self._log.append("ACTION_COMPLETED", task_id, record)
        except Exception as exc:
            # The effect may have happened but is not recorded: leave it pending.
            return self._outcome(task_id, step_id, "UNKNOWN", f"completion not recorded: {exc}",
                                 action_id=action_id, observed=observed)
        if status in SETTLED:
            self._pending.pop(action_id, None)
        return self._outcome(task_id, step_id, status, reason, action_id=action_id,
                             observed=observed, decision=decision)

    @staticmethod
    def _run(adapter, params, permit):
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = pool.submit(adapter.execute, params, permit)
        try:
            observed = future.result(timeout=adapter.timeout_s)
        except concurrent.futures.TimeoutError:
            pool.shutdown(wait=False, cancel_futures=True)
            return "UNKNOWN", "timed out; the effect may still happen", {}
        except AdapterFailure as exc:
            pool.shutdown(wait=False)
            return "FAILED", str(exc), {}
        except TimeoutError as exc:
            pool.shutdown(wait=False)
            return "UNKNOWN", f"timed out: {exc}", {}
        except Exception as exc:
            pool.shutdown(wait=False)
            return "UNKNOWN", f"{type(exc).__name__}: {exc}", {}
        pool.shutdown(wait=False)
        try:
            verified = adapter.verify(params, observed) is True
        except Exception:
            verified = False
        return ("SUCCEEDED" if verified else "SUCCEEDED_UNVERIFIED"), "", observed

    # ---------- recovery ----------

    def reconcile(self, action_id):
        """Inspect live state for a pending action (MAEP-018). Never replays it."""
        pending = self._pending.get(action_id)
        if pending is None:
            raise MAEPError("no pending action with that id")
        adapter = self._adapters.get(pending["tool"])
        finding = adapter.reconcile(pending["intent"]) if adapter else "UNKNOWN"
        if finding not in {"APPLIED", "NOT_APPLIED", "UNKNOWN"}:
            finding = "UNKNOWN"
        known = finding != "UNKNOWN"
        decision = recovery_decision(known, bool(adapter and adapter.idempotent), known)
        self._log.append("ACTION_RECONCILED", pending["task_id"],
                         {"action_id": action_id, "finding": finding, "recovery_decision": decision})
        if known:
            self._pending.pop(action_id, None)
        return {"action_id": action_id, "task_id": pending["task_id"], "finding": finding,
                "recovery_decision": decision}

"""C-20 Code-intelligence and research tools, behind ActionGateway like every other tool.

Each adapter declares its action, parameters, idempotency and how its effect can be
reconciled. None can act without a gateway permit (RT-06), so every search, test run or
URL read is authorized, permitted and recorded.

- code.search  READ    literal text search under a path (bounded output)
- code.symbols READ    Python definitions and call names via `ast` (no execution)
- code.diff    READ    unified diff of a file against provided text
- test.run     EXECUTE `python -m unittest discover` on a path, with a timeout. It runs
               code, so it is not idempotent and its outcome cannot be reconciled after
               a crash: an interrupted run stays UNKNOWN until a person decides.
- url.read     READ    HTTP(S) GET of one URL (resource "url:<url>"), size-capped.
               The owner manifest must list a matching "url:" scope for anchored use.
"""
import ast
import difflib
import hashlib
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

from hg.tools.gateway import AdapterFailure, AdapterInputError, ToolAdapter, _RootedFileAdapter

SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules"}
MAX_FILE_BYTES = 1_000_000
MAX_MATCHES = 200


def _iter_text_files(full):
    if full.is_file():
        yield full
        return
    for dirpath, dirnames, filenames in os.walk(full):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            yield type(full)(dirpath) / name


def _read_text(path):
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


class _ReadOnlyRooted(_RootedFileAdapter):
    action = "READ"
    idempotent = True
    risk = "LOW"
    ledger_exclude = {"content", "matches", "symbols", "diff"}

    def intent(self, params):
        return {"path": self._rel(params["path"])[0]}

    def verify(self, params, observed):
        return True

    def reconcile(self, intent):
        return "APPLIED"        # reads change nothing


class CodeSearchAdapter(_ReadOnlyRooted):
    name = "code.search"
    version = "1.0"
    description = "Literal text search in UTF-8 files under a path (skips VCS/cache dirs)."
    params_schema = {"path": str, "pattern": str}

    def validate_params(self, params):
        super().validate_params(params)
        if not params["pattern"]:
            raise AdapterInputError("pattern must be non-empty")

    def _perform(self, params):
        rel, full = self._rel(params["path"])
        if not full.exists():
            raise AdapterFailure("path does not exist")
        matches, scanned, truncated = [], 0, False
        for file in _iter_text_files(full):
            text = _read_text(file)
            if text is None:
                continue
            scanned += 1
            for number, line in enumerate(text.splitlines(), 1):
                if params["pattern"] in line:
                    if len(matches) >= MAX_MATCHES:
                        truncated = True
                        break
                    matches.append({"file": file.relative_to(self._root).as_posix(), "line": number,
                                    "text": line.strip()[:300]})
            if truncated:
                break
        return {"path": rel, "pattern": params["pattern"], "files_scanned": scanned, "match_count": len(matches),
                "truncated": truncated, "matches": matches}


class SymbolIndexAdapter(_ReadOnlyRooted):
    name = "code.symbols"
    version = "1.0"
    description = "Index Python classes/functions (with qualified names and lines) and called names, via ast."
    params_schema = {"path": str}

    def _perform(self, params):
        rel, full = self._rel(params["path"])
        if not full.exists():
            raise AdapterFailure("path does not exist")
        symbols, calls, errors = [], {}, []
        for file in _iter_text_files(full):
            if file.suffix != ".py":
                continue
            text = _read_text(file)
            if text is None:
                continue
            name = file.relative_to(self._root).as_posix()
            try:
                tree = ast.parse(text, filename=name)
            except SyntaxError as exc:
                errors.append({"file": name, "line": exc.lineno, "error": exc.msg})
                continue

            def visit(node, prefix):
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        qual = f"{prefix}{child.name}"
                        kind = "class" if isinstance(child, ast.ClassDef) else "function"
                        symbols.append({"file": name, "name": child.name, "qualname": qual, "kind": kind,
                                        "line": child.lineno})
                        visit(child, qual + ".")
                    else:
                        visit(child, prefix)
            visit(tree, "")
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                    if called:
                        calls[called] = calls.get(called, 0) + 1
        return {"path": rel, "symbol_count": len(symbols), "symbols": symbols,
                "top_calls": sorted(calls.items(), key=lambda kv: (-kv[1], kv[0]))[:50], "syntax_errors": errors}


class CodeDiffAdapter(_ReadOnlyRooted):
    name = "code.diff"
    version = "1.0"
    description = "Unified diff of a file under the root against provided text (the file is only read)."
    params_schema = {"path": str, "against": str}

    def _perform(self, params):
        rel, full = self._rel(params["path"])
        current = _read_text(full) if full.is_file() else None
        if current is None:
            raise AdapterFailure("path is not a readable UTF-8 file")
        diff = list(difflib.unified_diff(params["against"].splitlines(), current.splitlines(),
                                         fromfile="against", tofile=rel, lineterm=""))
        added = sum(1 for d in diff if d.startswith("+") and not d.startswith("+++"))
        removed = sum(1 for d in diff if d.startswith("-") and not d.startswith("---"))
        return {"path": rel, "identical": not diff, "added": added, "removed": removed, "diff": diff[:2000]}


_RAN = re.compile(r"^Ran (\d+) tests? in", re.M)
_FAILED = re.compile(r"^FAILED \((.*)\)$", re.M)


class TestRunAdapter(_RootedFileAdapter):
    name = "test.run"
    version = "1.0"
    action = "EXECUTE"
    idempotent = False
    risk = "HIGH"
    timeout_s = 600
    description = "Run `python -m unittest discover` on a directory under the root (executes code)."
    params_schema = {"path": str}
    ledger_exclude = {"output_tail"}

    def intent(self, params):
        return {"path": self._rel(params["path"])[0]}

    def _perform(self, params):
        rel, full = self._rel(params["path"])
        if not full.is_dir():
            raise AdapterFailure("test path is not a directory")
        env = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "LANG", "LC_ALL", "SYSTEMROOT", "TMPDIR"}}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(full), "-t", str(full)],
                                  cwd=str(full), env=env, capture_output=True, text=True,
                                  timeout=max(self.timeout_s - 5, 1))
        except subprocess.TimeoutExpired:
            raise TimeoutError("test run exceeded its time limit")
        output = proc.stderr + proc.stdout
        ran = _RAN.search(output)
        failed = _FAILED.search(output)
        counts = dict(re.findall(r"(\w+)=(\d+)", failed.group(1))) if failed else {}
        return {"path": rel, "exit_code": proc.returncode, "tests_run": int(ran.group(1)) if ran else None,
                "failures": int(counts.get("failures", 0)), "errors": int(counts.get("errors", 0)),
                "ok": proc.returncode == 0 and ran is not None,
                "output_sha256": hashlib.sha256(output.encode()).hexdigest(), "output_tail": output[-4000:]}

    def verify(self, params, observed):
        return observed.get("tests_run") is not None       # the run completed and reported

    def reconcile(self, intent):
        return "UNKNOWN"     # a test run's side effects cannot be inspected afterwards


class UrlReadAdapter(ToolAdapter):
    name = "url.read"
    version = "1.0"
    action = "READ"
    idempotent = True
    risk = "LOW"
    timeout_s = 20
    description = "HTTP(S) GET of one URL; text responses returned, size-capped at 2 MB."
    params_schema = {"url": str}
    ledger_exclude = {"text"}
    MAX_BYTES = 2_000_000

    def _canonical(self, raw):
        parts = urllib.parse.urlsplit(raw)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise AdapterInputError("url must be absolute http(s)")
        if parts.username or parts.password:
            raise AdapterInputError("credentials in URLs are not allowed")
        netloc = parts.hostname.lower() + (f":{parts.port}" if parts.port else "")
        return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))

    def validate_params(self, params):
        super().validate_params(params)
        self._canonical(params["url"])

    def resource_for(self, params):
        return "url:" + self._canonical(params["url"])

    def in_scope(self, params, scope):
        url = self._canonical(params["url"])
        return any(url == s or url.startswith(s if s.endswith("/") else s + "/") for s in scope)

    def intent(self, params):
        return {"url": self._canonical(params["url"])}

    def _perform(self, params):
        url = self._canonical(params["url"])
        request = urllib.request.Request(url, headers={"User-Agent": "HG-url.read/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s - 2) as response:
                data = response.read(self.MAX_BYTES + 1)
                status, ctype = response.status, response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            raise AdapterFailure(f"HTTP {exc.code}")
        except (urllib.error.URLError, OSError) as exc:
            raise AdapterFailure(f"cannot read {url}: {getattr(exc, 'reason', exc)}")
        truncated = len(data) > self.MAX_BYTES
        data = data[:self.MAX_BYTES]
        textual = ctype.startswith("text/") or "json" in ctype or "xml" in ctype
        return {"url": url, "status": status, "content_type": ctype, "bytes": len(data), "truncated": truncated,
                "sha256": hashlib.sha256(data).hexdigest(),
                "text": data.decode("utf-8", errors="replace") if textual else None}

    def verify(self, params, observed):
        return observed.get("status") == 200

    def reconcile(self, intent):
        return "APPLIED"

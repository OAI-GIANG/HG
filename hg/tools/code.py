"""C-20 Code-intelligence and research tools, behind ActionGateway like every other tool.

Each adapter declares its action, parameters, idempotency and how its effect can be
reconciled. None can act without a gateway permit (RT-06), so every search, test run or
URL read is authorized, permitted and recorded.

- code.search  READ    literal text search under a path (bounded output)
- code.symbols READ    Python definitions and call names via `ast` (no execution)
- code.diff    READ    unified diff of a file against provided text
               These three count lines as Python does (LF, CRLF, CR), list every file
               a walk did not read in `files_skipped` with a reason, and fail on a single
               start file they cannot read; `identical` means the exact same text.
- test.run     EXECUTE `python -m unittest discover` on a path, with a timeout. It runs
               code, so it is not idempotent and its outcome cannot be reconciled after
               a crash: an interrupted run stays UNKNOWN until a person decides. Output
               is streamed (hashed in full, tail kept), never decides the outcome beyond
               unittest's own final summary, and no process the run starts outlives it.
- url.read     READ    HTTP(S) GET of one URL (resource "url:<url>"), size-capped.
               The owner manifest must list a matching "url:" scope for anchored use.
               Redirects are never followed: a 3xx names a URL nobody authorized, so it is
               a known failure, not a read of the redirect target.
"""
import ast
import difflib
import hashlib
import http.client
import os
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from hg.tools.gateway import AdapterFailure, AdapterInputError, ToolAdapter, _RootedFileAdapter, read_regular_file

SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules"}
MAX_FILE_BYTES = 1_000_000
MAX_MATCHES = 200
MAX_DIFF_LINES = 2000


def _iter_text_files(full):
    """Candidate files under `full`. os.walk does not descend into symlinked directories;
    symlinked or non-regular files are skipped later by `_read_text`."""
    try:
        mode = os.lstat(full).st_mode
    except OSError:
        raise AdapterFailure("path does not exist")
    if stat.S_ISREG(mode):
        yield full
        return
    if not stat.S_ISDIR(mode):
        raise AdapterFailure("path is not a regular file or directory")
    for dirpath, dirnames, filenames in os.walk(full):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            yield type(full)(dirpath) / name


def _read_file(path):
    """(text, None) for a regular, non-symlinked UTF-8 file of at most MAX_FILE_BYTES,
    else (None, reason).

    Never follows a symlinked file (it may point outside the root or the authorized scope)
    and never blocks on a FIFO or device. The reason names no content and no link target.
    """
    try:
        data = read_regular_file(path, MAX_FILE_BYTES)
    except OSError:
        return None, "not a regular file"
    if data is None:
        return None, f"over {MAX_FILE_BYTES} bytes"
    try:
        return data.decode("utf-8"), None
    except UnicodeDecodeError as exc:
        return None, f"not UTF-8 text (byte {exc.start})"


def _read_text(path):
    return _read_file(path)[0]


_LINE_BREAK = re.compile(r"\r\n|\r|\n")
_LINE_KEEPENDS = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+\Z")


def _lines(text):
    """Lines as Python's tokenizer, editors and `grep -n` count them: only LF, CRLF and CR
    end a line (str.splitlines also splits on VT, FF, FS/GS/RS, NEL, U+2028/U+2029)."""
    parts = _LINE_BREAK.split(text)
    if parts and parts[-1] == "":
        parts.pop()
    return parts


def _scan(adapter, full, suffix=None):
    """Yield (relative name, text) of each readable candidate file; record the others.

    A single start file that cannot be read is a known failure, not an empty result."""
    skipped = []
    single = stat.S_ISREG(os.lstat(full).st_mode) if os.path.lexists(full) else False

    def files():
        for file in _iter_text_files(full):
            if suffix is not None and file.suffix != suffix:
                continue
            name = file.relative_to(adapter._root).as_posix()
            text, reason = _read_file(file)
            if text is None:
                if single:
                    raise AdapterFailure(f"{name}: {reason}")
                skipped.append({"file": name, "reason": reason})
                continue
            yield name, text
    return files(), skipped


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
    version = "1.1"
    description = "Literal text search in UTF-8 files under a path (skips VCS/cache dirs)."
    params_schema = {"path": str, "pattern": str}

    def validate_params(self, params):
        super().validate_params(params)
        if not params["pattern"]:
            raise AdapterInputError("pattern must be non-empty")
        if "\r" in params["pattern"] or "\n" in params["pattern"]:
            raise AdapterInputError("pattern must not contain a line break (it is matched within one line)")

    def _perform(self, params):
        rel, full = self._rel(params["path"])
        if not full.exists():
            raise AdapterFailure("path does not exist")
        matches, scanned, truncated = [], 0, False
        files, skipped = _scan(self, full)
        for name, text in files:
            scanned += 1
            for number, line in enumerate(_lines(text), 1):
                if params["pattern"] in line:
                    if len(matches) >= MAX_MATCHES:
                        truncated = True
                        break
                    matches.append({"file": name, "line": number, "text": line.strip()[:300]})
            if truncated:
                break
        return {"path": rel, "pattern": params["pattern"], "files_scanned": scanned, "match_count": len(matches),
                "truncated": truncated, "matches": matches, "files_skipped": skipped}


class SymbolIndexAdapter(_ReadOnlyRooted):
    name = "code.symbols"
    version = "1.1"
    description = "Index Python classes/functions (with qualified names and lines) and called names, via ast."
    params_schema = {"path": str}

    def _perform(self, params):
        rel, full = self._rel(params["path"])
        if not full.exists():
            raise AdapterFailure("path does not exist")
        symbols, calls, errors = [], {}, []
        files, skipped = _scan(self, full, suffix=".py")
        for name, text in files:
            try:
                tree = ast.parse(text, filename=name)
            except SyntaxError as exc:
                errors.append({"file": name, "line": exc.lineno, "error": exc.msg})
                continue
            except (ValueError, RecursionError, MemoryError):
                # CPython reports a too-deep parse as RecursionError or MemoryError; the
                # file is bounded (MAX_FILE_BYTES), so this is the file, not the process.
                errors.append({"file": name, "line": None, "error": "too deeply nested to parse"})
                continue
            # Pre-order walk without recursion: a file that parses can still be deeper than
            # Python's own recursion limit.
            stack = [(child, "") for child in reversed(list(ast.iter_child_nodes(tree)))]
            while stack:
                node, prefix = stack.pop()
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    qual = f"{prefix}{node.name}"
                    kind = "class" if isinstance(node, ast.ClassDef) else "function"
                    symbols.append({"file": name, "name": node.name, "qualname": qual, "kind": kind,
                                    "line": node.lineno})
                    prefix = qual + "."
                stack.extend((child, prefix) for child in reversed(list(ast.iter_child_nodes(node))))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                    if called:
                        calls[called] = calls.get(called, 0) + 1
        return {"path": rel, "symbol_count": len(symbols), "symbols": symbols,
                "top_calls": sorted(calls.items(), key=lambda kv: (-kv[1], kv[0]))[:50], "syntax_errors": errors,
                "files_skipped": skipped}


class CodeDiffAdapter(_ReadOnlyRooted):
    name = "code.diff"
    version = "1.1"
    description = "Unified diff of a file under the root against provided text (the file is only read)."
    params_schema = {"path": str, "against": str}

    def _perform(self, params):
        rel, full = self._rel(params["path"])
        current = _read_text(full) if full.is_file() else None
        if current is None:
            raise AdapterFailure("path is not a readable UTF-8 file")
        against = params["against"]
        # Lines keep their terminators, so a missing final newline or other line endings
        # show as changed lines; `identical` is exact text equality, never "same lines".
        diff = list(difflib.unified_diff(_LINE_KEEPENDS.findall(against), _LINE_KEEPENDS.findall(current),
                                         fromfile="against", tofile=rel, lineterm=""))
        body = diff[2:]
        added = sum(1 for d in body if d.startswith("+"))
        removed = sum(1 for d in body if d.startswith("-"))
        return {"path": rel, "identical": current == against, "added": added, "removed": removed,
                "diff": diff[:MAX_DIFF_LINES], "truncated": len(diff) > MAX_DIFF_LINES}

    def verify(self, params, observed):
        return observed["identical"] == (observed["added"] == observed["removed"] == 0)


_RAN = re.compile(r"^Ran (\d+) tests? in [^\n]*\n", re.M)
_RESULT = re.compile(r"\s*(?:OK|NO TESTS RAN|FAILED \(([^)\n]*)\))[^\n]*$", re.M)
TAIL_BYTES = 65536          # per stream; the run's output is hashed in full, never held in full


def _summary(stderr_text):
    """unittest's own summary: the LAST "Ran N tests" line and the result line right after it.

    Text a test prints (on either stream, before the summary) can look like a summary line;
    only the runner's final one counts. Returns (tests_run, counts) or (None, {}).
    """
    last = None
    for last in _RAN.finditer(stderr_text):
        pass
    if last is None:
        return None, {}
    result = _RESULT.match(stderr_text, last.end())
    if result is None:
        return None, {}
    counts = dict(re.findall(r"(\w+)=(\d+)", result.group(1) or ""))
    return int(last.group(1)), counts


def _run_streamed(argv, *, cwd, env, timeout_s):
    """Run argv in its own process group; return (returncode, {stream: (sha256, bytes, tail)}).

    Output is read as it arrives: hashed in full, only the last TAIL_BYTES of each stream
    kept, so a flooding test costs time, not memory. stdin is /dev/null. When the main
    process exits, what it wrote is drained and every process it left in its group is
    killed, so a background child neither holds the run open nor outlives it; on the
    deadline the whole group is killed and TimeoutError is raised.
    """
    deadline = time.monotonic() + timeout_s
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            cwd=cwd, env=env, start_new_session=True)
    state = {"stdout": [hashlib.sha256(), 0, bytearray()], "stderr": [hashlib.sha256(), 0, bytearray()]}
    timed_out, exited_at = False, None
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ, state["stdout"])
            selector.register(proc.stderr, selectors.EVENT_READ, state["stderr"])
            while selector.get_map():
                now = time.monotonic()
                if now >= deadline:
                    timed_out = True
                    break
                if exited_at is None and proc.poll() is not None:
                    exited_at = now
                if exited_at is not None and now - exited_at > 1.0:
                    break                       # a left-behind child keeps writing: stop reading
                wait = 0 if exited_at is not None else min(0.2, deadline - now)
                events = selector.select(wait)
                if not events and exited_at is not None:
                    break                       # main exited and its output is drained
                for key, _ in events:
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    digest, _count, tail = key.data
                    digest.update(chunk)
                    key.data[1] += len(chunk)
                    tail += chunk
                    del tail[:-TAIL_BYTES]
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        proc.wait()
        proc.stdout.close()
        proc.stderr.close()
    if timed_out:
        raise TimeoutError("test run exceeded its time limit")
    return proc.returncode, {name: (d.hexdigest(), n, bytes(t)) for name, (d, n, t) in state.items()}


class TestRunAdapter(_RootedFileAdapter):
    name = "test.run"
    version = "1.1"
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
        returncode, streams = _run_streamed(
            [sys.executable, "-m", "unittest", "discover", "-s", str(full), "-t", str(full)],
            cwd=str(full), env=env, timeout_s=max(self.timeout_s - 5, 1))
        # Bytes that are not UTF-8 are shown replaced; they never decide the outcome, which is
        # the exit code and unittest's own summary (ASCII) on stderr.
        err_text = streams["stderr"][2].decode("utf-8", errors="replace")
        out_text = streams["stdout"][2].decode("utf-8", errors="replace")
        tests_run, counts = _summary(err_text)
        return {"path": rel, "exit_code": returncode, "tests_run": tests_run,
                "failures": int(counts.get("failures", 0)), "errors": int(counts.get("errors", 0)),
                "ok": returncode == 0 and tests_run is not None,
                "stdout_sha256": streams["stdout"][0], "stdout_bytes": streams["stdout"][1],
                "stderr_sha256": streams["stderr"][0], "stderr_bytes": streams["stderr"][1],
                "output_tail": (err_text + out_text)[-4000:]}

    def verify(self, params, observed):
        return observed.get("tests_run") is not None       # the run completed and reported

    def reconcile(self, intent):
        return "UNKNOWN"     # a test run's side effects cannot be inspected afterwards


_TEXT_CODECS = {"utf-8": "utf-8", "utf8": "utf-8", "us-ascii": "ascii", "ascii": "ascii"}


def _media_type(ctype):
    """`type/subtype` and charset of a Content-Type value, lower-cased (RFC 9110: case-insensitive)."""
    main, _, rest = ctype.partition(";")
    charset = None
    for param in rest.split(";"):
        name, eq, value = param.partition("=")
        if eq and name.strip().lower() == "charset":
            charset = value.strip().strip('"').strip().lower()
    return main.strip().lower(), charset


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # Returning None makes urllib raise HTTPError for the 3xx instead of requesting Location.
    def redirect_request(self, *args, **kwargs):
        return None


_URL_OPENER = urllib.request.build_opener(_NoRedirect())


class UrlReadAdapter(ToolAdapter):
    name = "url.read"
    version = "1.1"
    action = "READ"
    idempotent = True
    risk = "LOW"
    timeout_s = 20
    description = "HTTP(S) GET of one URL; the whole body (at most 2 MB) or a known failure; UTF-8 text returned exactly."
    params_schema = {"url": str}
    ledger_exclude = {"text"}
    MAX_BYTES = 2_000_000

    def _canonical(self, raw):
        try:
            parts = urllib.parse.urlsplit(raw)
        except ValueError:
            raise AdapterInputError("url is invalid") from None
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise AdapterInputError("url must be absolute http(s)")
        if parts.username or parts.password:
            raise AdapterInputError("credentials in URLs are not allowed")
        if any(urllib.parse.unquote(seg) in (".", "..") for seg in parts.path.split("/")):
            # Scope is a prefix test; a dot segment would name a path outside the prefix.
            raise AdapterInputError("url path must not contain dot segments")
        try:
            port = parts.port
        except ValueError:
            raise AdapterInputError("url port is invalid") from None
        netloc = parts.hostname.lower() + (f":{port}" if port else "")
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
        request = urllib.request.Request(url, headers={"User-Agent": "HG-url.read/1.1"})
        # Everything (connect, every read, the whole body) ends before the gateway's timeout,
        # so a slow or dripping server is a known failure and no read outlives the action.
        budget = max(self.timeout_s - 2, 0.5)
        per_read = min(5.0, budget / 2)
        deadline = time.monotonic() + budget - per_read
        try:
            # Only the URL the gateway authorized and scope-checked is read (WS-04).
            with _URL_OPENER.open(request, timeout=per_read) as response:
                status, ctype = response.status, response.headers.get("Content-Type", "")
                chunks, size = [], 0
                while True:
                    if time.monotonic() > deadline:
                        raise AdapterFailure(f"response not complete within {budget:g} s")
                    chunk = response.read1(65536)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > self.MAX_BYTES:
                        raise AdapterFailure(f"response is larger than {self.MAX_BYTES} bytes")
                    chunks.append(chunk)
                if response.length:     # Content-Length promised more than the server sent
                    raise AdapterFailure("response body is shorter than its Content-Length")
        except urllib.error.HTTPError as exc:
            raise AdapterFailure(f"HTTP {exc.code}")
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            raise AdapterFailure(f"cannot read {url}: {getattr(exc, 'reason', None) or type(exc).__name__}")
        data = b"".join(chunks)
        mtype, charset = _media_type(ctype)
        text = None
        if mtype.startswith("text/") or "json" in mtype or "xml" in mtype:
            # The text is the exact reading of the bytes under `sha256`, or there is no result.
            codec = _TEXT_CODECS.get(charset or "utf-8")
            if codec is None:
                raise AdapterFailure(f"response charset {charset!r} is not UTF-8")
            try:
                text = data.decode(codec)
            except UnicodeDecodeError as exc:
                raise AdapterFailure(f"response is not {codec} text (byte {exc.start})") from None
        return {"url": url, "status": status, "content_type": ctype, "bytes": len(data), "truncated": False,
                "sha256": hashlib.sha256(data).hexdigest(), "text": text}

    def verify(self, params, observed):
        if observed.get("status") != 200:
            return False
        text = observed.get("text")
        if text is None:
            return True
        raw = text.encode("utf-8")
        return len(raw) == observed.get("bytes") and hashlib.sha256(raw).hexdigest() == observed.get("sha256")

    def reconcile(self, intent):
        return "APPLIED"

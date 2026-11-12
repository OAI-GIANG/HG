"""Prove a release can read the owner's assistant home before the `hg` command or chat uses it.

Usage:
  python3 -I -B assistant_precheck.py <release_root> [<home>]

<home> defaults to the release's own default_home() ($HG_HOME, else ~/.local/share/hg/assistant),
which is what the `hg` shim and `hg serve` chat open. The live home is only read: each
config.json and *.jsonl is copied (no symlinks followed) under a shared hold of the home's
existing .lock (never created), into a private temporary home. The release's own readers then
load that copy: repair.inspect() on every ledger (OK only), Notebook.active()/trusted_ids()
and config.load() — the same code `hg note list`, `hg ask` and chat run.

Exit 0: every reader accepts the copy (result OK), or the home does not exist (result ABSENT).
Exit 1: a reader refuses it or the copy cannot be taken; the report names the file and reason.
Exit 2: bad usage. One JSON report on stdout in every case.
"""
import errno
import fcntl
import json
import os
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path

LOCK_WAIT_S = 10.0


class CopyError(Exception):
    pass


def _print(report):
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


def _usage(reason):
    _print({"result": "FAIL", "reason": f"usage: assistant_precheck.py <release_root> [<home>]: {reason}"})
    return 2


def _hold_shared(home):
    """LOCK_SH on the home's existing .lock (read-only open), so no writer is mid-append.

    A home that never had a writer has no .lock; it is not created (the home stays unchanged).
    """
    try:
        fd = os.open(home / ".lock", os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise CopyError(f".lock cannot be opened safely: {exc}") from exc
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise CopyError(".lock is not a regular file")
    deadline = time.monotonic() + LOCK_WAIT_S
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            return fd
        except OSError as exc:
            if exc.errno not in (errno.EWOULDBLOCK, errno.EAGAIN) or time.monotonic() > deadline:
                os.close(fd)
                raise CopyError("another HG process holds the home; try again") from exc
            time.sleep(0.05)


def _read_regular(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
                 | getattr(os, "O_NONBLOCK", 0))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise CopyError("not a regular file")
        chunks = []
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    finally:
        os.close(fd)


def _copy_home(home, copy, checks):
    """Copy config.json and every *.jsonl; a file that cannot be copied safely is a failed check."""
    fd = _hold_shared(home)
    try:
        names = sorted(n for n in os.listdir(home) if n == "config.json" or n.endswith(".jsonl"))
        for name in names:
            try:
                if stat.S_ISLNK(os.lstat(home / name).st_mode):
                    raise CopyError("is a symlink (not followed)")
                data = _read_regular(home / name)
            except (OSError, CopyError) as exc:
                checks.append({"name": "copy", "file": name, "ok": False, "detail": f"cannot copy: {exc}"})
                continue
            target = os.open(copy / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(target, "wb") as stream:
                stream.write(data)
        return [n for n in names if (copy / n).exists()]
    finally:
        if fd is not None:
            os.close(fd)


def main(argv):
    if len(argv) not in (1, 2):
        return _usage("wrong number of arguments")
    release = Path(argv[0])
    if not release.is_absolute() or release.is_symlink() or not (release / "hg" / "__main__.py").is_file():
        return _usage("release_root must be an absolute real release directory")
    if len(argv) == 2 and not Path(argv[1]).is_absolute():
        return _usage("home must be an absolute path")

    sys.path.insert(0, str(release))
    try:
        from hg.assistant.config import load
        from hg.assistant.home import default_home, ensure_home
        from hg.assistant.notes import Notebook
        from hg.assistant.repair import inspect
    except Exception as exc:
        _print({"result": "FAIL", "release": str(release), "reason": f"import: {type(exc).__name__}: {exc}"})
        return 1

    home = Path(argv[1]) if len(argv) == 2 else Path(default_home())
    report = {"release": str(release), "home": str(home), "checks": []}
    checks = report["checks"]
    if not os.path.lexists(home):
        report["result"] = "ABSENT"
        _print(report)
        return 0

    def check(name, file, fn):
        try:
            checks.append({"name": name, "file": file, "ok": True, "detail": fn()})
        except Exception as exc:
            checks.append({"name": name, "file": file, "ok": False, "detail": f"{type(exc).__name__}: {exc}"})

    check("home", ".", lambda: str(ensure_home(home, create=False)))
    if checks[-1]["ok"]:
        tmp = Path(tempfile.mkdtemp(prefix="hg-assistant-precheck-"))
        try:
            copy = tmp / "home"
            copy.mkdir(mode=0o700)
            try:
                copied = _copy_home(home, copy, checks)
            except (OSError, CopyError) as exc:
                checks.append({"name": "copy", "file": ".", "ok": False, "detail": str(exc)})
                copied = None
            if copied is not None:
                for name in copied:
                    if name.endswith(".jsonl"):
                        def ledger(name=name):
                            result = inspect(copy / name)
                            if result.get("status") != "OK":
                                hint = " — run `hg repair` (it keeps a backup) and precheck again" \
                                    if result.get("status") == "TORN_LAST_LINE" else ""
                                raise ValueError(f"{result.get('status')}: {result.get('reason')}{hint}")
                            return result
                        check("ledger", name, ledger)

                def notes():
                    book = Notebook(copy)
                    return {"active": len(book.active()), "trusted": len(book.trusted_ids())}

                check("notes", "notes.jsonl", notes)
                check("config", "config.json",
                      lambda: {"file": "config.json" in copied, "model": load(copy)["model"]})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    report["result"] = "OK" if all(c["ok"] for c in checks) else "FAIL"
    _print(report)
    return 0 if report["result"] == "OK" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

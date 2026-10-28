"""`hg repair`: recover a ledger whose LAST line was cut off (for example the process was killed
by Android's memory manager in the middle of an append).

Only that one case is repaired automatically, because only then is the intent unambiguous:
every earlier line is a complete, valid event and the last one is not. The file is first
copied to `<name>.bak-<UTC timestamp>` (mode 0600), then rewritten without the broken line,
then loaded again to prove it is consistent. Any other damage is reported and left alone for
the owner to inspect; HG never guesses which of several bad lines to drop.
"""
import json
import os
import shutil
from datetime import datetime, timezone

from maep.core import MAEPError
from hg.assistant.home import locked
from hg.verification.evidence import EventLog


def _valid(line):
    try:
        event = json.loads(line)
    except ValueError:
        return False
    return isinstance(event, dict) and isinstance(event.get("event_id"), str) and bool(event["event_id"])


def inspect(path):
    """Return {"status": OK|TORN_LAST_LINE|DAMAGED, ...} without changing anything."""
    try:
        EventLog(path)
        return {"file": path.name, "status": "OK"}
    except MAEPError as exc:
        reason = str(exc)
    raw = path.read_bytes()
    lines = raw.split(b"\n")
    if lines and lines[-1] == b"":
        lines = lines[:-1]
    bad = [i for i, line in enumerate(lines) if not _valid(line.decode("utf-8", errors="replace"))]
    if bad == [len(lines) - 1]:
        return {"file": path.name, "status": "TORN_LAST_LINE", "reason": reason, "line": len(lines),
                "bytes_removed": len(lines[-1]) + (1 if raw.endswith(b"\n") else 0)}
    return {"file": path.name, "status": "DAMAGED", "reason": reason, "bad_lines": [i + 1 for i in bad][:10]}


def repair(home, *, clock=None, apply=True):
    clock = clock or (lambda: datetime.now(timezone.utc))
    results = []
    with locked(home, exclusive=True):
        for path in sorted(home.glob("*.jsonl")):
            report = inspect(path)
            if report["status"] == "TORN_LAST_LINE" and apply:
                backup = path.with_name(f"{path.name}.bak-{clock():%Y%m%dT%H%M%SZ}")
                shutil.copy2(path, backup)
                os.chmod(backup, 0o600)
                raw = path.read_bytes()
                keep = raw[:len(raw) - report["bytes_removed"]]
                tmp = path.with_name(path.name + ".tmp")
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
                try:
                    os.write(fd, keep)
                    os.fsync(fd)
                finally:
                    os.close(fd)
                os.replace(tmp, path)
                EventLog(path)          # must load cleanly now, or the exception reaches the owner
                report.update(status="REPAIRED", backup=backup.name)
            results.append(report)
    return results

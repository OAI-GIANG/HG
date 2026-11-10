"""`hg repair`: recover a ledger whose LAST line was cut off (for example the process was killed
by Android's memory manager in the middle of an append).

Only that one case is repaired automatically, because only then is the intent unambiguous:
an interrupted append leaves a final record without its "\\n" terminator (C1), and every
earlier record is complete and loads under the ledger rules. A complete (terminated) bad last
line is damage, not a torn write, and is left alone.

The file is opened the way the ledger reader opens it (no symlink, no waiting on a FIFO, an
owner-owned regular file no other user can write); anything else is reported and never
rewritten, so `repair` cannot adopt a file from outside the home or launder one another user
could have written. The bytes that were inspected are the bytes that are backed up and
rewritten: the backup `<name>.bak-<UTC timestamp>` (mode 0600, never overwrites) is written
first, the kept prefix is validated before the rewrite, and the result is loaded again to
prove it is consistent. Any other damage is reported and left alone for the owner to inspect;
HG never guesses which of several bad lines to drop.
"""
import json
import os
import stat
from datetime import datetime, timezone

from maep import ledger
from maep.core import MAEPError
from hg.assistant.home import locked
from hg.memory.locking import outcome_file_lock
from hg.verification.evidence import EventLog


def _valid(line):
    try:
        event = json.loads(line)
    except ValueError:
        return False
    return isinstance(event, dict) and isinstance(event.get("event_id"), str) and bool(event["event_id"])


def _read_safely(path):
    """Return the file's bytes, or raise MAEPError if the ledger reader would refuse the file itself."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | os.O_NONBLOCK
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise MAEPError("cannot safely open ledger (symlink or unreadable)") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o022:
            raise MAEPError("ledger must be an owner-owned regular file that no other user can write")
        os.set_blocking(fd, True)
        chunks = []
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    finally:
        os.close(fd)


def _check_prefix(data):
    """Apply the ledger and EventLog read rules to complete records (data ends with "\\n" or is empty)."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MAEPError("invalid ledger encoding (not UTF-8)") from exc
    events, seen = [], set()
    for number, line in enumerate(text.split("\n")[:-1], 1):
        ledger._check_line(line + "\n", number, events, seen)
    for event in events:
        if not isinstance(event.get("kind"), str) or not isinstance(event.get("seq"), int):
            raise MAEPError(f"ledger event {event['event_id']} lacks kind/seq")
    if [e["seq"] for e in events] != list(range(1, len(events) + 1)):
        raise MAEPError("ledger sequence numbers are not contiguous")


def _inspect(path):
    """Return (report, raw bytes or None, kept prefix or None) without changing anything."""
    try:
        raw = _read_safely(path)
    except MAEPError as exc:
        return {"file": path.name, "status": "DAMAGED", "reason": str(exc), "bad_lines": []}, None, None
    try:
        EventLog(path, read_only=True)
        return {"file": path.name, "status": "OK"}, raw, None
    except MAEPError as exc:
        reason = str(exc)
    lines = raw.split(b"\n")
    if lines and lines[-1] == b"":
        lines = lines[:-1]
    if raw and not raw.endswith(b"\n"):
        keep = raw[:raw.rfind(b"\n") + 1]
        try:
            _check_prefix(keep)
        except MAEPError as exc:
            reason = f"{reason}; records before the torn tail are damaged too: {exc}"
        else:
            return ({"file": path.name, "status": "TORN_LAST_LINE", "reason": reason, "line": len(lines),
                     "bytes_removed": len(raw) - len(keep)}, raw, keep)
    bad = [i for i, line in enumerate(lines) if not _valid(line.decode("utf-8", errors="replace"))]
    return {"file": path.name, "status": "DAMAGED", "reason": reason, "bad_lines": [i + 1 for i in bad][:10]}, raw, None


def inspect(path):
    """Return {"status": OK|TORN_LAST_LINE|DAMAGED, ...} without changing anything."""
    return _inspect(path)[0]


def _write_new(path, data, *, exclusive):
    flags = os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | (os.O_EXCL if exclusive else os.O_TRUNC)
    fd = os.open(path, flags, 0o600)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)


def repair(home, *, clock=None, apply=True):
    clock = clock or (lambda: datetime.now(timezone.utc))
    results = []
    with locked(home, exclusive=True):
        for path in sorted(home.glob("*.jsonl")):
            # Inspect first: a directory, FIFO, symlink, or otherwise refused ledger
            # must not acquire a sidecar file as a side effect of being refused.
            report, raw, keep = _inspect(path)
            if report["status"] == "TORN_LAST_LINE" and apply:
                # MemoryStore direct writers share this lock; re-read after acquisition
                # so the repair decision is based on bytes protected by the same lock.
                with outcome_file_lock(path):
                    report, raw, keep = _inspect(path)
                    if report["status"] == "TORN_LAST_LINE":
                        backup = path.with_name(f"{path.name}.bak-{clock():%Y%m%dT%H%M%SZ}")
                        _write_new(backup, raw, exclusive=True)
                        tmp = path.with_name(path.name + ".tmp")
                        _write_new(tmp, keep, exclusive=False)
                        os.replace(tmp, path)
                        EventLog(path)  # must load cleanly now, or the exception reaches the owner
                        report.update(status="REPAIRED", backup=backup.name)
            results.append(report)
    return results

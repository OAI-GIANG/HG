"""Single-writer append-only JSONL evidence/event ledger.

This protects against accidental overwrite through this API; it is not tamper-proof
against a process/user with filesystem write access. Use one authorized writer.
"""
import json
import os
from pathlib import Path
from .core import MAEPError


def read_events(path):
    path = Path(path)
    if not path.exists():
        return []
    events = []
    seen = set()
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                raise MAEPError(f"blank ledger line at {line_number}")
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise MAEPError(f"invalid ledger JSON at line {line_number}") from exc
            if not isinstance(event, dict) or not isinstance(event.get("event_id"), str) or not event["event_id"]:
                raise MAEPError(f"invalid event record at line {line_number}")
            if event["event_id"] in seen:
                raise MAEPError(f"duplicate event_id at line {line_number}")
            seen.add(event["event_id"])
            events.append(event)
    return events


def append_event(path, event):
    """Append one unique event and fsync it; assumes one authorized writer."""
    if not isinstance(event, dict) or not isinstance(event.get("event_id"), str) or not event["event_id"]:
        raise MAEPError("event must have a non-empty event_id")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    current = read_events(path)
    if any(existing["event_id"] == event["event_id"] for existing in current):
        raise MAEPError("event_id already exists; append an amendment with a new ID")
    payload = (json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short append write")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    return event["event_id"]

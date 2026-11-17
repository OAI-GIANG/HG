"""Restart forensics for `hg serve` (RF-1): a bounded liveness heartbeat and one record per start.

Android/ColorOS can kill Termux's whole process tree, freeze it, suspend the CPU or reboot the phone.
None of that reaches HG: the process simply stops running. Before RF-1 the only trace was the next
start line in the runit log, so soak 3 (2026-11-15..17) lost 23.8 h and 31.5 h of production with no
HG record at all; the gaps were found only in another program's log. This module makes such gaps
observable without guessing their cause:

- While serving, a daemon thread rewrites <state_dir>/liveness.json every interval (atomic replace)
  with the wall clock, CLOCK_BOOTTIME, CLOCK_MONOTONIC, boot_id, pid and release id.
- A beat that comes later than STALL_FACTOR intervals is a stall. The part of the delay in which
  CLOCK_BOOTTIME advanced but CLOCK_MONOTONIC did not is device suspend (measured by the kernel);
  the rest is time the device was awake but this process did not run (frozen or starved -- a
  suspicion, not a measurement). Totals stay in the heartbeat; long stalls also get a record.
- At start, the previous heartbeat is classified once and appended to restart-forensics.jsonl
  (bounded, one rotation):
    CLEAN_STOP / ERROR_EXIT   CONFIRMED  the stop path ran and wrote the reason
    DEVICE_REBOOT             CONFIRMED  boot_id changed; how the old process ended is unknown
    UNCLEAN_END_SAME_BOOT     SUSPECTED  same boot, no stop path: Android kill, SIGKILL or OOM
    FIRST_START, PREVIOUS_UNREADABLE, UNCLEAN_END_UNKNOWN_BOOT   UNKNOWN
  The downtime of an unclean end is bounded, not measured: the process died after its last beat.

Observability only: nothing here grants, blocks or retries any action, a failed write is reported
once on stderr and never stops the service, and no token, request or note content is written.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

SCHEMA = "hg.liveness.v1"
HEARTBEAT_FILE = "liveness.json"
RECORDS_FILE = "restart-forensics.jsonl"
DEFAULT_INTERVAL_S = 60.0
STALL_FACTOR = 3
STALL_RECORD_S = 600.0
MAX_RECORDS_BYTES = 64 * 1024
MAX_HEARTBEAT_BYTES = 16 * 1024
BOOT_ID_PATH = "/proc/sys/kernel/random/boot_id"


def read_clocks():
    """Wall clock, CLOCK_BOOTTIME (counts suspend; None if unavailable) and CLOCK_MONOTONIC."""
    boot = None
    if hasattr(time, "CLOCK_BOOTTIME"):
        try:
            boot = time.clock_gettime(time.CLOCK_BOOTTIME)
        except OSError:
            boot = None
    return {"wall": time.time(), "boottime": boot, "monotonic": time.monotonic()}


def read_boot_id(path=BOOT_ID_PATH):
    try:
        value = Path(path).read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        return None
    return value if 0 < len(value) <= 64 else None


def _num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _round(value):
    return None if value is None else round(float(value), 1)


def read_heartbeat(state_dir):
    """-> (doc, None) | (None, "missing") | (None, "unreadable")."""
    path = Path(state_dir) / HEARTBEAT_FILE
    try:
        st = os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        return None, "missing"
    except OSError:
        return None, "unreadable"
    try:
        if not os.path.isfile(path) or os.path.islink(path) or st.st_size > MAX_HEARTBEAT_BYTES:
            return None, "unreadable"
        doc = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None, "unreadable"
    if (not isinstance(doc, dict) or doc.get("schema") != SCHEMA
            or not _num(doc.get("last_alive")) or not _num(doc.get("started"))):
        return None, "unreadable"
    return doc, None


def classify(prev, problem, now, boot_id):
    """Classify how the previous run ended. Pure: `now` is read_clocks() output."""
    out = {"class": None, "evidence": "UNKNOWN"}
    if prev is None:
        out["class"] = "FIRST_START" if problem == "missing" else "PREVIOUS_UNREADABLE"
        return out
    last = prev["last_alive"]
    out.update({
        "release_id": prev.get("release_id"), "pid": prev.get("pid"), "boot_id": prev.get("boot_id"),
        "started": prev["started"], "last_alive": last, "uptime_s": _round(last - prev["started"]),
        "beats": prev.get("beats"), "stalls": prev.get("stalls"),
        "suspended_total_s": prev.get("suspended_total_s"),
        "stalled_awake_total_s": prev.get("stalled_awake_total_s"),
    })
    gap = now["wall"] - last
    if gap < 0:
        out["clock_inconsistent"] = True
        gap = None
    stopped = prev.get("stopped")
    if isinstance(stopped, dict) and stopped.get("reason") in {"signal", "returned", "error"}:
        out["class"] = "ERROR_EXIT" if stopped["reason"] == "error" else "CLEAN_STOP"
        out["evidence"] = "CONFIRMED"
        out["stopped_reason"] = stopped["reason"]
        out["downtime_s"] = _round(gap)
        return out
    out["downtime_max_s"] = _round(gap)
    prev_boot = prev.get("boot_id")
    if not prev_boot or not boot_id:
        out["class"] = "UNCLEAN_END_UNKNOWN_BOOT"
        return out
    if prev_boot != boot_id:
        out["class"] = "DEVICE_REBOOT"
        out["evidence"] = "CONFIRMED"
        return out
    out["class"] = "UNCLEAN_END_SAME_BOOT"
    out["evidence"] = "SUSPECTED"
    interval = prev.get("interval_s")
    if gap is not None and _num(interval):
        out["downtime_min_s"] = _round(max(0.0, gap - interval))
    if all(_num(x) for x in (prev.get("boottime"), prev.get("monotonic"), now["boottime"], now["monotonic"])):
        out["suspended_s"] = _round(max(0.0, (now["boottime"] - now["monotonic"])
                                        - (prev["boottime"] - prev["monotonic"])))
    return out


def format_start(record):
    p = record["previous"]
    parts = [f"previous={p['class']}", f"evidence={p['evidence']}"]
    for key in ("downtime_s", "downtime_max_s", "downtime_min_s", "suspended_s", "uptime_s", "stopped_reason"):
        if p.get(key) is not None:
            parts.append(f"{key}={p[key]}")
    if p.get("release_id"):
        parts.append(f"previous_release={str(p['release_id'])[:12]}")
    if record.get("since_boot_s") is not None:
        parts.append(f"since_boot_s={record['since_boot_s']}")
    return " ".join(parts)


class Liveness:
    """Heartbeat writer for one serving process. Thread-safe; never raises after construction."""

    def __init__(self, state_dir, *, release_id, interval=None, clock=read_clocks,
                 boot_id_reader=read_boot_id, stderr=None):
        self.state_dir = Path(state_dir)
        self.release_id = release_id
        self.interval = float(DEFAULT_INTERVAL_S if interval is None else interval)
        if self.interval <= 0:
            raise ValueError("interval must be positive")
        self._clock = clock
        self._boot_id = boot_id_reader()
        self._stderr = stderr
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._reported = set()
        self._started = None
        self._last = None
        self.beats = 0
        self.stalls = 0
        self.suspended_total = 0.0
        self.stalled_awake_total = 0.0
        self.stopped = False

    # ---------------------------------------------------------------- files
    def _report(self, what):
        if what in self._reported:
            return
        self._reported.add(what)
        print(f"HG_LIVENESS_WRITE_FAILED {what}", file=self._stderr or sys.stderr, flush=True)

    def _append(self, record):
        path = self.state_dir / RECORDS_FILE
        line = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            try:
                size = os.stat(path, follow_symlinks=False).st_size
            except FileNotFoundError:
                size = 0
            if size and size + len(line) > MAX_RECORDS_BYTES:
                os.replace(path, self.state_dir / (RECORDS_FILE + ".1"))
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
            try:
                os.write(fd, line)
                os.fsync(fd)
            finally:
                os.close(fd)
            return True
        except OSError:
            self._report("records")
            return False

    def _write_heartbeat(self, doc, *, durable=False):
        path = self.state_dir / HEARTBEAT_FILE
        tmp = self.state_dir / (HEARTBEAT_FILE + ".tmp")
        data = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
        try:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                view = memoryview(data)
                while view:
                    view = view[os.write(fd, view):]
                if durable:
                    os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(tmp, path)
            return True
        except OSError:
            self._report("heartbeat")
            return False

    def _doc(self, clocks, stopped=None):
        return {
            "schema": SCHEMA, "pid": os.getpid(), "release_id": self.release_id, "boot_id": self._boot_id,
            "interval_s": self.interval, "started": self._started, "last_alive": clocks["wall"],
            "boottime": clocks["boottime"], "monotonic": clocks["monotonic"], "beats": self.beats,
            "stalls": self.stalls, "suspended_total_s": _round(self.suspended_total),
            "stalled_awake_total_s": _round(self.stalled_awake_total), "stopped": stopped,
        }

    # ---------------------------------------------------------------- lifecycle
    def start(self):
        """Classify the previous run, append the START record, write the first heartbeat."""
        prev, problem = read_heartbeat(self.state_dir)
        now = self._clock()
        with self._lock:
            self._started = now["wall"]
            self._last = now
            record = {
                "schema": SCHEMA, "event": "START", "time": now["wall"], "pid": os.getpid(),
                "release_id": self.release_id, "boot_id": self._boot_id,
                "since_boot_s": _round(now["boottime"]),
                "previous": classify(prev, problem, now, self._boot_id),
            }
            self._append(record)
            self._write_heartbeat(self._doc(now), durable=True)
        return record

    def beat(self):
        now = self._clock()
        with self._lock:
            if self.stopped:
                return False
            last = self._last
            if last is not None:
                d_mono = now["monotonic"] - last["monotonic"]
                d_boot = None
                if _num(now["boottime"]) and _num(last["boottime"]):
                    d_boot = now["boottime"] - last["boottime"]
                elapsed = d_boot if d_boot is not None else d_mono
                if elapsed > STALL_FACTOR * self.interval:
                    suspended = max(0.0, d_boot - d_mono) if d_boot is not None else None
                    awake = max(0.0, d_mono - self.interval)
                    self.stalls += 1
                    self.suspended_total += suspended or 0.0
                    self.stalled_awake_total += awake
                    if elapsed >= STALL_RECORD_S:
                        self._append({
                            "schema": SCHEMA, "event": "STALL", "time": now["wall"], "pid": os.getpid(),
                            "release_id": self.release_id, "boot_id": self._boot_id,
                            "since": last["wall"], "elapsed_s": _round(elapsed),
                            "suspended_s": _round(suspended), "stalled_awake_s": _round(awake),
                        })
            self._last = now
            self.beats += 1
            return self._write_heartbeat(self._doc(now))

    def _loop(self):
        while not self._stop.wait(self.interval):
            self.beat()

    def start_thread(self):
        self._thread = threading.Thread(target=self._loop, name="hg-liveness", daemon=True)
        self._thread.start()

    def stop(self, reason):
        """Record a deliberate end ("signal", "returned" or "error"). Idempotent."""
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)
        now = self._clock()
        with self._lock:
            if self.stopped:
                return False
            self.stopped = True
            return self._write_heartbeat(self._doc(now, stopped={"reason": reason, "time": now["wall"]}),
                                         durable=True)


def _read_records(state_dir):
    rows = []
    for name in (RECORDS_FILE + ".1", RECORDS_FILE):
        try:
            raw = (Path(state_dir) / name).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for line in raw.splitlines():
            try:
                doc = json.loads(line)
            except ValueError:
                continue
            if isinstance(doc, dict) and doc.get("schema") == SCHEMA and _num(doc.get("time")):
                rows.append(doc)
    return rows


def summarize(state_dir, *, now=None, since=None):
    """Availability report from the records and the current heartbeat (read-only).

    unobserved_s counts every gap the service did not record itself (unclean ends, reboots, unknown
    starts are counted from the previous last beat; FIRST_START has no lower bound and is not
    counted). It is an upper bound of downtime, never evidence of uptime.
    """
    now = time.time() if now is None else now
    starts, stalls, by_class = [], [], {}
    unobserved = intentional = 0.0
    for rec in _read_records(state_dir):
        if since is not None and rec["time"] < since:
            continue
        if rec.get("event") == "STALL":
            stalls.append({k: rec.get(k) for k in ("time", "elapsed_s", "suspended_s", "stalled_awake_s")})
            continue
        if rec.get("event") != "START":
            continue
        p = rec.get("previous") or {}
        by_class[p.get("class")] = by_class.get(p.get("class"), 0) + 1
        if p.get("class") == "CLEAN_STOP" and _num(p.get("downtime_s")):
            intentional += p["downtime_s"]
        elif _num(p.get("downtime_max_s")):
            unobserved += p["downtime_max_s"]
        starts.append({"time": rec["time"], "release_id": rec.get("release_id"),
                       "since_boot_s": rec.get("since_boot_s"),
                       **{k: p.get(k) for k in ("class", "evidence", "downtime_s", "downtime_max_s",
                                                "downtime_min_s", "suspended_s", "uptime_s")}})
    hb, problem = read_heartbeat(state_dir)
    current = {"heartbeat": problem or "present"}
    if hb is not None:
        age = now - hb["last_alive"]
        stale = age > STALL_FACTOR * float(hb.get("interval_s") or DEFAULT_INTERVAL_S)
        current.update({
            "release_id": hb.get("release_id"), "pid": hb.get("pid"), "started": hb["started"],
            "last_alive": hb["last_alive"], "age_s": _round(age), "beats": hb.get("beats"),
            "stalls": hb.get("stalls"), "suspended_total_s": hb.get("suspended_total_s"),
            "stalled_awake_total_s": hb.get("stalled_awake_total_s"),
            "state": ("STOPPED" if hb.get("stopped") else "STALE" if stale else "ALIVE"),
        })
    return {"schema": SCHEMA, "starts": len(starts), "by_class": by_class,
            "unobserved_s": _round(unobserved), "intentional_down_s": _round(intentional),
            "stall_records": len(stalls), "current": current,
            "recent_starts": starts[-20:], "recent_stalls": stalls[-20:]}

"""Bounded evidence-window extraction for logs and command output.

This implements the operational goal discussed alongside GTEW-1.0: send a small,
source-linked excerpt to an LLM while preserving the raw evidence separately. The
repository did not contain a GTEW-1.0 specification, so this module does not claim
wire-level or behavioral conformance to that unlocated specification.
"""
from __future__ import annotations

import hashlib
import re


_ERROR = re.compile(
    r"(?:\bERROR\b|\bFATAL\b|\bCRITICAL\b|\bEXCEPTION\b|"
    r"\b[A-Za-z_][A-Za-z0-9_]*(?:Error|Exception)\b|"
    r"Traceback \(most recent call last\)|\bFAILED\b|\bPANIC\b)",
    re.IGNORECASE,
)
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_LINE_BREAK = re.compile(r"\r\n|\r|\n")


class EvidenceWindowError(ValueError):
    pass


def source_lines(text):
    """Lines as editors, `less -N` and `grep -n` number them: only LF, CRLF and CR end a line.
    (str.splitlines also splits on VT, FF, FS/GS/RS, NEL, U+2028/U+2029, which would shift
    every later [L#] anchor and line range away from the raw line it names.)"""
    parts = _LINE_BREAK.split(text)
    if parts and parts[-1] == "":
        parts.pop()
    return parts


def extract_log_window(payload, *, max_source_bytes=4 * 1024 * 1024, max_output_bytes=8192,
                       tail_lines=50, context_lines=2, max_matches=8):
    if isinstance(payload, str):
        raw = payload.encode("utf-8", errors="replace")
    elif isinstance(payload, (bytes, bytearray, memoryview)):
        raw = bytes(payload)
    else:
        raise EvidenceWindowError("payload must be text or bytes")
    for name, value, lower, upper in (
        ("max_source_bytes", max_source_bytes, 1, 64 * 1024 * 1024),
        ("max_output_bytes", max_output_bytes, 128, 64 * 1024),
        ("tail_lines", tail_lines, 1, 500),
        ("context_lines", context_lines, 0, 20),
        ("max_matches", max_matches, 1, 50),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
            raise EvidenceWindowError(f"{name} is outside the allowed range")
    if len(raw) > max_source_bytes:
        raise EvidenceWindowError("raw evidence exceeds the extraction input limit")
    text = raw.decode("utf-8", errors="replace")
    lines = source_lines(text)
    if not lines:
        lines = [""]
    matches = [i for i, line in enumerate(lines) if _ERROR.search(line)][:max_matches]
    ranges = []
    for index in matches:
        start, end = max(0, index - context_lines), min(len(lines) - 1, index + context_lines)
        if ranges and start <= ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], end))
        else:
            ranges.append((start, end))
    selection = "error-context"
    if not ranges:
        start = max(0, len(lines) - tail_lines)
        ranges = [(start, len(lines) - 1)]
        selection = "tail-fallback"
    rendered = []
    for start, end in ranges:
        if rendered:
            rendered.append("… [omitted lines] …")
        rendered.extend(f"[L{n + 1}] {_ANSI.sub('', lines[n]).replace(chr(0), '')}" for n in range(start, end + 1))
    excerpt = "\n".join(rendered)
    encoded = excerpt.encode("utf-8")
    truncated = False
    if len(encoded) > max_output_bytes:
        suffix = "\n… [excerpt truncated; consult raw evidence] …".encode("utf-8")
        budget = max(0, max_output_bytes - len(suffix))
        excerpt = encoded[:budget].decode("utf-8", errors="ignore") + suffix.decode("utf-8")
        truncated = True
    return {
        "excerpt": excerpt,
        "selection": selection,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_bytes": len(raw),
        "output_bytes": len(excerpt.encode("utf-8")),
        "line_ranges": [[start + 1, end + 1] for start, end in ranges],
        "matched_error_lines": [i + 1 for i in matches],
        "truncated": truncated,
        "derived_evidence": True,
        "raw_evidence_preserved": True,
        "redaction_required_before_external_or_model_disclosure": True,
    }

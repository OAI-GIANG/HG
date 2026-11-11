"""Bound JSON nesting depth before a recursive parser sees the text.

CPython's json scanner and json.dumps recurse in C once per nesting level. Their guard
assumes a stack a worker thread does not always have: on Termux/Android (Python 3.14) a
20 000-level array kills the process with SIGSEGV on a worker thread, where `hg serve`
parses request bodies and model replies. This scan is iterative (one regex pass, no
recursion), so it is safe on any stack; it skips string literals so brackets inside text
never count. Text that is not valid JSON may be over-counted; it is refused either way.
"""
import re

MAX_JSON_DEPTH = 64

# A JSON string literal (escapes included) or one structural bracket. Strings are matched
# whole so their brackets are skipped; the unrolled form keeps the regex linear.
_TOKEN = re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"|[\[\]{}]', re.DOTALL)
_TOKEN_BYTES = re.compile(rb'"[^"\\]*(?:\\.[^"\\]*)*"|[\[\]{}]', re.DOTALL)


def json_depth_exceeds(text, limit=MAX_JSON_DEPTH):
    """True when `text` (str or bytes) opens more than `limit` nested arrays/objects."""
    if isinstance(text, (bytes, bytearray)):
        tokens, opens = _TOKEN_BYTES, (b"[", b"{")
    else:
        tokens, opens = _TOKEN, ("[", "{")
    depth = 0
    for match in tokens.finditer(text):
        token = match.group()
        if len(token) != 1:
            continue                      # a string literal
        if token in opens:
            depth += 1
            if depth > limit:
                return True
        elif depth:
            depth -= 1
    return False

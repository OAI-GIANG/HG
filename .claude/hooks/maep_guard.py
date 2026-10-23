#!/usr/bin/env python3
"""MAEP agent guard: a Claude Code PreToolUse hook for the HG repository.

Blocks agent tool calls that would destroy history or work without a recovery path,
bypass the pull-request route to `main`, or change the owner's delegation:

- force, mirror, all-branch and prune pushes; direct pushes to `main`; deleting or
  lease-forcing `main` or `recovery/*` (MAEP-015, MAEP-027);
- `git reset --hard` with uncommitted changes and `git clean -f` with files it would
  delete; recursive deletion of `.git`, `/` or the home directory (MAEP-016, 027);
- any write to `maep/spec/MAEP_OWNER_DELEGATION_V1.md` (MAEP-017, delegation condition 3).

Exit 0 allows the call; exit 2 blocks it and shows stderr to the agent. Input that cannot
be evaluated is blocked (MAEP-005).

Limits: this is a best-effort command parser, not a sandbox. It does not see inside
`$(...)`, `eval`, `xargs` or interpreter one-liners, and an agent that edits this file or
`.claude/settings.json` can disable it. Weakening it is a policy change (MAEP-017, 028).
"""
import json
import re
import shlex
import subprocess
import sys
from pathlib import PurePosixPath

DELEGATION_FILE = "maep/spec/MAEP_OWNER_DELEGATION_V1.md"
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
SEPARATORS = {"&&", "||", ";", "|", "&", "(", ")", "|&", ";;"}
REDIRECTS = {">", ">>", ">|", "&>", "&>>"}
PREFIX_COMMANDS = {"sudo", "command", "exec", "nohup", "time", "env", "builtin"}
SHELLS = {"bash", "sh", "zsh", "dash"}
GIT_OPTS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
PUSH_OPTS_WITH_VALUE = {"--repo", "--receive-pack", "--exec", "-o", "--push-option"}
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
RISK_HINT = re.compile(r"\bgit\b|\brm\b|MAEP_OWNER_DELEGATION")


class Blocked(Exception):
    pass


class GitProbe:
    """Reads git facts for the directory a command runs in; None if they cannot be read."""

    def _git(self, path, *args):
        try:
            result = subprocess.run(["git", "-C", path or ".", *args], capture_output=True,
                                    text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout if result.returncode == 0 else None

    def current_branch(self, path):
        out = self._git(path, "symbolic-ref", "--quiet", "--short", "HEAD")
        return out.strip() or None if out is not None else None

    def has_uncommitted_changes(self, path):
        out = self._git(path, "status", "--porcelain", "--untracked-files=no")
        return None if out is None else bool(out.strip())

    def has_untracked_files(self, path, include_ignored=False):
        args = ["status", "--porcelain", "--untracked-files=all"]
        if include_ignored:
            args.append("--ignored")
        out = self._git(path, *args)
        if out is None:
            return None
        return any(line.startswith(("??", "!!")) for line in out.splitlines())


def _strip_heredocs(command):
    """Drop heredoc bodies so file contents are not parsed as commands."""
    lines, out, pending = command.split("\n"), [], []
    for line in lines:
        if pending:
            if line.strip() == pending[0]:
                pending.pop(0)
            continue
        out.append(line)
        pending.extend(match.group(2) for match in HEREDOC.finditer(line))
    return "\n".join(out)


def _segments(command):
    lexer = shlex.shlex(_strip_heredocs(command).replace("\n", " ; "), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    tokens = list(lexer)
    segment = []
    for token in tokens:
        if token in SEPARATORS:
            if segment:
                yield segment
            segment = []
        else:
            segment.append(token)
    if segment:
        yield segment


def _protected(branch):
    return branch == "main" or branch.startswith("recovery/")


def _short_flags(token):
    return set(token[1:]) if token.startswith("-") and not token.startswith("--") and len(token) > 1 else set()


def _check_push(args, path, probe):
    remote_seen, refspecs, delete, lease = False, [], False, False
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in PUSH_OPTS_WITH_VALUE:
            i += 2
            continue
        if arg in ("--force", "--mirror", "--all", "--branches", "--prune") or "f" in _short_flags(arg):
            raise Blocked(f"`git push {arg}` rewrites or deletes remote history; push a new branch instead")
        if arg == "--delete" or "d" in _short_flags(arg):
            delete = True
        elif arg.startswith("--force-with-lease"):
            lease = True
        elif not arg.startswith("-"):
            if remote_seen:
                refspecs.append(arg)
            else:
                remote_seen = True
        i += 1

    destinations = []
    for spec in refspecs:
        if spec.startswith("+"):
            raise Blocked(f"forced refspec `{spec}` rewrites remote history")
        if delete:
            destinations.append((spec, True))
        elif spec.startswith(":"):
            destinations.append((spec[1:], True))
        else:
            destinations.append((spec.split(":", 1)[1] if ":" in spec else spec, False))
    if not destinations:
        destinations.append(("HEAD", False))

    for dst, is_delete in destinations:
        if dst == "HEAD":
            dst = probe.current_branch(path)
            if not dst:
                raise Blocked("cannot determine which branch this push updates; name the branch explicitly")
        if dst.startswith("refs/heads/"):
            dst = dst[len("refs/heads/"):]
        elif dst.startswith("refs/"):
            continue
        if is_delete and _protected(dst):
            raise Blocked(f"deleting protected branch `{dst}` is not allowed")
        if dst == "main":
            raise Blocked("direct pushes to `main` are not allowed; merge through a pull request")
        if lease and _protected(dst):
            raise Blocked(f"force-pushing protected branch `{dst}` is not allowed")


def _check_git(tokens, cwd, probe):
    path, i = cwd, 1
    while i < len(tokens) and tokens[i].startswith("-"):
        if tokens[i] in GIT_OPTS_WITH_VALUE:
            if tokens[i] == "-C" and i + 1 < len(tokens):
                path = tokens[i + 1]
            i += 2
        else:
            i += 1
    if i >= len(tokens):
        return
    sub, args = tokens[i], tokens[i + 1:]
    if sub == "push":
        _check_push(args, path, probe)
    elif sub == "reset" and "--hard" in args:
        dirty = probe.has_uncommitted_changes(path)
        if dirty is not False:
            raise Blocked("`git reset --hard` would discard uncommitted changes; commit or stash them first")
    elif sub == "clean":
        flags = set().union(*(_short_flags(a) for a in args)) if args else set()
        forced = "f" in flags or "--force" in args
        dry_run = "n" in flags or "--dry-run" in args
        if forced and not dry_run:
            include_ignored = "x" in flags or "X" in flags
            if probe.has_untracked_files(path, include_ignored) is not False:
                raise Blocked("`git clean -f` would delete untracked files; move or commit them first")
    if sub in {"rm", "mv", "checkout", "restore", "reset", "apply", "am"} and _mentions_delegation(args):
        raise Blocked(f"only the owner changes {DELEGATION_FILE}")


def _mentions_delegation(tokens):
    return any(t.rstrip("/").endswith(DELEGATION_FILE) for t in tokens)


def _check_rm(args):
    flags = set().union(*(_short_flags(a) for a in args)) if args else set()
    recursive = bool(flags & {"r", "R"}) or "--recursive" in args
    targets = [a for a in args if not a.startswith("-")]
    if recursive:
        for target in targets:
            if target in {"/", "/*", "~", "~/", "$HOME"}:
                raise Blocked(f"recursive deletion of `{target}` is not allowed")
            if PurePosixPath(target.rstrip("/") or "/").name == ".git":
                raise Blocked("deleting a `.git` directory destroys repository history")


def _check_delegation_writes(tokens):
    for index, token in enumerate(tokens):
        if not token.rstrip("/").endswith(DELEGATION_FILE):
            continue
        if index > 0 and tokens[index - 1] in REDIRECTS:
            raise Blocked(f"only the owner changes {DELEGATION_FILE}")
    if not tokens or not _mentions_delegation(tokens):
        return
    name = PurePosixPath(tokens[0]).name
    args = tokens[1:]
    if name in {"rm", "mv", "truncate", "tee", "dd", "shred", "chmod", "chown", "ln", "install"}:
        raise Blocked(f"only the owner changes {DELEGATION_FILE}")
    if name == "cp" and args and args[-1].rstrip("/").endswith(DELEGATION_FILE):
        raise Blocked(f"only the owner changes {DELEGATION_FILE}")
    if name in {"sed", "perl"} and any(a.startswith("-i") or a == "--in-place" for a in args):
        raise Blocked(f"only the owner changes {DELEGATION_FILE}")


def _check_segment(tokens, cwd, probe, depth):
    _check_delegation_writes(tokens)
    while tokens and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]) or tokens[0] in PREFIX_COMMANDS):
        tokens = tokens[1:]
    if not tokens:
        return
    name = PurePosixPath(tokens[0]).name
    if name in SHELLS and "-c" in tokens[1:]:
        position = tokens.index("-c")
        if position + 1 < len(tokens) and depth < 3:
            _check_command(tokens[position + 1], cwd, probe, depth + 1)
    elif name == "git":
        _check_git(tokens, cwd, probe)
    elif name == "rm":
        _check_rm(tokens[1:])


def _check_command(command, cwd, probe, depth=0):
    try:
        segments = list(_segments(command))
    except ValueError as exc:
        if RISK_HINT.search(command):
            raise Blocked(f"cannot parse command to verify it is safe ({exc})")
        return
    for tokens in segments:
        _check_segment(tokens, cwd, probe, depth)


def evaluate(payload, probe=None):
    """Return (allowed, reason) for one PreToolUse payload."""
    probe = probe or GitProbe()
    try:
        if not isinstance(payload, dict):
            raise Blocked("hook input is not a JSON object")
        tool = payload.get("tool_name")
        tool_input = payload.get("tool_input") or {}
        if not isinstance(tool_input, dict):
            raise Blocked("tool_input is not an object")
        if tool in EDIT_TOOLS:
            file_path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
            if isinstance(file_path, str) and file_path.replace("\\", "/").endswith(DELEGATION_FILE):
                raise Blocked(f"only the owner changes {DELEGATION_FILE}")
        elif tool == "Bash":
            command = tool_input.get("command")
            if not isinstance(command, str):
                raise Blocked("Bash command is not a string")
            _check_command(command, payload.get("cwd") or ".", probe)
    except Blocked as exc:
        return False, str(exc)
    return True, "allowed"


def main():
    try:
        payload = json.load(sys.stdin)
    except (ValueError, UnicodeDecodeError) as exc:
        print(f"MAEP guard: blocked, hook input is not valid JSON ({exc})", file=sys.stderr)
        return 2
    allowed, reason = evaluate(payload)
    if allowed:
        return 0
    print(f"MAEP guard: blocked, {reason}. See CLAUDE.md and maep/spec/MAEP_OWNER_DELEGATION_V1.md.",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())

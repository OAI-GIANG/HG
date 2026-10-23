"""Tests for the MAEP agent guard hook (PreToolUse).

Negative tests come first: each blocked case is a destructive or authority-widening
action that CLAUDE.md and MAEP-015/016/017/027 forbid without a recovery path.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import maep_guard
from maep_guard import evaluate

HOOK = Path(__file__).with_name("maep_guard.py")
DELEGATION = "maep/spec/MAEP_OWNER_DELEGATION_V1.md"
GRANTS = "maep/authority/owner-grants.json"


class FakeProbe:
    """Git facts for tests; None means the fact could not be determined."""

    def __init__(self, branch="feature", dirty=False, untracked=False, ignored=False):
        self.branch, self.dirty, self.untracked, self.ignored = branch, dirty, untracked, ignored
        self.paths = []

    def current_branch(self, path):
        self.paths.append(path)
        return self.branch

    def has_uncommitted_changes(self, path):
        self.paths.append(path)
        return self.dirty

    def has_untracked_files(self, path, include_ignored=False):
        self.paths.append(path)
        if self.untracked is None:
            return None
        return self.untracked or (include_ignored and self.ignored)


def bash(command):
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": "/repo"}


class BlockedPushTests(unittest.TestCase):
    def assertBlocked(self, command, probe=None):
        allowed, reason = evaluate(bash(command), probe=probe or FakeProbe())
        self.assertFalse(allowed, f"expected block: {command!r}")
        self.assertTrue(reason)

    def test_force_push_variants_blocked(self):
        for command in (
            "git push --force origin feature",
            "git push -f origin feature",
            "git push -uf origin feature",
            "git push origin +feature",
            "git push origin +feature:other",
            "git push --mirror origin",
            "git push --all origin",
            "git push --prune origin",
        ):
            self.assertBlocked(command)

    def test_direct_push_to_main_blocked(self):
        for command in (
            "git push origin main",
            "git push origin HEAD:main",
            "git push origin feature:refs/heads/main",
            "git push -u origin main",
            "git -C /repo push origin main",
            "GIT_TRACE=1 git push origin main",
            "echo start; git push origin main",
            "cd /repo && git push origin main",
            "bash -c 'git push origin main'",
        ):
            self.assertBlocked(command)

    def test_implicit_push_from_main_blocked(self):
        for command in ("git push", "git push origin", "git push origin HEAD", "git push -u origin HEAD"):
            self.assertBlocked(command, FakeProbe(branch="main"))

    def test_unknown_push_destination_fails_closed(self):
        self.assertBlocked("git push", FakeProbe(branch=None))
        self.assertBlocked("git push origin HEAD", FakeProbe(branch=None))

    def test_deleting_protected_branches_blocked(self):
        for command in (
            "git push origin --delete main",
            "git push origin :main",
            "git push origin -d recovery/main-pre-maep-20261023",
            "git push origin :refs/heads/recovery/x",
        ):
            self.assertBlocked(command)

    def test_lease_force_on_protected_branches_blocked(self):
        self.assertBlocked("git push --force-with-lease origin main")
        self.assertBlocked("git push --force-with-lease=recovery/x:abc origin recovery/x")


class BlockedLocalDestructionTests(unittest.TestCase):
    def test_hard_reset_with_uncommitted_changes_blocked(self):
        allowed, _ = evaluate(bash("git reset --hard origin/main"), probe=FakeProbe(dirty=True))
        self.assertFalse(allowed)

    def test_hard_reset_with_unknown_tree_fails_closed(self):
        allowed, _ = evaluate(bash("git reset --hard"), probe=FakeProbe(dirty=None))
        self.assertFalse(allowed)

    def test_clean_force_with_untracked_files_blocked(self):
        for command in ("git clean -fd", "git clean -f", "git clean --force -d", "git clean -dfx"):
            allowed, _ = evaluate(bash(command), probe=FakeProbe(untracked=True))
            self.assertFalse(allowed, command)

    def test_clean_x_with_ignored_files_blocked(self):
        allowed, _ = evaluate(bash("git clean -fdx"), probe=FakeProbe(untracked=False, ignored=True))
        self.assertFalse(allowed)

    def test_recursive_delete_of_git_directory_blocked(self):
        for command in ("rm -rf .git", "rm -rf ./.git/", "rm -fr /repo/.git", "rm -r -f .git", "rm -Rf .git"):
            allowed, _ = evaluate(bash(command), probe=FakeProbe())
            self.assertFalse(allowed, command)

    def test_recursive_delete_of_root_or_home_blocked(self):
        for command in ("rm -rf /", "rm -rf ~", "rm -rf /*"):
            allowed, _ = evaluate(bash(command), probe=FakeProbe())
            self.assertFalse(allowed, command)


class DelegationFileTests(unittest.TestCase):
    """Only the owner changes the delegation or trust root (MAEP-017, delegation condition 3)."""

    def test_shell_writes_to_delegation_file_blocked(self):
        for command in (
            f"sed -i 's/a/b/' {DELEGATION}",
            f"echo x > {DELEGATION}",
            f"echo x >> {DELEGATION}",
            f"rm {DELEGATION}",
            f"mv {DELEGATION} /tmp/old.md",
            f"cp /tmp/new.md {DELEGATION}",
            f"git rm {DELEGATION}",
            f"git checkout HEAD~1 -- {DELEGATION}",
            f"printf x | tee {DELEGATION}",
            f"truncate -s 0 /repo/{DELEGATION}",
        ):
            allowed, _ = evaluate(bash(command), probe=FakeProbe())
            self.assertFalse(allowed, command)

    def test_edit_tools_on_delegation_file_blocked(self):
        for tool in ("Edit", "Write", "MultiEdit"):
            payload = {"tool_name": tool, "tool_input": {"file_path": f"/repo/{DELEGATION}"}}
            allowed, _ = evaluate(payload, probe=FakeProbe())
            self.assertFalse(allowed, tool)


class OwnerGrantsFileTests(unittest.TestCase):
    """RT-06: the canonical grants manifest is trust-root data; agents never write it (MAEP-017)."""

    def test_shell_writes_to_grants_file_blocked(self):
        for command in (
            f"echo '{{}}' > {GRANTS}",
            f"echo x >> {GRANTS}",
            f"sed -i 's/a/b/' {GRANTS}",
            f"cp /tmp/grants.json {GRANTS}",
            f"mv /tmp/grants.json {GRANTS}",
            f"rm {GRANTS}",
            f"git rm {GRANTS}",
            f"git checkout other-branch -- {GRANTS}",
            f"printf x | tee /repo/{GRANTS}",
            f"truncate -s 0 {GRANTS}",
        ):
            allowed, _ = evaluate(bash(command), probe=FakeProbe())
            self.assertFalse(allowed, command)

    def test_edit_tools_on_grants_file_blocked(self):
        for tool in ("Edit", "Write", "MultiEdit"):
            payload = {"tool_name": tool, "tool_input": {"file_path": f"/repo/{GRANTS}"}}
            allowed, reason = evaluate(payload, probe=FakeProbe())
            self.assertFalse(allowed, tool)
            self.assertIn(GRANTS, reason)

    def test_symlink_alias_to_grants_file_blocked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / GRANTS
            target.parent.mkdir(parents=True)
            target.write_text("{}", encoding="utf-8")
            alias = root / "alias-grants.json"
            alias.symlink_to(target)
            payload = {"tool_name": "Write", "tool_input": {"file_path": str(alias)}, "cwd": str(root)}
            allowed, reason = evaluate(payload, probe=FakeProbe())
            self.assertFalse(allowed, "symlink alias must not bypass trust-file protection")
            self.assertIn(GRANTS, reason)

    def test_path_traversal_alias_to_guard_settings_blocked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / ".claude" / "settings.json"
            target.parent.mkdir(parents=True)
            target.write_text("{}", encoding="utf-8")
            alias = root / "nested" / ".." / ".claude" / "settings.json"
            payload = {"tool_name": "Edit", "tool_input": {"file_path": str(alias)}, "cwd": str(root)}
            allowed, reason = evaluate(payload, probe=FakeProbe())
            self.assertFalse(allowed, "path traversal must not bypass guard protection")
            self.assertIn(".claude/settings.json", reason)

    def test_reading_grants_file_and_editing_neighbours_allowed(self):
        for payload in (
            bash(f"cat {GRANTS}"),
            {"tool_name": "Read", "tool_input": {"file_path": f"/repo/{GRANTS}"}},
            {"tool_name": "Write", "tool_input": {"file_path": "/repo/maep/authority/trust_anchor.py"}},
            {"tool_name": "Write", "tool_input": {"file_path": "/repo/maep/authority/owner-grants.json.example"}},
        ):
            allowed, reason = evaluate(payload, probe=FakeProbe())
            self.assertTrue(allowed, f"{payload} ({reason})")

    def test_agent_cannot_disable_or_rewrite_guard_controls(self):
        for command in (
            "echo x > .claude/settings.json",
            "sed -i 's/a/b/' .claude/settings.json",
            "rm .claude/settings.json",
            "echo x > .claude/hooks/maep_guard.py",
            "sed -i 's/a/b/' .claude/hooks/maep_guard.py",
            "git checkout other-branch -- .claude/settings.json",
        ):
            allowed, reason = evaluate(bash(command), probe=FakeProbe())
            self.assertFalse(allowed, command)
            self.assertIn("only the owner changes", reason)
        for tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
            for path in ("/repo/.claude/settings.json", "/repo/.claude/hooks/maep_guard.py"):
                payload = {"tool_name": tool, "tool_input": {"file_path": path}}
                allowed, reason = evaluate(payload, probe=FakeProbe())
                self.assertFalse(allowed, f"{tool} {path}")
                self.assertIn("only the owner changes", reason)


class InlineInterpreterTests(unittest.TestCase):
    """Inline interpreter payloads are opaque to the shell parser and must fail closed."""

    def test_inline_interpreter_execution_blocked(self):
        for command in (
            "python3 -c 'open(\"maep/authority/owner-grants.json\", \"w\").write(\"{}\")'",
            "python -c 'import subprocess; subprocess.run([\"git\", \"push\", \"origin\", \"main\"])'",
            "node -e 'require(\"child_process\").execSync(\"git push origin main\")'",
            "perl -e 'system(\"git push origin main\")'",
            "ruby -e 'system(\"git push origin main\")'",
            "php -r 'file_put_contents(\"maep/authority/owner-grants.json\", \"{}\");'",
            "env python3 -c 'print(1)'",
            "bash -c \"python3 -c 'print(1)'\"",
        ):
            allowed, reason = evaluate(bash(command), probe=FakeProbe())
            self.assertFalse(allowed, command)
            self.assertIn("inline code execution", reason)

    def test_module_based_test_runner_remains_allowed(self):
        allowed, reason = evaluate(bash("python3 -m unittest discover -s maep/tests -v"), probe=FakeProbe())
        self.assertTrue(allowed, reason)

    def test_script_file_execution_blocked(self):
        for command in (
            "python3 tools/modify_policy.py",
            "python ./scripts/update.py",
            "env python3 tools/modify_policy.py",
            "bash ./scripts/change-trust.sh",
            "sh ./scripts/change-trust.sh",
            "node ./scripts/change-policy.js",
            "ruby ./scripts/change-policy.rb",
            "perl ./scripts/change-policy.pl",
            "php ./scripts/change-policy.php",
            "bash -c 'python3 tools/modify_policy.py'",
            "env -S 'python3 tools/modify_policy.py'",
            "HG_MODE=1 env -S 'python3 tools/modify_policy.py'",
            "command env -S 'python3 tools/modify_policy.py'",
            "python3 -m unittest tools.malicious_test",
            "python3 -m unittest discover -s ../outside-tests",
            "python3 -m pytest",
            "git -c alias.pwn='!sh -c whoami' pwn",
            "git --config-env=alias.pwn=HG_ALIAS pwn",
        ):
            allowed, reason = evaluate(bash(command), probe=FakeProbe())
            self.assertFalse(allowed, command)
            self.assertTrue(reason)

    def test_opaque_shell_indirection_blocked(self):
        for command in (
            "echo $(git push origin main)",
            "echo `git push origin main`",
            "python3 -m unittest $(echo something)",
            "eval 'git push origin main'",
            "printf 'git push origin main' | xargs -I{} sh -c '{}'",
            "find . -type f -exec sh -c 'git push origin main' \\;",
            "cat <(git status)",
            "cat >(tee /tmp/maep-probe)",
        ):
            allowed, reason = evaluate(bash(command), probe=FakeProbe())
            self.assertFalse(allowed, command)
            self.assertTrue(reason)

    def test_allowlisted_modules_and_version_queries_remain_allowed(self):
        for command in (
            "python3 -m unittest discover -s maep/tests",
            "python3 -m unittest discover -s hg/tests -p test_*.py",
            "python3 --version",
            "node --version",
        ):
            allowed, reason = evaluate(bash(command), probe=FakeProbe())
            self.assertTrue(allowed, f"{command}: {reason}")


class MalformedInputTests(unittest.TestCase):
    def test_unparseable_risky_command_fails_closed(self):
        allowed, _ = evaluate(bash("git push origin 'main"), probe=FakeProbe())
        self.assertFalse(allowed)

    def test_non_object_payload_fails_closed(self):
        allowed, _ = evaluate(["not", "a", "payload"], probe=FakeProbe())
        self.assertFalse(allowed)

    def test_non_string_command_fails_closed(self):
        allowed, _ = evaluate({"tool_name": "Bash", "tool_input": {"command": 42}}, probe=FakeProbe())
        self.assertFalse(allowed)


class AllowedTests(unittest.TestCase):
    def assertAllowed(self, command, probe=None):
        allowed, reason = evaluate(bash(command), probe=probe or FakeProbe())
        self.assertTrue(allowed, f"expected allow: {command!r} ({reason})")

    def test_ordinary_feature_branch_pushes_allowed(self):
        for command in (
            "git push origin feature",
            "git push -u origin stt/rt01-enforcement",
            "git push origin feature:feature-copy",
            "git push --force-with-lease origin feature",
            "git push origin --delete old-feature",
            "git push origin abc123:refs/heads/recovery/main-pre-x",
            "git push origin --tags",
        ):
            self.assertAllowed(command)

    def test_implicit_push_from_feature_branch_allowed(self):
        self.assertAllowed("git push", FakeProbe(branch="feature"))
        self.assertAllowed("git push origin HEAD", FakeProbe(branch="feature"))

    def test_safe_local_git_commands_allowed(self):
        self.assertAllowed("git reset --hard origin/feature", FakeProbe(dirty=False))
        self.assertAllowed("git reset --soft HEAD~1", FakeProbe(dirty=True))
        self.assertAllowed("git clean -n", FakeProbe(untracked=True))
        self.assertAllowed("git clean -fd", FakeProbe(untracked=False))
        self.assertAllowed("git log --oneline main")
        self.assertAllowed("git status && git diff main")

    def test_ordinary_shell_commands_allowed(self):
        for command in (
            "rm -rf build/",
            "rm -rf node_modules .pytest_cache",
            f"cat {DELEGATION}",
            f"grep -n trust {DELEGATION}",
            'echo "git push --force origin main"',
            "python -m unittest discover -s maep/tests -v",
        ):
            self.assertAllowed(command)

    def test_heredoc_body_is_not_parsed_as_commands(self):
        command = "cat > notes.md <<'EOF'\ngit push --force origin main\nrm -rf .git\nEOF\necho done"
        self.assertAllowed(command)

    def test_command_after_heredoc_is_still_checked(self):
        command = "cat > notes.md <<'EOF'\nhello\nEOF\ngit push origin main"
        allowed, _ = evaluate(bash(command), probe=FakeProbe())
        self.assertFalse(allowed)

    def test_other_tools_and_files_allowed(self):
        for payload in (
            {"tool_name": "Read", "tool_input": {"file_path": f"/repo/{DELEGATION}"}},
            {"tool_name": "Edit", "tool_input": {"file_path": "/repo/maep/core.py"}},
            {"tool_name": "Glob", "tool_input": {"pattern": "**/*.py"}},
        ):
            allowed, reason = evaluate(payload, probe=FakeProbe())
            self.assertTrue(allowed, f"{payload} ({reason})")

    def test_git_C_path_is_used_for_probes(self):
        probe = FakeProbe(dirty=True)
        evaluate(bash("git -C /other reset --hard"), probe=probe)
        self.assertIn("/other", probe.paths)


class HookProcessTests(unittest.TestCase):
    """Run the hook as Claude Code does: JSON on stdin, exit 2 blocks with stderr."""

    def run_hook(self, payload, cwd=None):
        return subprocess.run(
            [sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
            text=True, cwd=cwd, timeout=30,
        )

    def test_block_exits_2_with_reason_on_stderr(self):
        result = self.run_hook(bash("git push --force origin feature"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("MAEP guard", result.stderr)

    def test_allow_exits_0(self):
        result = self.run_hook(bash("git status"))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_malformed_stdin_exits_2(self):
        result = subprocess.run([sys.executable, str(HOOK)], input="{not json", capture_output=True,
                                text=True, timeout=30)
        self.assertEqual(result.returncode, 2)

    def test_real_git_probe_dirty_and_clean_tree(self):
        with tempfile.TemporaryDirectory() as repo:
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                       GIT_COMMITTER_EMAIL="t@t")
            subprocess.run(["git", "init", "-q", "-b", "feature", repo], check=True, env=env)
            Path(repo, "a.txt").write_text("one\n", encoding="utf-8")
            subprocess.run(["git", "-C", repo, "add", "a.txt"], check=True, env=env)
            subprocess.run(["git", "-C", repo, "commit", "-q", "-m", "init"], check=True, env=env)
            payload = {"tool_name": "Bash", "tool_input": {"command": "git reset --hard"}, "cwd": repo}
            self.assertEqual(self.run_hook(payload, cwd=repo).returncode, 0)
            Path(repo, "a.txt").write_text("two\n", encoding="utf-8")
            self.assertEqual(self.run_hook(payload, cwd=repo).returncode, 2)
            clean = {"tool_name": "Bash", "tool_input": {"command": "git clean -fd"}, "cwd": repo}
            subprocess.run(["git", "-C", repo, "checkout", "-q", "--", "a.txt"], check=True, env=env)
            self.assertEqual(self.run_hook(clean, cwd=repo).returncode, 0)
            Path(repo, "new.txt").write_text("x\n", encoding="utf-8")
            self.assertEqual(self.run_hook(clean, cwd=repo).returncode, 2)
            push = {"tool_name": "Bash", "tool_input": {"command": "git push origin HEAD"}, "cwd": repo}
            self.assertEqual(self.run_hook(push, cwd=repo).returncode, 0)
            subprocess.run(["git", "-C", repo, "branch", "-q", "-m", "main"], check=True, env=env)
            self.assertEqual(self.run_hook(push, cwd=repo).returncode, 2)


if __name__ == "__main__":
    unittest.main()

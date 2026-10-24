"""Small deterministic local Git fixture for release-integrity tests."""
import os
from pathlib import Path
import subprocess

from hg.release import build_release, extract_archive


def make_tiny_release(root: Path):
    root = Path(root)
    repo = root / "source-repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", "--initial-branch=main", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "HG tests"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "hg-tests@example.invalid"], check=True)
    files = {
        "README.md": "HG release fixture\n",
        "hg/runtime.py": '"""fixture runtime source"""\n',
        "bin/check": "#!/bin/sh\nexit 0\n",
    }
    for name, content in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    (repo / "bin/check").chmod(0o755)
    subprocess.run(["git", "-C", str(repo), "add", "--", *files], check=True)
    env = dict(os.environ, GIT_AUTHOR_NAME="HG tests", GIT_AUTHOR_EMAIL="hg-tests@example.invalid",
               GIT_COMMITTER_NAME="HG tests", GIT_COMMITTER_EMAIL="hg-tests@example.invalid")
    subprocess.run(["git", "-C", str(repo), "commit", "--quiet", "-m", "fixture"], check=True, env=env)
    commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
                            capture_output=True, text=True).stdout.strip()
    archive = root / "release.tar.gz"
    manifest = root / "release-manifest.json"
    doc = build_release(repo, commit, archive, manifest)
    release_root = root / "release-root"
    extract_archive(archive, release_root)
    return {"repo": repo, "commit": commit, "archive": archive, "manifest": manifest,
            "root": release_root, "doc": doc}

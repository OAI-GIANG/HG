"""Deterministic release packaging and source-integrity verification for HG.

The manifest is a transport record, not a signature. Build/verify commands bind it
back to the exact Git commit/tree; a deployed service checks the installed file set
against the manifest and a locally configured release_id.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import tempfile
import zlib

REPOSITORY = "OAI-GIANG/HG"
SCHEMA = "hg-release-manifest-v1"


class ReleaseError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def _canonical_json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _reject_constant(_value):
    raise ValueError("non-finite JSON constant is not permitted")


def _git(repo: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    try:
        p = subprocess.run(["git", "-C", str(repo), *args], input=input_bytes,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    except OSError as exc:
        raise ReleaseError(f"git command unavailable ({type(exc).__name__})") from exc
    if p.returncode:
        raise ReleaseError("git command failed: " + " ".join(args[:2]))
    return p.stdout


def _validate_commit(commit: str) -> str:
    if not isinstance(commit, str) or len(commit) != 40 or any(ch not in "0123456789abcdef" for ch in commit):
        raise ReleaseError("commit must be a full lowercase 40-character Git SHA")
    return commit


def _tree_records(repo: Path, commit: str):
    _validate_commit(commit)
    raw = _git(repo, "ls-tree", "-r", "-z", "--full-tree", commit)
    rows = {}
    for item in raw.split(b"\0"):
        if not item:
            continue
        try:
            meta, raw_path = item.split(b"\t", 1)
            mode, kind, blob = meta.decode("ascii").split(" ")
            path = raw_path.decode("utf-8")
        except (ValueError, UnicodeError) as exc:
            raise ReleaseError("unexpected git tree encoding") from exc
        pp = PurePosixPath(path)
        if (pp.is_absolute() or not path or pp.as_posix() != path or "\\" in path
                or "\x00" in path or any(part in ("", ".", "..") for part in pp.parts)):
            raise ReleaseError("unsafe path in source tree")
        if kind != "blob" or mode not in ("100644", "100755"):
            raise ReleaseError(f"unsupported non-regular source entry: {path}")
        rows[path] = {"path": path, "mode": mode, "git_blob": blob}
    return rows


def _read_archive(data: bytes):
    files = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tf:
            for member in tf.getmembers():
                pp = PurePosixPath(member.name)
                if (pp.is_absolute() or not member.name or pp.as_posix() != member.name
                        or any(x in ("", ".", "..") for x in pp.parts)):
                    raise ReleaseError("unsafe path in release archive")
                if member.isdir():
                    continue
                if not member.isfile():
                    raise ReleaseError(f"non-regular entry in release archive: {member.name}")
                stream = tf.extractfile(member)
                if stream is None:
                    raise ReleaseError(f"cannot read archive member: {member.name}")
                if member.name in files:
                    raise ReleaseError("duplicate archive path")
                files[member.name] = (member.mode, stream.read())
    except (tarfile.TarError, OSError) as exc:
        raise ReleaseError("invalid release archive") from exc
    return files


def _make_manifest(repo: Path, commit: str, archive_bytes: bytes):
    resolved = _git(repo, "rev-parse", "--verify", f"{commit}^{{commit}}").decode().strip()
    tree = _git(repo, "rev-parse", "--verify", f"{resolved}^{{tree}}").decode().strip()
    rows = _tree_records(repo, resolved)
    try:
        tar_bytes = gzip.decompress(archive_bytes)
    except (OSError, EOFError, zlib.error) as exc:
        raise ReleaseError("release archive is not valid gzip") from exc
    archive_files = _read_archive(tar_bytes)
    if set(rows) != set(archive_files):
        raise ReleaseError("git archive file set differs from the commit tree")
    files = []
    for path in sorted(rows):
        mode, content = archive_files[path]
        row = rows[path]
        executable = bool(mode & 0o111)
        expected_executable = row["mode"] == "100755"
        if executable != expected_executable or _blob_sha(content) != row["git_blob"]:
            raise ReleaseError(f"archive content differs from Git blob: {path}")
        files.append({**row, "sha256": _sha256(content), "bytes": len(content)})
    doc = {"schema": SCHEMA, "repository": REPOSITORY, "commit": resolved, "tree": tree,
           "archive_sha256": _sha256(archive_bytes), "files": files}
    doc["release_id"] = _sha256(_canonical_json(doc))
    return doc


def build_release(repo: str | Path, commit: str, archive_path: str | Path, manifest_path: str | Path):
    repo = Path(repo).resolve()
    _validate_commit(commit)
    try:
        tar_bytes = _git(repo, "archive", "--format=tar", commit)
    except ReleaseError:
        raise
    out = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=out, mtime=0, compresslevel=9) as gz:
        gz.write(tar_bytes)
    archive = out.getvalue()
    doc = _make_manifest(repo, commit, archive)
    archive_path, manifest_path = Path(archive_path), Path(manifest_path)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_bytes(archive)
    manifest_path.write_bytes(_canonical_json({**doc, "release_id": doc["release_id"]}) + b"\n")
    return doc


def _load_manifest(path: str | Path):
    try:
        raw = Path(path).read_bytes()
        doc = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                         parse_constant=_reject_constant)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ReleaseError("release manifest is unreadable or invalid") from exc
    required = {"schema", "repository", "commit", "tree", "archive_sha256", "files", "release_id"}
    if not isinstance(doc, dict) or set(doc) != required:
        raise ReleaseError("release manifest has an unsupported schema or key set")
    if doc.get("schema") != SCHEMA or doc.get("repository") != REPOSITORY:
        raise ReleaseError("release manifest has an unsupported schema or repository")
    claimed = doc.get("release_id")
    core = {k: v for k, v in doc.items() if k != "release_id"}
    try:
        expected_id = _sha256(_canonical_json(core))
    except (TypeError, ValueError) as exc:
        raise ReleaseError("release manifest contains unsupported JSON values") from exc
    if not isinstance(claimed, str) or claimed != expected_id:
        raise ReleaseError("release manifest digest mismatch")
    _validate_commit(doc.get("commit"))
    for field in ("tree", "archive_sha256", "release_id"):
        value = doc.get(field)
        length = 40 if field == "tree" else 64
        if not isinstance(value, str) or len(value) != length or any(ch not in "0123456789abcdef" for ch in value):
            raise ReleaseError(f"release manifest {field} is invalid")
    rows = doc.get("files")
    if not isinstance(rows, list):
        raise ReleaseError("release manifest files must be an array")
    seen = set()
    row_keys = {"path", "mode", "git_blob", "sha256", "bytes"}
    for row in rows:
        if not isinstance(row, dict) or set(row) != row_keys:
            raise ReleaseError("release manifest contains an invalid file record")
        path = row.get("path")
        if (not isinstance(path, str) or not path or PurePosixPath(path).is_absolute()
                or PurePosixPath(path).as_posix() != path or "\\" in path or "\x00" in path
                or any(part in ("", ".", "..") for part in PurePosixPath(path).parts)
                or path in seen):
            raise ReleaseError("release manifest contains an unsafe or duplicate path")
        seen.add(path)
        if row.get("mode") not in ("100644", "100755"):
            raise ReleaseError(f"release manifest mode is invalid: {path}")
        for field, length in (("git_blob", 40), ("sha256", 64)):
            value = row.get(field)
            if not isinstance(value, str) or len(value) != length or any(ch not in "0123456789abcdef" for ch in value):
                raise ReleaseError(f"release manifest {field} is invalid: {path}")
        size = row.get("bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ReleaseError(f"release manifest byte length is invalid: {path}")
    return doc


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _verify_content_map(expected_rows, actual_files):
    if not isinstance(expected_rows, list) or not all(isinstance(x, dict) for x in expected_rows):
        raise ReleaseError("manifest file list is invalid")
    expected = {x.get("path"): x for x in expected_rows}
    if len(expected) != len(expected_rows) or set(expected) != set(actual_files):
        raise ReleaseError("release file set does not match manifest")
    for path, (mode, content) in actual_files.items():
        row = expected[path]
        if (row.get("sha256") != _sha256(content) or row.get("bytes") != len(content)
                or row.get("git_blob") != _blob_sha(content)
                or (bool(mode & 0o111) != (row.get("mode") == "100755"))):
            raise ReleaseError(f"release file integrity mismatch: {path}")
    return len(expected)


def verify_archive(repo: str | Path, archive_path: str | Path, manifest_path: str | Path):
    repo = Path(repo).resolve()
    archive = Path(archive_path).read_bytes()
    doc = _load_manifest(manifest_path)
    if doc.get("archive_sha256") != _sha256(archive):
        raise ReleaseError("release archive SHA-256 mismatch")
    try:
        compressed = gzip.decompress(archive)
    except (OSError, EOFError, zlib.error) as exc:
        raise ReleaseError("release archive is not valid gzip") from exc
    files = _read_archive(compressed)
    count = _verify_content_map(doc.get("files"), files)
    commit = _validate_commit(doc.get("commit"))
    resolved = _git(repo, "rev-parse", "--verify", f"{commit}^{{commit}}").decode().strip()
    tree = _git(repo, "rev-parse", "--verify", f"{resolved}^{{tree}}").decode().strip()
    if resolved != commit or tree != doc.get("tree"):
        raise ReleaseError("manifest commit/tree does not match the repository")
    source_rows = _tree_records(repo, resolved)
    if set(source_rows) != set(files):
        raise ReleaseError("release file set does not match the Git tree")
    for path, row in source_rows.items():
        content = files[path][1]
        if row["git_blob"] != _blob_sha(content):
            raise ReleaseError(f"release content differs from repository blob: {path}")
    return {"result": "VERIFIED", "release_id": doc["release_id"], "commit": resolved,
            "tree": tree, "files_checked": count, "archive_sha256": _sha256(archive)}


def verify_root(root_path: str | Path, manifest_path: str | Path, expected_release_id: str):
    root_input = Path(root_path)
    if root_input.is_symlink() or not root_input.is_dir():
        raise ReleaseError("installed release root must be a real directory, not a symlink")
    root, doc = root_input.resolve(), _load_manifest(manifest_path)
    if doc.get("release_id") != expected_release_id:
        raise ReleaseError("configured release_id does not match manifest")
    actual = {}
    try:
        for path in root.rglob("*"):
            rel = path.relative_to(root).as_posix()
            if path.is_symlink():
                raise ReleaseError(f"symlink in installed release: {rel}")
            if path.is_file():
                mode = 0o755 if os.stat(path).st_mode & 0o111 else 0o644
                actual[rel] = (mode, path.read_bytes())
            elif not path.is_dir():
                raise ReleaseError(f"special file in installed release: {rel}")
    except OSError as exc:
        raise ReleaseError("cannot inspect installed release files") from exc
    count = _verify_content_map(doc.get("files"), actual)
    return {"result": "VERIFIED", "release_id": doc["release_id"], "commit": doc["commit"],
            "tree": doc["tree"], "files_checked": count}


def extract_archive(archive_path: str | Path, destination: str | Path):
    destination = Path(destination)
    if destination.is_symlink():
        raise ReleaseError("release destination must not be a symlink")
    if destination.exists() and not destination.is_dir():
        raise ReleaseError("release destination must be a directory")
    if destination.exists() and any(destination.iterdir()):
        raise ReleaseError("release destination must be empty")
    destination.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archive_path, "r:gz") as tf:
            for member in tf.getmembers():
                pp = PurePosixPath(member.name)
                target = (destination / Path(*pp.parts)).resolve()
                if (pp.is_absolute() or pp.as_posix() != member.name
                        or any(x in ("", ".", "..") for x in pp.parts)
                        or destination.resolve() not in target.parents):
                    raise ReleaseError("unsafe archive path")
                if not (member.isfile() or member.isdir()):
                    raise ReleaseError("release contains a non-regular entry")
            tf.extractall(destination, filter="data")
    except (tarfile.TarError, OSError, EOFError, zlib.error) as exc:
        raise ReleaseError("could not extract release") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m hg.release")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--repo", required=True)
    build.add_argument("--commit", required=True)
    build.add_argument("--archive", required=True)
    build.add_argument("--manifest", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--repo", required=True)
    verify.add_argument("--archive", required=True)
    verify.add_argument("--manifest", required=True)
    extract = sub.add_parser("extract")
    extract.add_argument("--archive", required=True)
    extract.add_argument("--destination", required=True)
    root = sub.add_parser("verify-root")
    root.add_argument("--root", required=True)
    root.add_argument("--manifest", required=True)
    root.add_argument("--release-id", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            doc = build_release(args.repo, args.commit, args.archive, args.manifest)
            report = {"result": "BUILT", "release_id": doc["release_id"], "commit": doc["commit"],
                      "tree": doc["tree"], "files": len(doc["files"]), "archive_sha256": doc["archive_sha256"]}
        elif args.command == "verify":
            report = verify_archive(args.repo, args.archive, args.manifest)
        elif args.command == "extract":
            extract_archive(args.archive, args.destination)
            report = {"result": "EXTRACTED", "destination": str(Path(args.destination).resolve())}
        else:
            report = verify_root(args.root, args.manifest, args.release_id)
    except ReleaseError as exc:
        print(json.dumps({"result": "FAILED", "reason": str(exc)}))
        return 2
    except OSError as exc:
        print(json.dumps({"result": "FAILED", "reason": f"filesystem operation failed ({type(exc).__name__})"}))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

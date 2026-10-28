#!/data/data/com.termux/files/usr/bin/sh
# HG v1 — build a release from a merged main commit, twice, in a private build dir (never ~/HG).
# usage: sh build_release.sh <commit-sha>
set -eu
C="$1"
B="$HOME/hg-release-build/$C"
mkdir -p "$B"
cd "$B"
if [ ! -d repo ]; then
  git init -q repo
  git -C repo remote add origin https://github.com/OAI-GIANG/HG.git
fi
git -C repo fetch -q --depth 1 origin "$C"
git -C repo checkout -q --detach FETCH_HEAD
test "$(git -C repo rev-parse HEAD)" = "$C"
cd repo
python3 -I -B -m hg.release build --repo . --commit "$C" --archive "$B/one.tar.gz" --manifest "$B/one.json" > "$B/build-one.json"
python3 -I -B -m hg.release build --repo . --commit "$C" --archive "$B/two.tar.gz" --manifest "$B/two.json" > "$B/build-two.json"
cmp "$B/one.tar.gz" "$B/two.tar.gz"
cmp "$B/one.json" "$B/two.json"
python3 -I -B -m hg.release verify --repo . --archive "$B/one.tar.gz" --manifest "$B/one.json" > "$B/verify.json"
cat "$B/build-one.json"
cat "$B/verify.json"
# Provenance across machines: compare tree + per-file manifest (archive bytes may differ by platform zlib).
python3 -I -c 'import json,hashlib,sys; d=json.load(open(sys.argv[1])); print("files", len(d["files"]), "files_digest", hashlib.sha256(json.dumps(d["files"], sort_keys=True).encode()).hexdigest(), "tree", d["tree"])' "$B/one.json"
echo BUILD_OK

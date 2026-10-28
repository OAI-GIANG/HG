#!/data/data/com.termux/files/usr/bin/sh
# HG v1 — install a built release beside the running one and point the `hg` command at it.
# Does NOT touch the hg-runtime service (that is switch_service.sh).
# usage: sh install_release.sh <commit-sha>
set -eu
C="$1"
B="$HOME/hg-release-build/$C"
RID="$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["release_id"])' "$B/one.json")"
ROOT="$HOME/hg-releases/$RID"
MAN="$HOME/.config/hg/releases/$RID.json"
if [ -e "$ROOT" ]; then
  echo "release dir already exists: $ROOT (not overwriting)"
else
  python3 -I -B -c 'import sys; sys.path.insert(0, sys.argv[1]); from hg.release import extract_archive; extract_archive(sys.argv[2], sys.argv[3])' "$B/repo" "$B/one.tar.gz" "$ROOT"
fi
if [ ! -e "$MAN" ]; then
  install -m 600 "$B/one.json" "$MAN"
fi
cmp "$B/one.json" "$MAN"
python3 -I -B -c 'import sys, json; sys.path.insert(0, sys.argv[1]); from hg.release import verify_root; print(json.dumps(verify_root(sys.argv[1], sys.argv[2], sys.argv[3]), sort_keys=True))' "$ROOT" "$MAN" "$RID"

# `hg` command: pointer file + shim (the shim never imports from the current directory).
POINTER="$HOME/.config/hg/assistant-release"
if [ -e "$POINTER" ]; then cp -p "$POINTER" "$POINTER.prev"; fi
printf '%s\n' "$ROOT" > "$POINTER.tmp" && chmod 600 "$POINTER.tmp" && mv "$POINTER.tmp" "$POINTER"
SHIM="$PREFIX/bin/hg"
if [ -e "$SHIM" ] && ! grep -q "HG command shim" "$SHIM"; then
  echo "$SHIM exists and is not the HG shim; not overwriting"; exit 1
fi
sed "s#@SH@#$PREFIX/bin/sh#" "$ROOT/hg/assistant/hg-shim.sh" > "$SHIM.tmp"
chmod 755 "$SHIM.tmp" && mv "$SHIM.tmp" "$SHIM"
echo "RELEASE_ID=$RID"
echo "ROOT=$ROOT"
echo INSTALL_OK

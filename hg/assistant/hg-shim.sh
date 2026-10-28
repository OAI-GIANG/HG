#!@SH@
# HG command shim — installed as `hg` on the owner's PATH by the deploy (docs/HG_V1_GUIDE.md).
#
# It runs the verified release named in $HG_CONFIG_DIR/assistant-release (one absolute
# path), never a git checkout: `python3 -I` ignores the current directory, PYTHONPATH and the
# user site, so running `hg` from inside ~/HG still imports the release (AC-D2). Relative
# paths such as `hg summarize notes.txt` keep working because the shim does not cd.
set -eu
conf_dir="${HG_CONFIG_DIR:-$HOME/.config/hg}"
pointer="$conf_dir/assistant-release"
if [ ! -f "$pointer" ]; then
    echo "HG: chưa cài release cho lệnh hg ($pointer không tồn tại)" >&2
    exit 78
fi
root="$(head -n 1 "$pointer")"
case "$root" in
    /*) ;;
    *) echo "HG: $pointer phải chứa một đường dẫn tuyệt đối" >&2; exit 78 ;;
esac
if [ ! -f "$root/hg/__main__.py" ]; then
    echo "HG: release $root không có hg/__main__.py" >&2
    exit 78
fi
HG_RELEASE_ID="$(basename "$root")"
export HG_RELEASE_ID
exec python3 -I -B -c 'import sys; sys.path.insert(0, sys.argv.pop(1)); from hg.__main__ import main; sys.exit(main(sys.argv[1:]))' "$root" "$@"

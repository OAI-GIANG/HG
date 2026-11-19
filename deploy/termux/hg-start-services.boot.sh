#!/data/data/com.termux/files/usr/bin/sh
# Installed as ~/.termux/boot/00-start-services (Termux:Boot runs it after the phone boots).
# Source: OAI-GIANG/HG deploy/termux/hg-start-services.boot.sh (P3 Strategy C, ledger §67).
export HOME="/data/data/com.termux/files/home"
export PREFIX="/data/data/com.termux/files/usr"
export PATH="$PREFIX/bin:$PREFIX/bin/applets:/system/bin"
export SVDIR="$PREFIX/var/service"
export LOGDIR="$PREFIX/var/log"
export TERMUX__HOME="$HOME"
export TERMUX__PREFIX="$PREFIX"

ENTRY="$HOME/.local/bin/hg-ensure-services.sh"
if [ -x "$ENTRY" ]; then
  exec "$ENTRY" --source boot
fi

# Entrypoint not installed: the previous boot behaviour (wake lock, then the supervisor).
termux-wake-lock >/dev/null 2>&1 || true
service-daemon start >/dev/null 2>&1 || true

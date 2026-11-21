# Installed as $PREFIX/etc/profile.d/start-services.sh (replaces the termux-services 0.13 hook).
# Source: OAI-GIANG/HG deploy/termux/hg-start-services.profile.sh (P3 Strategy C, ledger §67).
# Sourced by every login shell, so it must return at once: the entrypoint runs in the background.
export SVDIR=$PREFIX/var/service
export LOGDIR=$PREFIX/var/log
if [ -x "$HOME/.local/bin/hg-ensure-services.sh" ]; then
  ( "$HOME/.local/bin/hg-ensure-services.sh" --source profile >/dev/null 2>&1 & )
else
  # Entrypoint not installed: the original termux-services behaviour.
  (service-daemon start >/dev/null 2>&1 & )
fi

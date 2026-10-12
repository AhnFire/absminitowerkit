#!/bin/bash
# ============================================================================
#  uninstall_trixie.sh - reverses install_trixie.sh
#
#  The upstream uninstall.sh does not remove anything install_bookworm.sh
#  wrote into config.txt (dtparam=i2c_arm=on) and knows nothing about the fan
#  overlay, so both are handled here.
#
#  Usage: sudo ./uninstall_trixie.sh [--dry-run]
# ============================================================================
set -u
DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

if [ "$(id -u)" -ne 0 ]; then
  echo "please run with sudo" >&2
  exit 1
fi

run() { if [ "$DRY_RUN" = 1 ]; then printf '  [dry-run] %s\n' "$*"; else "$@"; fi; }

CONFIG=""
for f in /boot/firmware/config.txt /boot/config.txt; do
  if [ -f "$f" ]; then CONFIG="$f"; break; fi
done

[ "$DRY_RUN" = 1 ] && echo "[!] DRY RUN: nothing will be modified"

echo "[*] disabling and removing the systemd units"
run systemctl disable --now minitower_moodlight.service 2>/dev/null
run systemctl disable --now minitower_oled.service 2>/dev/null
run rm -f /etc/systemd/system/minitower_moodlight.service \
           /etc/systemd/system/minitower_oled.service
run systemctl daemon-reload

echo "[*] removing installed scripts"
run rm -rf /usr/local/minitower
run rm -f /usr/bin/moodlight

if [ -n "$CONFIG" ]; then
  echo "[*] reverting $CONFIG"
  if [ "$DRY_RUN" = 1 ]; then
    echo "  [dry-run] would strip the pwm-gpio-fan overlay, its comments and dtparam=i2c_arm=on"
  else
    sed -i -E '/^dtoverlay=pwm-gpio-fan.*/d' "$CONFIG"
    sed -i -E '/^# --- Mini Tower NAS V2 fan/d' "$CONFIG"
    sed -i -E '/^# --- pin 18 is the WS281X LED pin/d' "$CONFIG"
    # we only ever add the plain "=on" form, so this is safe to drop
    sed -i -E '/^dtparam=i2c_arm=on$/d' "$CONFIG"
  fi
  if [ -f "$CONFIG.premintower" ]; then
    echo "[i] an untouched original config.txt is still at $CONFIG.premintower"
    echo "    restore it with:  sudo cp $CONFIG.premintower $CONFIG"
  fi
fi

echo "[i] Left in place on purpose:"
echo "    - the luma.examples clone in the user's home directory"
echo "    - packages installed by apt (remove manually if you want)"
echo "    - a custom LED unit's scripts under /usr/local/minitower (removed above)"
if [ "$DRY_RUN" = 0 ]; then
  echo "[*] Done. Reboot to unload the fan overlay."
fi

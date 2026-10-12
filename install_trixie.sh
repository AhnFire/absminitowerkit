#!/bin/bash
# ============================================================================
#  install_trixie.sh - GeeekPi / 52Pi ABS Mini Tower Kit installer
#  Raspberry Pi OS Trixie (Debian 13) and Bookworm (Debian 12), arm64/armhf
#
#  Fork: AhnFire/absminitowerkit   Upstream: geeekpi/absminitowerkit
#
#  Why this exists (all verified, see TRIXIE-NOTES.md):
#   1. Never touches /etc/resolv.conf. install_bookworm.sh commented out every
#      nameserver and forced 114.114.114.114 + 8.8.8.8, hijacking your DNS.
#   2. No hardcoded `pi` user (upstream issue #15: "im using a custom username
#      instead of pi if that makes any difference"). Detects SUDO_USER.
#   3. Trixie package names: libfreetype6-dev no longer exists (it is
#      libfreetype-dev), which made the original apt line fail on Pi OS 6
#      (upstream issue #18 "Not compatible with rasbian trixie?").
#   4. No pip-editable install into /tmp. The original did
#      `pip3 install -e /tmp/luma.examples`, and systemd-tmpfiles-clean.timer
#      deletes /tmp daily, leaving a dangling package. We use apt
#      python3-luma.oled / python3-psutil, plus the minitower package below.
#   5. Correct systemd units. The originals use Type=simple together with
#      RemainAfterExit=yes and Restart=always; RemainAfterExit only applies to
#      Type=oneshot and disables Restart, so failures/deaths are not supervised.
#   6. Real fan control for the V2 4-wire fan via the kernel `pwm-gpio-fan`
#      overlay on GPIO14 (the userspace bit-bang demo burns >10% CPU -
#      upstream issue #17).
#   7. Idempotent config.txt edits, --dry-run, and no forced reboot
#      (the original always rebooted the machine at the end).
#   8. Loads the i2c-dev module and installs fonts-dejavu-core. Without i2c-dev
#      there is no /dev/i2c-1 at all on Trixie Lite, and without the font PIL
#      raises "OSError: cannot open resource" - both leave the OLED blank
#      (upstream issue #16). Both were found by running this on real hardware.
#   9. Installs the minitower package, which is what actually drives the LEDs
#      and the panel now. The vendor's moodlight binary was upstream's 8x8
#      matrix demo (64 pixels at 15 fps) and its single-view sysinfo.py never
#      rotated pages; both are replaced, and --leds moodlight/custom keep the
#      old behaviour available.
#
#  Usage:  sudo ./install_trixie.sh [options]
# ============================================================================
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VER="1.3.0-trixie"

# ---------------------------------------------------------------- defaults ---
TARGET_USER="${SUDO_USER:-}"
FAN_GPIO="14"                 # ZP-0130 V2 4-wire fan PWM = GPIO14 (pin 8)
LED_MODE="driver"             # driver | moodlight | custom | none
MOODLIGHT_BIN="/usr/bin/moodlight"
PREFIX="/usr/local/minitower"
DO_REBOOT=0
DRY_RUN=0

c_err=$'\033[31m'; c_ok=$'\033[32m'; c_warn=$'\033[33m'; c_info=$'\033[36m'; c_off=$'\033[0m'
log()  { printf '%s[*]%s %s\n' "$c_info" "$c_off" "$*"; }
ok()   { printf '%s[+]%s %s\n' "$c_ok"   "$c_off" "$*"; }
warn() { printf '%s[!]%s %s\n' "$c_warn" "$c_off" "$*" >&2; }
die()  { printf '%s[x]%s %s\n' "$c_err"  "$c_off" "$*" >&2; exit 1; }

usage() {
  cat <<EOF
GeeekPi ABS Mini Tower Kit installer v$VER

  --user NAME        target desktop user (default: \$SUDO_USER)
  --leds MODE        driver (minitower package, default) | moodlight | custom | none
  --fan-gpio N       fan PWM GPIO (default 14, the V2 4-wire fan)
  --no-fan           do not configure fan control
  --prefix DIR       install prefix for the legacy custom LED scripts (default $PREFIX)
  --reboot           reboot when finished (default: do not)
  --dry-run          print what would change, change nothing
  -h, --help         this text
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --user)      TARGET_USER="${2:-}"; shift 2 ;;
    --leds)      LED_MODE="${2:-}";    shift 2 ;;
    --fan-gpio)  FAN_GPIO="${2:-}";    shift 2 ;;
    --no-fan)    FAN_GPIO="none";      shift   ;;
    --prefix)    PREFIX="${2:-}";      shift 2 ;;
    --reboot)    DO_REBOOT=1;          shift   ;;
    --dry-run)   DRY_RUN=1;            shift   ;;
    -h|--help)   usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

case "$LED_MODE" in driver|moodlight|custom|none) ;; *) die "--leds must be driver, moodlight, custom or none" ;; esac

# -------------------------------------------------------------- preflight ----
[ "$(id -u)" -eq 0 ] || die "please run with sudo (needs apt, config.txt and systemd write access)"
[ -d "$SCRIPT_DIR/democ_code" ] || die "run this from inside the repository (democ_code/ not found next to the script)"

if [ -z "$TARGET_USER" ]; then
  TARGET_USER="$(id -nu 1000 2>/dev/null || true)"
fi
[ -n "$TARGET_USER" ] || die "cannot determine target user; pass --user NAME"
id "$TARGET_USER" >/dev/null 2>&1 || die "no such user: $TARGET_USER"
HOME_DIR="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
[ -d "$HOME_DIR" ] || die "home directory $HOME_DIR not found"

. /etc/os-release
CODENAME="${VERSION_CODENAME:-unknown}"
ARCH="$(uname -m)"
case "$CODENAME" in
  trixie|bookworm) log "OS: Raspberry Pi OS / Debian $CODENAME ($ARCH)" ;;
  *) warn "untested distribution '$CODENAME' - package names may differ, continuing" ;;
esac

CONFIG=""
for f in /boot/firmware/config.txt /boot/config.txt; do
  if [ -f "$f" ]; then CONFIG="$f"; break; fi
done
[ -n "$CONFIG" ] || die "cannot find config.txt (looked in /boot/firmware and /boot)"

log "user=$TARGET_USER  home=$HOME_DIR  config=$CONFIG"
[ "$DRY_RUN" = 1 ] && warn "DRY RUN: nothing will be modified"

# ----------------------------------------------------------------- helpers ---
run()   { if [ "$DRY_RUN" = 1 ]; then printf '  [dry-run] %s\n' "$*"; else "$@"; fi; }
apt_i() { if [ "$DRY_RUN" = 1 ]; then printf '  [dry-run] apt-get install %s\n' "$*"; else apt-get -y -q install "$@"; fi; }

# remove every config.txt line matching an extended regex
cfg_drop() {
  local re="$1"
  if [ "$DRY_RUN" = 1 ]; then printf '  [dry-run] would delete lines matching /%s/ from %s\n' "$re" "$CONFIG"; return 0; fi
  sed -i -E "/${re}/d" "$CONFIG"
}
# append a line unless it is already present verbatim
cfg_add() {
  local line="$1"
  if grep -qxF -- "$line" "$CONFIG" 2>/dev/null; then return 0; fi
  if [ "$DRY_RUN" = 1 ]; then printf '  [dry-run] would append to %s: %s\n' "$CONFIG" "$line"; return 0; fi
  printf '%s\n' "$line" >> "$CONFIG"
}

# ============================================================ 1. packages ---
log "Installing dependencies"
run apt-get update -q

# Package names verified against the Debian 13 (trixie) arm64 package index.
# libfreetype6-dev no longer exists in trixie (it is libfreetype-dev there),
# which is what made the original apt line fail on Pi OS 6 (issue #18).
# fonts-dejavu-core is NOT in Raspberry Pi OS Lite, but the panel program asks
# PIL for /usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf. Without it PIL
# raises "OSError: cannot open resource" and the OLED service crash-loops.
# (The package now also falls back to Pillow's built-in font, so a missing font
# is a smaller font rather than a dead service.)
CORE_PKGS="git cmake scons python3-dev python3-pip python3-pil python3-psutil libjpeg-dev zlib1g-dev libfreetype-dev liblcms2-dev libopenjp2-7 libtiff-dev i2c-tools python3-smbus python3-luma.oled fonts-dejavu-core"
# shellcheck disable=SC2086
apt_i $CORE_PKGS || {
  warn "bulk install failed; retrying one by one so one bad name cannot block the rest"
  for p in $CORE_PKGS; do apt_i "$p" || warn "could not install '$p' (continuing)"; done
}
for g in gpio i2c spi video; do
  getent group "$g" >/dev/null 2>&1 && run usermod -aG "$g" "$TARGET_USER"
done
ok "granted $TARGET_USER access to the gpio/i2c/spi/video groups (where present)"

# ========================================================== 2. package -------
# The vendor's panel was a 120-line script copied out of luma.examples by
# heredoc, driven by a shell loop that spawned and killed a python process every
# 10 seconds - which is what left an orphaned renderer behind when the service
# stopped. The minitower package replaces both halves with two supervised
# programs and a single configuration file.
log "Installing the minitower package (LED driver + panel driver)"
run install -d -m 755 /etc/minitower
if [ "$DRY_RUN" = 0 ] && [ ! -f /etc/minitower/config.toml ]; then
  install -m 644 "$SCRIPT_DIR/config.toml.example" /etc/minitower/config.toml
  ok "wrote /etc/minitower/config.toml (defaults match the ZP-0130; edit to taste)"
fi
# The runtime libraries come from apt (python3-luma.oled, python3-psutil,
# python3-pil), so pip is told not to duplicate them into /usr/local.
run python3 -m pip install --break-system-packages --no-deps "$SCRIPT_DIR"

# ============================================================= 3. LEDs -------
case "$LED_MODE" in
  driver)
    # rpi-ws281x is not packaged for Debian, so the Python binding comes from
    # pip. It compiles the C library against the kernel headers (python3-dev is
    # already in CORE_PKGS) and has no other dependencies.
    log "Installing the WS281X Python binding (rpi-ws281x)"
    run python3 -m pip install --break-system-packages rpi-ws281x
    ;;
  moodlight)
    log "Building the vendor moodlight binary (jgarff/rpi_ws281x)"
    if [ "$DRY_RUN" = 1 ]; then
      printf '  [dry-run] build rpi_ws281x with scons+cmake and install to %s\n' "$MOODLIGHT_BIN"
    elif [ -x "$MOODLIGHT_BIN" ]; then
      ok "$MOODLIGHT_BIN already present, skipping build"
    else
      rm -rf /tmp/rpi_ws281x
      if git clone --depth 1 https://github.com/jgarff/rpi_ws281x /tmp/rpi_ws281x; then
        if ( cd /tmp/rpi_ws281x && scons && mkdir -p build && cd build \
             && cmake -D BUILD_SHARED=OFF -D BUILD_TEST=ON .. && make ); then
          install -m 755 /tmp/rpi_ws281x/build/test "$MOODLIGHT_BIN" && ok "installed $MOODLIGHT_BIN"
        else
          warn "moodlight build failed - RGB lights stay dark (try --leds custom)"
        fi
      else
        warn "could not clone rpi_ws281x - RGB lights stay dark"
      fi
    fi
    ;;
  custom)
    log "Installing custom LED scripts (Adafruit CircuitPython stack)"
    if [ -d "$SCRIPT_DIR/custom_scripts" ]; then
      run install -d -m 755 "$PREFIX/custom"
      for f in "$SCRIPT_DIR/custom_scripts"/*.py "$SCRIPT_DIR/custom_scripts"/*.sh; do
        [ -e "$f" ] || continue
        run install -m 755 "$f" "$PREFIX/custom/"
      done
      # scripts captured on another machine may carry hardcoded home paths
      [ "$DRY_RUN" = 0 ] && sed -i "s|/home/pi|$HOME_DIR|g" "$PREFIX/custom"/*.sh "$PREFIX/custom"/*.py 2>/dev/null || true
      ok "custom scripts installed into $PREFIX/custom"
    else
      warn "custom_scripts/ not found in this checkout"
    fi
    if [ "$DRY_RUN" = 1 ]; then
      printf '  [dry-run] pip3 install --break-system-packages adafruit-blinka adafruit-circuitpython-neopixel rpi-ws281x\n'
    else
      pip3 install --break-system-packages --quiet \
        adafruit-blinka adafruit-circuitpython-neopixel rpi-ws281x \
        || warn "pip install of the Adafruit LED stack failed"
    fi
    ;;
  none) warn "LEDs left as-is (--leds none)" ;;
esac

# ============================================================== 4. fan -------
if [ "$FAN_GPIO" = "none" ]; then
  warn "fan control skipped (--no-fan)"
else
  log "Configuring the V2 4-wire fan on GPIO$FAN_GPIO via the pwm-gpio-fan overlay"
  [ -f "$(dirname "$CONFIG")/overlays/pwm-gpio-fan.dtbo" ] \
    || warn "pwm-gpio-fan.dtbo not found for this kernel - fan control needs it"
  if [ "$DRY_RUN" = 0 ] && [ ! -f "$CONFIG.premintower" ]; then
    cp -a "$CONFIG" "$CONFIG.premintower" && log "saved the original config.txt as $CONFIG.premintower"
  fi
  cfg_drop '^dtoverlay=pwm-gpio-fan.*'
  # config.txt applies the LAST section header to everything that follows, so if
  # the file currently ends inside e.g. [cm4] our settings would be ignored on
  # every other model. Make sure we append into [all].
  last_section="$(grep -E '^\[' "$CONFIG" 2>/dev/null | tail -1 | tr -d '[:space:]')"
  if [ -n "$last_section" ] && [ "$last_section" != "[all]" ]; then
    log "config.txt ends in section $last_section - inserting [all] before our settings"
    cfg_add '[all]'
  fi
  cfg_add '# --- Mini Tower NAS V2 fan (4-wire PWM). fan_gpio must stay 14:'
  cfg_add '# --- pin 18 is the WS281X LED pin used by the RGB light + mood light.'
  cfg_add "dtoverlay=pwm-gpio-fan,fan_gpio=${FAN_GPIO},fan_temp0=50000,fan_temp1=55000,fan_temp2=60000,fan_temp3=65000,fan_temp0_speed=90,fan_temp1_speed=140,fan_temp2_speed=200,fan_temp3_speed=255"
  ok "fan temperature curve added (the cooling device appears after reboot)"
fi

# ============================================================== 5. I2C -------
log 'Enabling I2C for the 0.96" SSD1306 OLED (address 0x3C)'
cfg_drop '^dtparam=i2c_arm(=.*)?$'
cfg_drop '^dtparam=i2c=(on|off|0|1)$'
cfg_add 'dtparam=i2c_arm=on'

# dtparam=i2c_arm=on only brings up the bus CONTROLLER (i2c_bcm2835). The
# /dev/i2c-N character device that luma.oled - and every userspace I2C tool -
# opens comes from the i2c-dev module, which Raspberry Pi OS Trixie LITE does
# not load by default, and which the original installer never added either.
# Without it the OLED can never initialise, which is almost certainly the real
# cause of upstream issue #16 ("RGB turned on, but OLED does not display
# anything").
if [ "$DRY_RUN" = 1 ]; then
  printf '  [dry-run] would write /etc/modules-load.d/i2c-dev.conf and modprobe i2c-dev\n'
else
  printf 'i2c-dev\n' > /etc/modules-load.d/i2c-dev.conf
  modprobe i2c-dev 2>/dev/null || true
  ok "i2c-dev will load at boot via /etc/modules-load.d/i2c-dev.conf"
fi

# =========================================================== 6. services ----
UNIT_DIR=/etc/systemd/system
log "Installing systemd units into $UNIT_DIR"
run install -m 644 "$SCRIPT_DIR/systemd_files/minitower_oled.service" "$UNIT_DIR/minitower_oled.service"
case "$LED_MODE" in
  driver)
    # The shipped unit runs minitower-leds from the package installed above.
    run install -m 644 "$SCRIPT_DIR/systemd_files/minitower_moodlight.service" "$UNIT_DIR/minitower_moodlight.service"
    ;;
  moodlight)
    # Legacy: the vendor's compiled demo binary. Reuse the shipped unit file so
    # it keeps the hardening comments, but point it at the old binary.
    run install -m 644 "$SCRIPT_DIR/systemd_files/minitower_moodlight.service" "$UNIT_DIR/minitower_moodlight.service"
    [ "$DRY_RUN" = 0 ] && sed -i "s|^ExecStart=.*|ExecStart=$MOODLIGHT_BIN|" "$UNIT_DIR/minitower_moodlight.service" || true
    warn "--leds moodlight is the legacy vendor demo (an 8x8 matrix animation at 15 fps); --leds driver is the supported path"
    ;;
  custom)
    if [ "$DRY_RUN" = 1 ]; then
      printf '  [dry-run] would write minitower_moodlight.service running %s/custom/led_rainbow.py\n' "$PREFIX"
    else
      cat > "$UNIT_DIR/minitower_moodlight.service" <<EOF
[Unit]
Description=Minitower moodlight (custom script)
After=multi-user.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
ExecStart=/usr/bin/python3 $PREFIX/custom/led_rainbow.py
Restart=always
RestartSec=30
User=root

[Install]
WantedBy=multi-user.target
EOF
    fi
    ;;
esac
# upstream shipped these units mode 755; systemd warns about that in dmesg
[ "$DRY_RUN" = 0 ] && chmod 644 "$UNIT_DIR"/minitower_*.service 2>/dev/null || true

run systemctl daemon-reload
case "$LED_MODE" in
  driver|moodlight|custom) run systemctl enable minitower_moodlight.service ;;
  none)                    run systemctl disable minitower_moodlight.service 2>/dev/null || true ;;
esac
run systemctl enable minitower_oled.service

if [ "$DRY_RUN" = 0 ]; then
  case "$LED_MODE" in
    driver|moodlight|custom) systemctl restart minitower_moodlight.service \
      || warn "the LED service did not start (journalctl -u minitower_moodlight -e)" ;;
  esac
  systemctl restart minitower_oled.service \
    || warn "OLED service did not start (journalctl -u minitower_oled -e)"
fi

# ========================================================= 7. verification ---
log "Verification"
if [ "$DRY_RUN" = 0 ]; then
  if i2cdetect -y 1 2>/dev/null | grep -q ' 3c '; then
    ok "OLED detected at 0x3C on i2c-1"
  else
    warn "nothing at 0x3C - if /dev/i2c-1 is missing, i2c-dev did not load yet; a reboot will fix it"
  fi
  if ls /sys/class/thermal/cooling_device*/type >/dev/null 2>&1; then
    ok "fan cooling device registered"
  else
    warn "no cooling device yet - expected until you reboot with the new overlay"
  fi
  systemctl --failed --no-legend 2>/dev/null | grep -q minitower \
    && warn "a minitower unit is failed: journalctl -u minitower_oled -e"
fi

printf '\n'
ok "Install finished."
echo "    panel/LEDs  : minitower-panel + minitower-leds (config /etc/minitower/config.toml)"
echo "    LED mode    : $LED_MODE"
echo "    fan         : $([ "$FAN_GPIO" = none ] && echo disabled || echo "pwm-gpio-fan on GPIO$FAN_GPIO")"
echo "    config.txt  : $CONFIG (original kept as $CONFIG.premintower)"
printf '\n'

if [ "$DO_REBOOT" = 1 ]; then
  log "Rebooting in 5 seconds (Ctrl-C to abort)"
  sleep 5
  run systemctl reboot
else
  warn "Reboot for the I2C and fan changes to take effect:  sudo reboot"
fi

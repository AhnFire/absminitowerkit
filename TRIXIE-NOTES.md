# Trixie support for the ABS Mini Tower Kit

A fork of [geeekpi/absminitowerkit](https://github.com/geeekpi/absminitowerkit)
that works on **Raspberry Pi OS Trixie (Debian 13)** as well as Bookworm, and
that finally enables the **V2 4-wire fan speed control**.

Everything below was verified on a real Pi 4 Model B (8 GB) with a
**ZP-0130-4wire** kit (TEAM TM8PS7002T 2 TB M.2 SATA on the ASM1153E bridge,
0.96" SSD1306 OLED at I2C 0x3C, WS281X RGB fan light + mood light on GPIO18).

## Quick start

```bash
git clone https://github.com/AhnFire/absminitowerkit.git
cd absminitowerkit
sudo ./install_trixie.sh --dry-run     # see exactly what it will do
sudo ./install_trixie.sh               # then do it
sudo reboot
```

Options: `--user NAME` (defaults to `$SUDO_USER`), `--leds moodlight|custom|none`,
`--fan-gpio N` (default 14), `--no-fan`, `--prefix DIR`, `--reboot`, `--dry-run`.

## What was wrong with `install_bookworm.sh`

| # | Problem in the original | Fix here |
|---|---|---|
| 1 | **It rewrote `/etc/resolv.conf`**: commented out every existing `nameserver` and appended `114.114.114.114` + `8.8.8.8`, hijacking DNS away from your router | never touches `resolv.conf` |
| 2 | **Hardcoded the `pi` user** (`usermod -a -G gpio,i2c pi`), so a custom username silently got no hardware access | uses `$SUDO_USER` or `--user` |
| 3 | **`libfreetype6-dev` no longer exists in Trixie** (it is `libfreetype-dev`), so its apt line fails there - this is [issue #18](https://github.com/geeekpi/absminitowerkit/issues/18) | correct names for trixie **and** bookworm, and installs packages one-by-one so one bad name cannot abort the whole run |
| 4 | **`pip3 install -e /tmp/luma.examples`** - an editable install inside `/tmp`, which `systemd-tmpfiles-clean.timer` deletes daily, leaving a dangling package (it shows up as `luma.examples 0.0.0 /tmp/luma.examples` in `pip3 list`) | `python3-luma.oled` from apt; `luma.examples` cloned to a persistent path |
| 5 | **Broken systemd unit semantics**: `sudo` inside `ExecStart`, `RemainAfterExit=yes` with `Type=simple` (unit reports `active (exited)` while nothing runs), `DefaultDependencies=no` (starts before `multi-user.target`/`/home`), and default 100 ms restart delay causing "Start request repeated too quickly" - see [issue #15](https://github.com/geeekpi/absminitowerkit/issues/15), where the reporter also mentions **"im using a custom username instead of pi"** | cleaned units in `systemd_files/`, mode 644 |
| 6 | **No fan control at all**, even though the V2 kit's headline feature is an adjustable 4-wire fan; the userspace PWM examples circulating for this kit burn >10% CPU - [issue #17](https://github.com/geeekpi/absminitowerkit/issues/17) | kernel `pwm-gpio-fan` overlay on GPIO14, ~0 CPU, survives reboots |
| 7 | Always reboots the machine at the end, and config.txt edits are not idempotent | `--reboot` to opt in, idempotent edits, original saved to `config.txt.premintower` |

## The fan, properly

The V2 fan's PWM wire is **GPIO14 (physical pin 8)**. GPIO14 is not a hardware
PWM pin, and GPIO18 is already taken by the WS281X LED driver, so the right tool
is the kernel overlay documented in your own
`/boot/firmware/overlays/README` under `pwm-gpio-fan`.

```
dtoverlay=pwm-gpio-fan,fan_gpio=14,fan_temp0=50000,fan_temp1=55000,fan_temp2=60000,fan_temp3=65000,fan_temp0_speed=90,fan_temp1_speed=140,fan_temp2_speed=200,fan_temp3_speed=255
```

> **`fan_gpio` must be passed explicitly.** The overlay defaults to **18** -
> the WS281X LED pin. If you load `dtoverlay=pwm-gpio-fan` bare, fan control
> and the RGB light fight over one pin.

Once loaded the kernel registers a cooling device, so there is no daemon,
no script, and no CPU cost:

```bash
cat /sys/class/thermal/cooling_device*/type        # -> pwm-fan
cat /sys/class/thermal/cooling_device*/cur_state   # 0-4, follows the curve
```

See `config.txt.example` for tuning notes and related overlays
(`gpio-fan` for simple on/off, `i2c-fan` for I2C controller chips).

## What is preserved

Unchanged from upstream so existing installs keep working:

* `democ_code/demo_opts.py`, `democ_code/sysinfo.py`, `democ_code/moodlight`
* `install_bookworm.sh` (left alone; use `install_trixie.sh` on Pi OS 6)
* the OLED display layout and the `minitower_*` service names the 52Pi wiki
  refers to

## Notes

* Companion hardware docs: <https://wiki.52pi.com/index.php?title=ZP-0130-4wire>
* Upstream issues this addresses: [#15](https://github.com/geeekpi/absminitowerkit/issues/15),
  [#16](https://github.com/geeekpi/absminitowerkit/issues/16),
  [#17](https://github.com/geeekpi/absminitowerkit/issues/17),
  [#18](https://github.com/geeekpi/absminitowerkit/issues/18)
* `uninstall_trixie.sh` reverses everything this script did, including the
  config.txt lines (the original `uninstall.sh` does not know about them).

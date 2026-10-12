"""Read-only system facts used by the status pages.

Every function here is defensive: it returns None (or a safe default) rather
than raising, because a monitoring display must never be the thing that takes a
service down. That behaviour is also what upstream's `wlan0` bug taught us -
the original code assumed one network topology and silently skipped two lines
when the assumption was wrong.
"""

from __future__ import annotations

import os
import socket
import subprocess
from pathlib import Path

#: Interfaces that are never the "real" uplink.
VIRTUAL_IFACE_PREFIXES = ("lo", "docker", "br-", "veth", "virbr", "tun", "tap", "wg", "zt")

_THERMAL_ZONE = Path("/sys/class/thermal/thermal_zone0/temp")

#: Meaning of the bits vcgencmd reports in `get_throttled`.
_THROTTLE_BITS = {
    0: "undervoltage now",
    1: "ARM frequency capped now",
    2: "throttled now",
    3: "soft temperature limit now",
    16: "undervoltage has occurred",
    17: "ARM frequency has been capped",
    18: "throttling has occurred",
    19: "soft temperature limit has occurred",
}


def _run(args: list[str], timeout: float = 3.0) -> str | None:
    """Run a command without a shell, returning stdout or None on any failure."""
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def default_iface() -> str | None:
    """The interface carrying the IPv4 default route.

    Falls back to the first physical-looking interface that holds a global IPv4
    address, so a container bridge can never be mistaken for the uplink.
    """
    route = _run(["/usr/sbin/ip", "-4", "route", "show", "default"]) or _run(
        ["ip", "-4", "route", "show", "default"]
    )
    if route:
        words = route.split()
        if "dev" in words:
            return words[words.index("dev") + 1]

    try:
        import psutil

        for name, addresses in psutil.net_if_addrs().items():
            if name.startswith(VIRTUAL_IFACE_PREFIXES):
                continue
            for addr in addresses:
                if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                    return name
    except Exception:
        pass
    return None


def primary_ipv4() -> str | None:
    """First global IPv4 address, via the kernel rather than DNS."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            # No packets are sent; this only asks the kernel which source
            # address it would pick.
            sock.connect(("192.0.2.1", 9))
            return sock.getsockname()[0]
    except OSError:
        return None


def net_counters(iface: str | None) -> tuple[int, int] | None:
    """(bytes_sent, bytes_received) for an interface, or None."""
    if not iface:
        return None
    try:
        import psutil

        counters = psutil.net_io_counters(pernic=True).get(iface)
    except Exception:
        return None
    if counters is None:
        return None
    return counters.bytes_sent, counters.bytes_recv


def bytes2human(count: float) -> str:
    """Compact byte count, e.g. 1536 -> '1K'."""
    for unit in ("K", "M", "G", "T", "P", "E", "Z", "Y"):
        count /= 1024.0
        if count < 1024.0:
            return f"{int(count)}{unit}"
    return f"{int(count)}Z"


def load_average() -> tuple[float, float, float]:
    try:
        return os.getloadavg()
    except OSError:
        return (0.0, 0.0, 0.0)


def uptime_seconds() -> float:
    try:
        return float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, IndexError, ValueError):
        return 0.0


def uptime_human(seconds: float | None = None) -> str:
    seconds = uptime_seconds() if seconds is None else seconds
    minutes, hours, days = int(seconds // 60), int(seconds // 3600), int(seconds // 86400)
    if days:
        return f"{days}d {hours % 24}h"
    if hours:
        return f"{hours}h {minutes % 60}m"
    return f"{minutes}m"


def memory() -> tuple[int, int]:
    """(used_bytes, total_bytes)."""
    try:
        import psutil

        usage = psutil.virtual_memory()
        return usage.used, usage.total
    except Exception:
        return (0, 0)


def disk(path: str = "/") -> tuple[int, int]:
    """(used_bytes, total_bytes) for a mount point."""
    try:
        import psutil

        usage = psutil.disk_usage(path)
        return usage.used, usage.total
    except Exception:
        return (0, 0)


def cpu_temperature_c() -> float | None:
    try:
        return int(_THERMAL_ZONE.read_text().strip()) / 1000.0
    except (OSError, ValueError):
        return None


def arm_clock_mhz() -> int | None:
    """Current ARM clock in MHz (vcgencmd measures in Hz)."""
    out = _run(["vcgencmd", "measure_clock", "arm"])
    if not out or "=" not in out:
        return None
    try:
        return int(out.split("=", 1)[1]) // 1_000_000
    except ValueError:
        return None


def throttled() -> str | None:
    """The raw vcgencmd get_throttled value, e.g. '0x50000'."""
    out = _run(["vcgencmd", "get_throttled"])
    if not out or "=" not in out:
        return None
    return out.split("=", 1)[1].strip()


def throttled_reasons(value: str | None) -> list[str]:
    """Decode a get_throttled value into human-readable events.

    An empty list means nothing has happened; a non-empty list is worth showing,
    because these are sticky bits that survive across boots.
    """
    if not value:
        return []
    try:
        flags = int(value, 16)
    except ValueError:
        return []
    return [label for bit, label in _THROTTLE_BITS.items() if flags & (1 << bit)]

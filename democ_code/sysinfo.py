#!/usr/bin/python3
# -*- coding: utf-8 -*-

import os
import socket
import sys
import time
from pathlib import Path
from datetime import datetime
from demo_opts import get_device
from luma.core.render import canvas
from PIL import ImageFont
import psutil
import subprocess as sp


def bytes2human(n):
    symbols = ('K', 'M', 'G', 'T', 'P', 'E', 'Z', 'Y')
    prefix = {}
    for i, s in enumerate(symbols):
        prefix[s] = 1 << (i + 1) * 10
    for s in reversed(symbols):
        if n >= prefix[s]:
            value = int(float(n) / prefix[s])
            return '%s%s' % (value, s)
    return "%sB" % n


def default_iface():
    # The Mini Tower is frequently used headless over Ethernet, so do not assume
    # wlan0. The original code called network('wlan0') inside a try/except
    # KeyError, so on a wired Pi the exception skipped the IP line as well.
    # Prefer the interface that carries the IPv4 default route.
    try:
        route = sp.getoutput("ip -4 route show default").split()
        if "dev" in route:
            return route[route.index("dev") + 1]
    except Exception:
        pass
    # Fallback: first physical-looking interface with a global IPv4 address.
    # Skip loopback, docker/virtual bridges and tunnels so a container network
    # cannot be picked instead of the real uplink.
    skip = ("lo", "docker", "br-", "veth", "virbr", "tun", "tap", "wg", "zt")
    try:
        for name, addrs in psutil.net_if_addrs().items():
            if name.startswith(skip):
                continue
            for a in addrs:
                if a.family == socket.AF_INET and not a.address.startswith("127."):
                    return name
    except Exception:
        pass
    return None


NET_IFACE = default_iface()


def cpu_usage():
    # load average
    av1, av2, av3 = os.getloadavg()
    return "Ld:%.1f %.1f %.1f" % (av1, av2, av3)


def uptime_usage():
    # uptime, Ip
    # uptime = datetime.now() - datetime.fromtimestamp(psutil.boot_time())
    ip = sp.getoutput("hostname -I").split(' ')[0]
    return "IP:%s" % (ip)


def mem_usage():
    usage = psutil.virtual_memory()
    return "Mem:%s %.0f%%" % (bytes2human(usage.used), 100 - usage.percent)


def disk_usage(dir):
    usage = psutil.disk_usage(dir)
    return "SD:%s %.0f%%" % (bytes2human(usage.used), usage.percent)


def network(iface):
    if not iface:
        return "net: unavailable"
    stat = psutil.net_io_counters(pernic=True).get(iface)
    if stat is None:
        return "%s: unavailable" % iface
    return "%s: Tx: %s,Rx: %s" % (iface, bytes2human(stat.bytes_sent), bytes2human(stat.bytes_recv))


def status_font(size=11):
    # Raspberry Pi OS Lite does not ship the DejaVu fonts, and PIL raises
    # "OSError: cannot open resource" for a missing path - which crash-looped the
    # OLED service outright. Fall back to Pillow's built-in bitmap font instead.
    font_path = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'
    try:
        return ImageFont.truetype(font_path, size)
    except OSError:
        return ImageFont.load_default()


def stats(device):
    font2 = status_font(11)

    with canvas(device) as draw:
        draw.text((0, 1), cpu_usage(), font=font2, fill="white")
        if device.height >= 32:
            draw.text((0, 12), mem_usage(), font=font2, fill="white")

        if device.height >= 64:
            draw.text((0, 24), disk_usage('/'), font=font2, fill="white")
            draw.text((0, 36), network(NET_IFACE), font=font2, fill="white")
            draw.text((0, 48), uptime_usage(), font=font2, fill="white")


device = get_device()

while True:
    stats(device)
    time.sleep(5)

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

"""Tray icon drawn in code, so its colour can carry the connection state.

⚠️ WHY NOT JUST CHANGE `IconName`. A themed icon name is rendered by the panel
in the panel's own colour -- that is the point of symbolic icons, and it means
a theme name can say *which* icon but never *what colour*. The StatusNotifierItem
spec leaves exactly one route to a colour we choose: `IconPixmap`, an ARGB
bitmap we supply.

The bitmap format is the fiddly part and it is easy to get subtly wrong:

    array of (width, height, bytes) with the bytes in ARGB32, **network byte
    order** -- big-endian, which is the opposite of what cairo hands back on
    every machine this runs on.

Cairo's ARGB32 is native-endian premultiplied, so on x86/ARM the four bytes
come out as B, G, R, A and have to be reversed per pixel. Skipping that step
produces an icon that looks plausible in one panel and has swapped colours in
another, depending on how forgiving the host is -- which is the worst kind of
bug to chase.

Two sizes are published (22 and 32 px). Hosts pick what suits their scaling;
offering one size makes the icon blurry on HiDPI panels.
"""

import math
import struct

import cairo
import dbus

# Deliberately muted: a tray icon that shouts is a tray icon people remove.
# The connected colour is a desaturated green that stays legible on both light
# and dark panels; disconnected is a mid grey that reads as "present, idle"
# rather than "broken".
_CONNECTED = (0.36, 0.72, 0.45)
_IDLE = (0.55, 0.55, 0.58)
_SIZES = (22, 32)


def _draw(size: int, rgb: tuple[float, float, float]) -> bytes:
    """A headphone glyph: a headband arc and two ear cups."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(surface)
    r, g, b = rgb
    cr.set_source_rgba(r, g, b, 1.0)

    unit = size / 22.0
    cr.set_line_width(2.0 * unit)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)

    # Headband: a half circle across the top.
    cr.arc(size / 2, size * 0.55, size * 0.34, math.pi, 2 * math.pi)
    cr.stroke()

    # Ear cups: rounded rectangles at each end of the band.
    cup_w = size * 0.16
    cup_h = size * 0.28
    for cx in (size / 2 - size * 0.34, size / 2 + size * 0.34):
        x = cx - cup_w / 2
        y = size * 0.55 - cup_h * 0.15
        rad = cup_w / 2
        cr.new_sub_path()
        cr.arc(x + cup_w - rad, y + rad, rad, -math.pi / 2, 0)
        cr.arc(x + cup_w - rad, y + cup_h - rad, rad, 0, math.pi / 2)
        cr.arc(x + rad, y + cup_h - rad, rad, math.pi / 2, math.pi)
        cr.arc(x + rad, y + rad, rad, math.pi, 3 * math.pi / 2)
        cr.close_path()
        cr.fill()

    surface.flush()
    return bytes(surface.get_data()), surface.get_stride()


def _to_network_argb(raw: bytes, width: int, height: int, stride: int) -> bytes:
    """Cairo's native-endian BGRA → the spec's big-endian ARGB, row by row.

    Also drops any row padding: cairo aligns strides to 4 bytes, the wire
    format does not.
    """
    out = bytearray(width * height * 4)
    o = 0
    for y in range(height):
        row = y * stride
        for x in range(width):
            p = row + x * 4
            bb, gg, rr, aa = raw[p], raw[p + 1], raw[p + 2], raw[p + 3]
            struct.pack_into("BBBB", out, o, aa, rr, gg, bb)
            o += 4
    return bytes(out)


def pixmaps(connected: bool) -> dbus.Array:
    """The `IconPixmap` value for the current state."""
    rgb = _CONNECTED if connected else _IDLE
    entries = []
    for size in _SIZES:
        raw, stride = _draw(size, rgb)
        data = _to_network_argb(raw, size, size, stride)
        entries.append(
            dbus.Struct(
                (dbus.Int32(size), dbus.Int32(size), dbus.ByteArray(data)),
                signature="iiay",
            )
        )
    return dbus.Array(entries, signature="(iiay)")

#!/usr/bin/env python3
# Whisper Vox - voice dictation.
# Copyright (C) 2026 Pekelni Boroshna Lab.
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License v3.0 as published by the Free
# Software Foundation. It comes with NO WARRANTY. See <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

"""Every icon the app ships, from one drawing, and a record of how.

The source is generated artwork: a rounded square on a black background, with
the edge speckled by compression. Three things happen to it before either
platform sees it, and each was a visible fault:

  1. The black surround comes off. It is flood-filled from the corners, so only
     the CONNECTED background goes: the dark blues inside the microphone mesh
     stay exactly as they are. Keying every dark pixel would have eaten them.

  2. Colour is pulled back. Measured on the source: saturation averaged 0.68
     against a brightness of 0.94 - both near the ceiling at once, which is
     what reads as "acid". Saturation is scaled down, brightness is compressed
     ONLY where colour is strong (so the white microphone stays white), and the
     hues are pulled toward their own circular average to narrow the spread.

  3. The shape is cut with a superellipse, not an arc - the corner every OS has
     used since about 2013.

Then the two platforms want different geometry, and this is the part that is
easy to get wrong by shipping one file to both:

  macOS  - the shape is 824x824 inside a 1024 canvas. A Mac icon is not
           full-bleed; the margin is part of Apple's grid, and filling the
           canvas edge to edge is the most obvious way to look foreign.
  Windows - full-bleed. Windows has no such grid, and an icon carrying Apple's
           margin just looks smaller than everything beside it in the taskbar.

Run:  .venv/bin/python tools/make-icons.py [--preview]
"""
import argparse
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, 'assets', 'wv-logo-source.png')

MAC_MASTER = os.path.join(ROOT, 'assets', 'wv-logo-1024.png')
WIN_ICO = os.path.join(ROOT, 'assets', 'wv-logo.ico')
LOGO_PNG = os.path.join(ROOT, 'assets', 'wv-logo.png')     # tray + fallback
WEB_PNG = os.path.join(ROOT, 'web', 'wv-logo.png')         # About tab

CANVAS = 1024          # Apple's macOS icon canvas
BODY = 824             # the shape inside it - the rest is deliberate margin
SUPERELLIPSE_N = 5.0   # |x|^n + |y|^n = 1; n=5 is the usual squircle stand-in

# Every size Windows asks for, including the 20/40/96 it uses at scaled DPI and
# in the larger Explorer views. Leaving those out makes Windows downscale a
# bigger one on the fly, which is exactly where an icon turns to mush.
ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]
SHARPEN_UP_TO = 48     # below this, a downscale needs help to stay readable

SATURATION = 0.78      # 0.68 -> ~0.54
VALUE_PULL = 0.12      # highlight compression, scaled BY saturation
HUE_PULL = 0.40        # how far each hue moves toward the average


def load_source():
    if not os.path.isfile(SOURCE):
        sys.exit(f'No source artwork at {SOURCE}')
    return Image.open(SOURCE).convert('RGB')


def cut_background(rgb):
    """Alpha from the connected black surround, not from darkness itself."""
    marker = (255, 0, 255)
    scratch = rgb.copy()
    width, height = scratch.size
    for corner in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        if sum(scratch.getpixel(corner)) < 150:      # still background, not art
            ImageDraw.floodfill(scratch, corner, marker, thresh=60)
    keyed = np.array(scratch)
    background = np.all(keyed == np.array(marker, dtype=np.uint8), axis=-1)
    return Image.fromarray(np.where(background, 0, 255).astype(np.uint8), mode='L')


def superellipse(size, n=SUPERELLIPSE_N, supersample=4):
    """The corner is a continuous curve, not a quarter circle."""
    big = size * supersample
    axis = (np.arange(big) + 0.5) / big * 2 - 1          # -1..1 across the square
    inside = (np.abs(axis)[None, :] ** n + np.abs(axis)[:, None] ** n) <= 1.0
    mask = Image.fromarray((inside * 255).astype(np.uint8), mode='L')
    return mask.resize((size, size), Image.LANCZOS)      # supersampled edge


def correct_colour(rgba):
    """Pull saturation and highlights back; narrow the spread of hues."""
    import colorsys
    array = np.array(rgba).astype(np.float32) / 255.0
    r, g, b, a = array[..., 0], array[..., 1], array[..., 2], array[..., 3]

    maximum, minimum = np.max(array[..., :3], axis=-1), np.min(array[..., :3], axis=-1)
    value = maximum
    span = maximum - minimum
    saturation = np.where(maximum > 0, span / np.maximum(maximum, 1e-6), 0)

    hue = np.zeros_like(value)
    safe = span > 1e-6
    red_max = safe & (maximum == r)
    green_max = safe & (maximum == g) & ~red_max
    blue_max = safe & (maximum == b) & ~red_max & ~green_max
    hue[red_max] = ((g - b)[red_max] / span[red_max]) % 6
    hue[green_max] = (b - r)[green_max] / span[green_max] + 2
    hue[blue_max] = (r - g)[blue_max] / span[blue_max] + 4
    hue = hue / 6.0

    # Average hue of the pixels that actually carry colour, on the circle - a
    # plain mean would put the average of 350 and 10 degrees at 180.
    visible = (a > 0.5) & (saturation > 0.15)
    angles = hue[visible] * 2 * math.pi
    centre = math.atan2(np.sin(angles).mean(), np.cos(angles).mean()) / (2 * math.pi) % 1.0

    offset = (hue - centre + 0.5) % 1.0 - 0.5            # shortest way round
    hue = (centre + offset * (1 - HUE_PULL)) % 1.0
    saturation = saturation * SATURATION
    value = value * (1 - VALUE_PULL * saturation)        # white stays white

    to_rgb = np.vectorize(colorsys.hsv_to_rgb)
    r2, g2, b2 = to_rgb(hue, saturation, value)
    out = np.stack([r2, g2, b2, a], axis=-1)
    return Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8), mode='RGBA')


def measure(rgba, label):
    array = np.array(rgba).astype(np.float32) / 255.0
    a = array[..., 3]
    maximum = np.max(array[..., :3], axis=-1)
    minimum = np.min(array[..., :3], axis=-1)
    saturation = np.where(maximum > 0, (maximum - minimum) / np.maximum(maximum, 1e-6), 0)
    keep = (a > 0.5) & (saturation > 0.15)
    print(f'  {label:<9} saturation {saturation[keep].mean():.2f}   '
          f'brightness {maximum[keep].mean():.2f}')


def build_body():
    """The finished artwork at 1024, cut out, corrected and squircled."""
    source = load_source()
    print(f'source: {source.size[0]}x{source.size[1]}')

    art = source.copy()
    art.putalpha(cut_background(source))
    art = art.crop(art.getchannel('A').getbbox())        # tight to the shape
    body = art.resize((CANVAS, CANVAS), Image.LANCZOS)

    measure(body, 'before')
    body = correct_colour(body)
    measure(body, 'after')

    body.putalpha(Image.fromarray(np.minimum(
        np.array(body.getchannel('A')), np.array(superellipse(CANVAS)))))
    return body


def scaled(body, size):
    """One size, with a little sharpening where a plain downscale goes soft."""
    out = body.resize((size, size), Image.LANCZOS)
    if size <= SHARPEN_UP_TO:
        out = out.filter(ImageFilter.UnsharpMask(radius=0.6, percent=70, threshold=2))
    return out


def build():
    body = build_body()

    # macOS: Apple's grid - the shape does not touch the canvas.
    margin = (CANVAS - BODY) // 2
    mac = Image.new('RGBA', (CANVAS, CANVAS), (0, 0, 0, 0))
    shrunk = body.resize((BODY, BODY), Image.LANCZOS)
    mac.paste(shrunk, (margin, margin), shrunk)
    mac.save(MAC_MASTER)
    print(f'\n  {os.path.relpath(MAC_MASTER, ROOT):<28} '
          f'{CANVAS}x{CANVAS}, {BODY}px body, {margin}px margin')

    # Windows: full-bleed, every size baked in rather than downscaled at runtime.
    frames = [scaled(body, size) for size in ICO_SIZES]
    frames[-1].save(WIN_ICO, format='ICO',
                    sizes=[(s, s) for s in ICO_SIZES], append_images=frames[:-1])
    print(f'  {os.path.relpath(WIN_ICO, ROOT):<28} {", ".join(str(s) for s in ICO_SIZES)}')

    # The plain logo: Windows tray icon, and the picture on the About tab.
    logo = scaled(body, 256)
    for path in (LOGO_PNG, WEB_PNG):
        logo.save(path)
        print(f'  {os.path.relpath(path, ROOT):<28} 256x256')
    return mac, body


def preview(mac, body):
    """Both icons at the sizes each OS shows, on a light and a dark ground.

    Two grounds because that is where a too-bright icon gives itself away: a
    Dock or taskbar on a dark wallpaper is exactly where the old one glowed.
    """
    old = Image.open(os.path.join(ROOT, 'build', 'icon-old.png')).convert('RGBA') \
        if os.path.isfile(os.path.join(ROOT, 'build', 'icon-old.png')) else None
    rows = [('macOS', mac), ('Windows', body)]
    if old:
        rows.insert(0, ('previous', old))
    sizes = [256, 128, 64, 48, 32, 24, 16]
    pad, gap, label = 24, 20, 18
    row_h = sizes[0] + label
    width = pad * 2 + sum(sizes) + gap * (len(sizes) - 1)
    height = pad * 3 + row_h * len(rows) * 2
    sheet = Image.new('RGBA', (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(sheet)

    for half, ground in enumerate(((246, 247, 250), (28, 30, 34))):
        top = pad + half * (pad + row_h * len(rows))
        draw.rectangle([0, top - pad // 2, width, top + row_h * len(rows) + pad // 2],
                       fill=ground)
        ink = (90, 96, 106) if half == 0 else (150, 158, 170)
        for row, (name, image) in enumerate(rows):
            x, y = pad, top + row * row_h
            draw.text((x, y + sizes[0] + 4), name, fill=ink)
            for size in sizes:
                one = scaled(image, size) if image is not body else scaled(body, size)
                sheet.paste(one, (x, y + sizes[0] - size), one)
                x += size + gap

    path = os.path.join(ROOT, 'build', 'icon-preview.png')
    sheet.convert('RGB').save(path)
    print(f'  {os.path.relpath(path, ROOT):<28} comparison sheet')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', action='store_true',
                        help='also write a before/after sheet at real sizes')
    args = parser.parse_args()
    mac_master, full_bleed = build()
    if args.preview:
        preview(mac_master, full_bleed)

#!/usr/bin/env python3
# Whisper Vox - voice dictation.
# Copyright (C) 2026 Pekelni Boroshna Lab.
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License v3.0 as published by the Free
# Software Foundation. It comes with NO WARRANTY. See <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

"""Turn the drawn logo into a macOS app icon, and record how.

The source is generated artwork: a rounded square sitting on a black
background, with the edge speckled by compression. macOS wants the opposite of
that - a shape cut out of transparency, on Apple's grid, in colours that do not
shout. Three things happen here, and each is worth its own line because each
was a visible fault:

  1. The black surround comes off. It is flood-filled from the corners, so only
     the CONNECTED background goes: the dark blues inside the microphone mesh
     stay exactly as they are. Keying every dark pixel would have eaten them.

  2. The artwork is placed on Apple's grid. A macOS icon is not a full-bleed
     square - the shape is 824x824 inside a 1024 canvas, and the corner is a
     superellipse, not an arc. Filling the canvas edge to edge is the single
     most obvious way to look unlike a Mac app.

  3. Colour is pulled back. Measured on the source: saturation averaged 0.69
     against a brightness of 0.92 - both near the ceiling at once, which is
     what reads as "acid". Saturation is scaled down, brightness is compressed
     ONLY where colour is strong (so the white microphone stays white), and the
     hues are pulled toward their own average to narrow the spread.

Run:  .venv/bin/python tools/make-macos-icon.py [--preview]
"""
import argparse
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, 'assets', 'wv-logo-source.png')
TARGET = os.path.join(ROOT, 'assets', 'wv-logo-1024.png')

CANVAS = 1024          # Apple's macOS icon canvas
BODY = 824             # the shape inside it - the rest is deliberate margin
SUPERELLIPSE_N = 5.0   # |x|^n + |y|^n = 1; n=5 is the usual squircle stand-in

SATURATION = 0.78      # 0.69 -> ~0.54
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
    alpha = np.where(background, 0, 255).astype(np.uint8)
    return Image.fromarray(alpha, mode='L')


def superellipse(size, n=SUPERELLIPSE_N, supersample=4):
    """Apple's corner is a continuous curve, not a quarter circle."""
    big = size * supersample
    axis = (np.arange(big) + 0.5) / big * 2 - 1          # -1..1 across the square
    x = np.abs(axis)[None, :] ** n
    y = np.abs(axis)[:, None] ** n
    inside = (x + y) <= 1.0
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
    print(f'  {label:<10} saturation {saturation[keep].mean():.2f}   '
          f'brightness {maximum[keep].mean():.2f}   '
          f'coloured pixels {keep.sum():,}')


def build():
    source = load_source()
    print(f'source: {source.size[0]}x{source.size[1]}')

    art = source.copy()
    art.putalpha(cut_background(source))
    art = art.crop(art.getchannel('A').getbbox())        # tight to the shape
    print(f'artwork after cutting the background: {art.size[0]}x{art.size[1]}')

    body = art.resize((BODY, BODY), Image.LANCZOS)
    measure(body, 'before')
    body = correct_colour(body)
    measure(body, 'after')

    mask = superellipse(BODY)
    body.putalpha(Image.fromarray(
        np.minimum(np.array(body.getchannel('A')), np.array(mask))))

    canvas = Image.new('RGBA', (CANVAS, CANVAS), (0, 0, 0, 0))
    margin = (CANVAS - BODY) // 2
    canvas.paste(body, (margin, margin), body)
    canvas.save(TARGET)
    print(f'\nwrote {os.path.relpath(TARGET, ROOT)}  '
          f'({CANVAS}x{CANVAS}, {BODY}px body, {margin}px margin)')
    return canvas


def preview(icon):
    """Both icons at the sizes macOS shows, on a light and a dark ground.

    Two grounds because that is where a too-bright icon gives itself away: a
    Dock on a dark wallpaper is exactly where the old one glowed.
    """
    old = Image.open(os.path.join(ROOT, 'assets', 'wv-logo.png')).convert('RGBA')
    sizes = [256, 128, 64, 32, 16]
    pad, gap, label = 24, 22, 18
    row_h = sizes[0] + label
    width = pad * 2 + sum(sizes) + gap * (len(sizes) - 1)
    sheet = Image.new('RGBA', (width, pad * 3 + row_h * 4), (255, 255, 255, 0))
    draw = ImageDraw.Draw(sheet)

    for half, ground in enumerate(((246, 247, 250), (28, 30, 34))):
        top = pad + half * (pad + row_h * 2)
        draw.rectangle([0, top - pad // 2, width, top + row_h * 2 + pad // 2], fill=ground)
        ink = (90, 96, 106) if half == 0 else (150, 158, 170)
        for row, (name, image) in enumerate((('current', old), ('new', icon))):
            x = pad
            y = top + row * row_h
            draw.text((x, y + sizes[0] + 4), name, fill=ink)
            for size in sizes:
                scaled = image.resize((size, size), Image.LANCZOS)
                sheet.paste(scaled, (x, y + sizes[0] - size), scaled)
                x += size + gap

    path = os.path.join(ROOT, 'build', 'icon-preview.png')
    sheet.convert('RGB').save(path)
    print(f'wrote {os.path.relpath(path, ROOT)}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', action='store_true',
                        help='also write a before/after sheet at real sizes')
    args = parser.parse_args()
    result = build()
    if args.preview:
        preview(result)

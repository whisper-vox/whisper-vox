#!/usr/bin/env python3
# Whisper Vox - voice dictation.
# Copyright (C) 2026 Pekelni Boroshna Lab.
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License v3.0 as published by the Free
# Software Foundation. It comes with NO WARRANTY. See <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

"""Decide the version a build carries. The one place that does.

MAJOR.MINOR is a decision, so it is declared in the repository - build/VERSION,
one line. BUILD is a fact about a particular build, so nothing declares it:
it counts up, once per build, on the machine doing the building.

    1.3.17  ->  the seventeenth build of the 1.3 series on this machine

A release is simply the build that turned out to be worth publishing: you tag
v1.3.17, and every platform builds that exact number rather than inventing its
own. So the tag is the authority for anything public, and the counter only ever
serves development.

Every build asks this one module, including the ones in CI, because two places
computing a version is two places that can disagree - and the disagreement only
shows up as a release missing a file.

The counter lives in build/.buildno, which is NOT in the repository. Two
machines counting separately is the point - their development builds are
throwaway and only need to be told apart from each other, one machine at a
time. It resets when the series changes, so 1.4 starts at 1 again.

    python build/version_for_build.py           bump, print the new version
    python build/version_for_build.py --peek    print what the next one would be
"""
import os
import re
import sys

BUILD_DIR = os.path.dirname(os.path.abspath(__file__))
COUNTER = os.path.join(BUILD_DIR, '.buildno')


def series():
    """MAJOR.MINOR, as declared by build/VERSION."""
    with open(os.path.join(BUILD_DIR, 'VERSION'), encoding='utf-8') as f:
        m = re.match(r'\s*(\d+)\.(\d+)\s*$', f.read())
    if not m:
        raise SystemExit('build/VERSION: expected MAJOR.MINOR, e.g. 1.3')
    return f'{m.group(1)}.{m.group(2)}'


def _counter(current):
    """(series, number) as last written, or a fresh start for this series."""
    try:
        with open(COUNTER, encoding='utf-8') as f:
            stored, number = f.read().split()
        if stored == current:
            return int(number)
    except Exception:
        pass
    return 0


def version_for_build(bump=True):
    """The version this build should carry."""
    # An explicit answer, for a build that has already been told what it is.
    forced = os.environ.get('WHISPERVOX_VERSION', '').strip()
    if forced:
        return forced.lstrip('vV')

    # A tag build says its own number and nothing here may argue with it.
    ref = os.environ.get('GITHUB_REF', '')
    if ref.startswith('refs/tags/v'):
        return ref[len('refs/tags/v'):]

    current = series()

    # CI off a tag - a manual run, built to be tested and thrown away. A local
    # counter would be meaningless on a runner that is new every time, and a
    # plain number would be indistinguishable from a real release.
    run = os.environ.get('GITHUB_RUN_NUMBER', '').strip()
    if run:
        return f'{current}.0-ci.{run}'

    number = _counter(current) + 1
    if bump:
        with open(COUNTER, 'w', encoding='utf-8') as f:
            f.write(f'{current} {number}')
    return f'{current}.{number}'


if __name__ == '__main__':
    print(version_for_build(bump='--peek' not in sys.argv))

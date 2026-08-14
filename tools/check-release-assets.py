#!/usr/bin/env python3
# Whisper Vox - voice dictation.
# Copyright (C) 2026 Pekelni Boroshna Lab.
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License v3.0 as published by the Free
# Software Foundation. It comes with NO WARRANTY. See <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

"""Do the files we publish still match what the app looks for?

This exists because of a bug that shipped and stayed: the updater looked for a
release asset ending in .exe, the Windows build published only the .zip holding
it, and nothing said so. latest_installer_url() quietly returned None, the app
opened the releases page instead, and the Settings window meanwhile announced a
download that was never happening. Nothing failed - it just did not work.

So this walks the same path the files do, from the build scripts through the
workflow to the release page, and asks the REAL predicate from updater.py
whether it can find an installer at the end of it. Rename an artifact past what
the app recognises and this fails loudly instead.

Run it anywhere:  python3 tools/check-release-assets.py
"""
import fnmatch
import os
import re
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from updater import pick_installer_asset   # noqa: E402  (needs the path above)

VERSION = '9.9.9'          # stands in for whatever launcher.py holds that day
DOWNLOAD_HOST = 'https://github.com/whisper-vox/whisper-vox/releases/download'

problems = []
notes = []


def fail(message):
    problems.append(message)


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding='utf-8') as handle:
        return handle.read()


# ── what the build scripts produce ────────────────────────────────────────────

def windows_outputs():
    """Every release/ file build_all.ps1 writes, with the version filled in."""
    source = read('build', 'build_all.ps1')
    found = re.findall(r'\$(?:outExe|zipOut)\s*=\s*"([^"]+)"', source)
    if not found:
        fail('build_all.ps1: could not find $outExe / $zipOut - has it been '
             'rewritten? This check reads the artifact names from there.')
    return [path.replace('\\', '/').replace('$version', VERSION) for path in found]


def macos_labels():
    """The architecture labels build_mac.sh can stamp into a name."""
    return re.findall(r"^\s*\w+\)\s+LABEL='([A-Za-z0-9]+)'", read('build', 'build_mac.sh'), re.M)


def macos_outputs():
    """Every release/ file build_mac.sh writes - one per architecture label."""
    source = read('build', 'build_mac.sh')
    template = re.search(r'^DMG="([^"]+)"', source, re.M)
    labels = macos_labels()
    if not template or not labels:
        fail('build_mac.sh: could not find the DMG name or the LABEL cases.')
        return []
    name = template.group(1).replace('${VERSION}', VERSION)
    return [name.replace('${LABEL}', label) for label in labels]


# ── what the workflow carries, and what it publishes ──────────────────────────

def workflow():
    return yaml.safe_load(read('.github', 'workflows', 'release.yml'))


def uploaded(entry, produced, labels):
    """The files one matrix entry hands to upload-artifact.

    A macOS runner globs release/*.dmg but only ever writes one of them - the
    one for its own architecture. Which that is comes from the artifact name
    the workflow declares (WhisperVox-macos-AppleSilicon), so a runner whose
    label does not line up with anything the build script can produce is itself
    worth catching.
    """
    matched = [path for path in produced if fnmatch.fnmatch(path, entry['files'])]
    artifact = str(entry.get('artifact', ''))
    mine = [label for label in labels if label.lower() in artifact.lower()]
    if len(mine) != 1 or not matched:
        return matched
    narrowed = [path for path in matched if mine[0].lower() in path.lower()]
    if not narrowed:
        fail(f'{entry["os"]}: its artifact is called "{artifact}", but nothing '
             f'the build script writes carries the label "{mine[0]}" - two '
             f'runners would upload the same file under different names: '
             f'{matched}')
    return narrowed


def published_extensions(flow):
    """Extensions the release step actually publishes.

    The globs are of the form artifacts/**/*.zip. fnmatch has no idea what **
    means, and reimplementing it would be its own bug - the part that matters
    here is which extensions survive, so take those.
    """
    for step in flow['jobs']['release']['steps']:
        if 'Publish' in str(step.get('name', '')):
            globs = str(step.get('with', {}).get('files', '')).split()
            return {os.path.splitext(g)[1].lower() for g in globs if g}
    fail('release.yml: no "Publish" step found in the release job.')
    return set()


def main():
    flow = workflow()
    entries = flow['jobs']['build']['strategy']['matrix']['include']
    extensions = published_extensions(flow)

    labels = macos_labels()
    produced = {'windows': windows_outputs(), 'macos': macos_outputs()}
    if problems:                      # nothing below is meaningful if parsing failed
        return report()

    published = []                    # basenames that reach the release page
    for entry in entries:
        runner = str(entry['os'])
        kind = 'windows' if 'windows' in runner else 'macos'
        before = len(problems)
        carried = uploaded(entry, produced[kind], labels)
        if not carried:
            if len(problems) == before:   # uploaded() has not already explained
                fail(f'{runner}: uploads "{entry["files"]}", which matches none '
                     f'of what its build script writes: {produced[kind]}')
            continue
        for path in carried:
            name = os.path.basename(path)
            if os.path.splitext(name)[1].lower() in extensions:
                published.append(name)
            else:
                notes.append(f'{name} is built and uploaded as an artifact but '
                             f'not published on the release page')

    if not published:
        fail('nothing at all would be published.')
        return report()

    notes.append('published: ' + ', '.join(sorted(published)))

    # The question this tool exists for.
    assets = [{'name': name, 'browser_download_url': f'{DOWNLOAD_HOST}/v{VERSION}/{name}'}
              for name in published]
    if not pick_installer_asset(assets):
        fail('the Windows app could not find an installer among the published '
             'files. updater.pick_installer_asset() wants "setup" in the name '
             'and a .zip or .exe extension; it was offered: '
             + ', '.join(sorted(published)))

    # macOS never self-installs, but a user who cannot tell the two disk images
    # apart is a support question, so both must say which they are.
    dmgs = [name for name in published if name.lower().endswith('.dmg')]
    if len(dmgs) > 1:
        for label in ('AppleSilicon', 'Intel'):
            if not any(label.lower() in name.lower() for name in dmgs):
                fail(f'more than one .dmg is published and none is marked '
                     f'"{label}" - a user cannot tell which one to take: {dmgs}')
    return report()


def report():
    for note in notes:
        print(f'  {note}')
    if problems:
        print('\nRelease assets do NOT match what the app looks for:')
        for problem in problems:
            print(f'  - {problem}')
        return 1
    print('\nRelease assets OK: the app can find what it needs on the release page.')
    return 0


if __name__ == '__main__':
    sys.exit(main())

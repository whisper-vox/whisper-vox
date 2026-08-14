# Whisper Vox - voice dictation.
# Copyright (C) 2026 Pekelni Boroshna Lab.
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License v3.0 as published by the Free
# Software Foundation. It comes with NO WARRANTY. See <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

"""Lightweight update checker.

Asks the PUBLIC releases repo's GitHub API for the latest release tag and
compares it with the running version. No Qt, no third-party deps - just stdlib
urllib so it can be imported from anywhere (app or, conceptually, the launcher).

Privacy: a single anonymous GET to GitHub. No telemetry, no identifiers - the
only thing GitHub sees is the requesting IP and a neutral User-Agent. The
optional one-click update downloads the official setup from GitHub's own hosts
only (validated below) and runs it; the user always triggers it explicitly.
"""
import json
import os
import sys
import tempfile
import urllib.parse
import urllib.request

# ── Public surfaces (source + releases live in one public repo) ───────────────
REPO_URL     = 'https://github.com/whisper-vox/whisper-vox'
RELEASES_URL = REPO_URL + '/releases'
ISSUES_URL   = REPO_URL + '/issues'
LATEST_API   = 'https://api.github.com/repos/whisper-vox/whisper-vox/releases/latest'

_TIMEOUT_S = 5
_USER_AGENT = 'WhisperVox-UpdateCheck'
# One-click update downloads only from GitHub's own asset hosts — never an
# arbitrary URL that happened to appear in the API response.
_TRUSTED_HOSTS = ('github.com', 'objects.githubusercontent.com',
                  'release-assets.githubusercontent.com')


def parse_version(s) -> tuple:
    """'v1.2.3' / '1.2.3' -> (1, 2, 3). Non-numeric parts collapse to 0.
    Lexical string compare is wrong ('1.0.10' < '1.0.9'); always compare these."""
    if not s:
        return ()
    s = str(s).strip().lstrip('vV')
    parts = []
    for chunk in s.split('.'):
        num = ''.join(ch for ch in chunk if ch.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts)


def is_newer(latest, current) -> bool:
    """True if `latest` is a strictly higher version than `current`."""
    lt, ct = parse_version(latest), parse_version(current)
    if not lt:
        return False
    return lt > ct


def check_latest():
    """Return the latest release tag (e.g. '1.0.18') from the public releases
    repo, or None on any error / offline. Never raises."""
    try:
        req = urllib.request.Request(
            LATEST_API,
            headers={'User-Agent': _USER_AGENT, 'Accept': 'application/vnd.github+json'},
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        tag = (data.get('tag_name') or '').strip()
        return tag or None
    except Exception:
        return None


def _trusted(url) -> bool:
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
        return any(host == h or host.endswith('.' + h) for h in _TRUSTED_HOSTS)
    except Exception:
        return False


def latest_installer_url():
    """URL of an asset this platform can install from by itself, or None.

    Windows: the setup. It is published as a .zip, not a bare .exe, because a
    browser warns loudly about downloading an executable - so the app has to
    unpack it (download_installer does). A .exe asset is still preferred if one
    is ever published, since it needs no unpacking.

    macOS: None, deliberately. A running .app cannot replace itself in place, a
    .dmg is something the user drags to Applications, and there are two of them
    - one per architecture. The caller falls back to opening the releases page,
    which is the honest answer there.
    """
    if sys.platform != 'win32':
        return None
    try:
        req = urllib.request.Request(
            LATEST_API,
            headers={'User-Agent': _USER_AGENT, 'Accept': 'application/vnd.github+json'},
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return pick_installer_asset(data.get('assets') or [])
    except Exception:
        return None


def pick_installer_asset(assets):
    """Which of a release's assets the Windows app can install from, or None.

    Split out from the network call so the naming contract can be checked
    without one - see tools/check-release-assets.py. The rule this encodes is
    the whole contract: a Windows asset is recognised by the word "setup" in
    its name and a .zip or .exe extension. Rename the build output past that
    and one-click updates stop working, silently, for everyone.
    """
    fallback = None
    for asset in assets:
        name = (asset.get('name') or '').lower()
        url = asset.get('browser_download_url') or ''
        if 'setup' not in name or not _trusted(url):
            continue
        if name.endswith('.exe'):
            return url
        if name.endswith('.zip') and fallback is None:
            fallback = url
    return fallback


def download_installer(url, progress=None):
    """Download the setup from a TRUSTED GitHub host and return a path to
    something runnable, or None on failure. `progress(frac)` is called 0.0-1.0.

    A .zip is unpacked and the setup inside it is what comes back.
    """
    if not _trusted(url):
        return None
    is_zip = urllib.parse.urlparse(url).path.lower().endswith('.zip')
    dest = os.path.join(tempfile.gettempdir(),
                        'WhisperVox-Setup-update.zip' if is_zip
                        else 'WhisperVox-Setup-update.exe')
    try:
        req = urllib.request.Request(url, headers={'User-Agent': _USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp, open(dest, 'wb') as f:
            total = int(resp.headers.get('Content-Length') or 0)
            read = 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                read += len(chunk)
                if progress and total:
                    try:
                        progress(read / total)
                    except Exception:
                        pass
    except Exception:
        return None
    return _unpack_setup(dest) if is_zip else dest


def _unpack_setup(zip_path):
    """Pull the setup executable out of the downloaded archive, or None.

    Members are taken by BASENAME only. A path inside an archive is attacker-
    controlled data, and one containing '..' would otherwise write wherever it
    liked - the archive comes from our own release, but that is a reason to
    keep the guard cheap, not to drop it.
    """
    import shutil
    import zipfile
    folder = os.path.join(tempfile.gettempdir(), 'WhisperVox-update')
    try:
        with zipfile.ZipFile(zip_path) as archive:
            for member in archive.namelist():
                name = os.path.basename(member)
                if not (name.lower().endswith('.exe') and 'setup' in name.lower()):
                    continue
                os.makedirs(folder, exist_ok=True)
                target = os.path.join(folder, name)
                with archive.open(member) as src, open(target, 'wb') as out:
                    shutil.copyfileobj(src, out)
                return target
    except Exception:
        pass
    return None

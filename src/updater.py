# Whisper Vox - voice dictation for Windows.
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
    """URL of the latest release's setup .exe asset (the single-file installer),
    or None. Picks the asset whose name contains 'Setup' and ends in '.exe'."""
    try:
        req = urllib.request.Request(
            LATEST_API,
            headers={'User-Agent': _USER_AGENT, 'Accept': 'application/vnd.github+json'},
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        for asset in data.get('assets') or []:
            name = (asset.get('name') or '').lower()
            url = asset.get('browser_download_url') or ''
            if name.endswith('.exe') and 'setup' in name and _trusted(url):
                return url
    except Exception:
        pass
    return None


def download_installer(url, progress=None):
    """Download the setup exe from a TRUSTED GitHub host to a temp file and
    return its path, or None on failure. `progress(frac)` is called 0.0-1.0."""
    if not _trusted(url):
        return None
    try:
        dest = os.path.join(tempfile.gettempdir(), 'WhisperVox-Setup-update.exe')
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
        return dest
    except Exception:
        return None

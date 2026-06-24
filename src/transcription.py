# Whisper Vox - voice dictation for Windows.
# Copyright (C) 2026 Pekelni Boroshna Lab.
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License v3.0 as published by the Free
# Software Foundation. It comes with NO WARRANTY. See <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

import io
import numpy as np
import soundfile as sf
from openai import OpenAI

from config_manager import ConfigManager


def transcribe_api(audio_data, sample_rate):
    client = OpenAI(
        api_key=ConfigManager.get('api_key'),
        base_url=ConfigManager.get('api_url'),
    )

    byte_io = io.BytesIO()
    # sample_rate is the rate the audio was actually captured at (device-native);
    # the WAV header must match it. Whisper resamples to 16 kHz server-side.
    sf.write(byte_io, audio_data, sample_rate, format='wav')
    byte_io.seek(0)

    kwargs = dict(
        model=ConfigManager.get('model'),
        file=('audio.wav', byte_io, 'audio/wav'),
        prompt=ConfigManager.get('initial_prompt'),
    )
    # '' = Auto-detect: omit the language param so Whisper detects it.
    lang = ConfigManager.get('language')
    if lang:
        kwargs['language'] = lang

    response = client.audio.transcriptions.create(**kwargs)
    return response.text


# STT model id heuristics (the OpenAI-compatible /v1/models endpoint does not
# categorise models, so we filter by id).
_STT_KEYWORDS = ('whisper', 'transcribe')


def fetch_models(api_url, api_key):
    """Live list of speech-to-text models from the provider's /v1/models."""
    client = OpenAI(api_key=api_key, base_url=api_url)
    ids = sorted({m.id for m in client.models.list().data})
    return [i for i in ids if any(k in i.lower() for k in _STT_KEYWORDS)]


def friendly_error(exc):
    """Map a transcription exception to a short, user-facing reason for the
    status overlay. Kept generic (no key/secret detail) and actionable."""
    try:
        import openai
        if isinstance(exc, openai.AuthenticationError):
            return 'Invalid or missing API key — open Settings to check it.'
        if isinstance(exc, openai.PermissionDeniedError):
            return 'API key was rejected — open Settings to check it.'
        if isinstance(exc, openai.RateLimitError):
            return 'Rate limit reached — wait a moment and try again.'
        if isinstance(exc, openai.APIConnectionError):
            return 'Could not reach the server — check your internet.'
        if isinstance(exc, openai.NotFoundError):
            return 'Model or API URL not found — check Settings.'
        if isinstance(exc, openai.APIStatusError):
            return f'Server error ({exc.status_code}) — try again later.'
    except Exception:
        pass
    return 'Transcription failed — check your settings and connection.'


def post_process(text):
    text = text.strip()
    if ConfigManager.get('remove_trailing_period') and text.endswith('.'):
        text = text[:-1]
    if ConfigManager.get('remove_capitalization'):
        text = text.lower()
    if ConfigManager.get('add_trailing_space'):
        text += ' '
    return text


def transcribe(audio_data, sample_rate):
    if audio_data is None:
        return ''
    result = transcribe_api(audio_data, sample_rate)
    return post_process(result)

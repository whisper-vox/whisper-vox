# Whisper Vox - voice dictation for Windows.
# Copyright (C) 2026 Pekelni Boroshna Lab.
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License v3.0 as published by the Free
# Software Foundation. It comes with NO WARRANTY. See <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Static data for the Settings UI - languages, provider presets, help texts.

Help texts use **bold** markers (rendered to <b> in the WebUI) to highlight the
parameter/option names. Ported from the original PyQt5 settings_window.py. No Qt.
"""

# ── Full Whisper language set (≈99), sorted by English name; '' = Auto-detect ──
LANGUAGES = [
    ('Afrikaans', 'af'), ('Albanian', 'sq'), ('Amharic', 'am'), ('Arabic', 'ar'),
    ('Armenian', 'hy'), ('Assamese', 'as'), ('Azerbaijani', 'az'), ('Bashkir', 'ba'),
    ('Basque', 'eu'), ('Belarusian', 'be'), ('Bengali', 'bn'), ('Bosnian', 'bs'),
    ('Breton', 'br'), ('Bulgarian', 'bg'), ('Cantonese', 'yue'), ('Catalan', 'ca'),
    ('Chinese', 'zh'), ('Croatian', 'hr'), ('Czech', 'cs'), ('Danish', 'da'),
    ('Dutch', 'nl'), ('English', 'en'), ('Estonian', 'et'), ('Faroese', 'fo'),
    ('Finnish', 'fi'), ('French', 'fr'), ('Galician', 'gl'), ('Georgian', 'ka'),
    ('German', 'de'), ('Greek', 'el'), ('Gujarati', 'gu'), ('Haitian Creole', 'ht'),
    ('Hausa', 'ha'), ('Hawaiian', 'haw'), ('Hebrew', 'he'), ('Hindi', 'hi'),
    ('Hungarian', 'hu'), ('Icelandic', 'is'), ('Indonesian', 'id'), ('Italian', 'it'),
    ('Japanese', 'ja'), ('Javanese', 'jw'), ('Kannada', 'kn'), ('Kazakh', 'kk'),
    ('Khmer', 'km'), ('Korean', 'ko'), ('Lao', 'lo'), ('Latin', 'la'),
    ('Latvian', 'lv'), ('Lingala', 'ln'), ('Lithuanian', 'lt'), ('Luxembourgish', 'lb'),
    ('Macedonian', 'mk'), ('Malagasy', 'mg'), ('Malay', 'ms'), ('Malayalam', 'ml'),
    ('Maltese', 'mt'), ('Maori', 'mi'), ('Marathi', 'mr'), ('Mongolian', 'mn'),
    ('Myanmar', 'my'), ('Nepali', 'ne'), ('Norwegian', 'no'), ('Nynorsk', 'nn'),
    ('Occitan', 'oc'), ('Pashto', 'ps'), ('Persian', 'fa'), ('Polish', 'pl'),
    ('Portuguese', 'pt'), ('Punjabi', 'pa'), ('Romanian', 'ro'), ('Russian', 'ru'),
    ('Sanskrit', 'sa'), ('Serbian', 'sr'), ('Shona', 'sn'), ('Sindhi', 'sd'),
    ('Sinhala', 'si'), ('Slovak', 'sk'), ('Slovenian', 'sl'), ('Somali', 'so'),
    ('Spanish', 'es'), ('Sundanese', 'su'), ('Swahili', 'sw'), ('Swedish', 'sv'),
    ('Tagalog', 'tl'), ('Tajik', 'tg'), ('Tamil', 'ta'), ('Tatar', 'tt'),
    ('Telugu', 'te'), ('Thai', 'th'), ('Tibetan', 'bo'), ('Turkish', 'tr'),
    ('Turkmen', 'tk'), ('Ukrainian', 'uk'), ('Urdu', 'ur'), ('Uzbek', 'uz'),
    ('Vietnamese', 'vi'), ('Welsh', 'cy'), ('Yiddish', 'yi'), ('Yoruba', 'yo'),
]

_LANG_CODE_TO_NAME = {code: name for name, code in LANGUAGES}

# ── Provider presets ────────────────────────────────────────────────────────--
PROVIDERS = {
    'groq':   {'label': 'Groq (Free)', 'url': 'https://api.groq.com/openai/v1',
               'stt': ['whisper-large-v3', 'whisper-large-v3-turbo'],
               'stt_default': 'whisper-large-v3'},
    'openai': {'label': 'OpenAI - ChatGPT (Paid)', 'url': 'https://api.openai.com/v1',
               'stt': ['whisper-1', 'gpt-4o-transcribe', 'gpt-4o-mini-transcribe'],
               'stt_default': 'whisper-1'},
    'manual': {'label': 'Manual Settings', 'url': '', 'stt': [], 'stt_default': ''},
}

PROVIDER_LINKS = {
    'groq':   ('CLICK HERE - to get your free API key -> console.groq.com/keys',   'https://console.groq.com/keys'),
    'openai': ('CLICK HERE - to get your API key -> platform.openai.com/api-keys', 'https://platform.openai.com/api-keys'),
    'manual': ('Manual mode - paste your own Whisper-compatible API URL and key', ''),
}

DONATE_URL = 'https://nowpayments.io/donation/PekelniBoroshnaLab'
REPO_URL     = 'https://github.com/whisper-vox/whisper-vox'
RELEASES_URL = REPO_URL + '/releases'
ISSUES_URL   = REPO_URL + '/issues'


def key_slot(provider_id: str) -> str:
    return provider_id if provider_id in ('groq', 'openai', 'manual') else 'groq'


def default_prompt(lang_name: str = None) -> str:
    tail = (
        'Transcribe exactly what is spoken{scope}. Do not translate. Do not '
        'transliterate. Keep English words, names, brands, products, acronyms '
        'and technical terms in Latin script as spoken.'
    )
    if lang_name:
        return (f'Verbatim {lang_name} dictation. '
                + tail.format(scope=f' in {lang_name} using its native script'))
    return 'Verbatim dictation. ' + tail.format(
        scope=" in the original spoken language and its native script")


# ── Help texts (**bold** = highlighted term; shown on hover and on click) ──────
HELP = {
    'provider': (
        'Where transcription runs.\n\n'
        '**Groq (Free)** - free Whisper API with generous daily limits. Recommended.\n'
        '**OpenAI - ChatGPT (Paid)** - paid Whisper API used with your OpenAI key.\n'
        '**Manual Settings** - a blank profile: type any API URL, key and model '
        'yourself (e.g. a self-hosted or third-party server). Saved independently.\n\n'
        '**Important:** Whisper Vox speaks the OpenAI-compatible speech-to-text '
        '(Whisper) API only - a provider must expose an /audio/transcriptions '
        'endpoint with a Whisper-style model. Chat/LLM endpoints will NOT work here.'
    ),
    'api_url': 'Base URL of the transcription API endpoint. Change this if you use a different OpenAI-compatible provider.',
    'api_key': (
        'How to get your free API key:\n\n'
        '**1.** Click the link above 👆\n'
        '**2.** Sign in with your account.\n'
        '**3.** Click the **Create API Key** button.\n'
        '**4.** It asks for a name - type anything you like.\n'
        '**5.** Copy the key and paste it into field 4 here.\n'
        '**6.** Press the **Save** button ↘'
    ),
    'api_key_link': (
        'The official provider websites where you create your own API key.\n\n'
        '**Groq** offers a free API with a huge amount of free daily limits - far more '
        'than enough for everyday dictation, with plenty to spare.\n'
        '**OpenAI** is a paid API, used with your own paid key.'
    ),
    'model': (
        'Speech-to-text model sent to the API. Pick from the list, or press '
        '**Refresh** to pull the current models from your provider.\n\n'
        '**whisper-large-v3** - slower, but more accurate.\n'
        '**whisper-large-v3-turbo** - faster, but may make more mistakes.\n'
        '**whisper-1** - OpenAI paid model, used with your paid OpenAI API key.'
    ),
    'language': (
        'Language of the dictated audio.\n\n'
        '**Auto-detect** - Whisper figures out the language; best for mixed-language '
        'speech, but on short phrases it may guess wrong.\n'
        '**A specific language** - most accurate and avoids transliteration (your '
        'speech written in the wrong alphabet) when you mostly dictate in one language.'
    ),
    'initial_prompt': 'Optional text that primes the model before transcription. Use it to supply domain vocabulary, style hints, or mixed-language instructions.',
    'activation_key': 'Click the field, then press your desired key combination (e.g. Ctrl+D or F2). It will be captured automatically.',
    'recording_mode': (
        'How the activation key behaves.\n\n'
        '**Hold to record** - record while the key is held.\n'
        '**Press to toggle** - press once to start, press again to stop.\n'
        '**Continuous** - press once; it records and stops automatically when you go '
        'quiet (uses Silence Duration below).'
    ),
    'sound_device': (
        'Which microphone to record from.\n\n'
        '**Default microphone** - follows your Windows default; the line shows '
        'which device that is right now. Plug in a headset and it switches to it '
        'from your NEXT dictation.\n'
        '**A specific device** - pinned and always used; if it gets unplugged the '
        'app falls back to the default automatically.\n'
        'Press **↻** to rescan now and refresh this list and the "Default" name.'
    ),
    'silence_duration': (
        '**Continuous mode only** - how long a pause counts as "you have finished".\n'
        'After you start talking, once the mic stays quiet for this many '
        'milliseconds the recording stops automatically and the text is typed.\n'
        'Too low cuts you off on natural pauses; too high makes you wait. '
        '**~2000 ms (2 s)** is a good balance.\n'
        'The timer starts only after speech is first detected.'
    ),
    'min_duration': (
        'Recordings shorter than this (ms) are discarded - it filters accidental '
        'taps of the activation key.\n'
        'Keep it small: **~250 ms** drops stray taps but still keeps short real '
        'words like "yes", "no" or "ok".'
    ),
    'add_trailing_space': 'Append a space after the transcribed text so the next word types correctly.',
    'input_method': (
        'How the transcribed text is delivered into the active window.\n\n'
        '**Clipboard paste** - instant for long text; keyboard layout never matters. Recommended.\n'
        '**Unicode keystrokes** - types real unicode characters one by one, layout-independent; for fields that reject pasting.\n'
        '**Keystrokes (legacy)** - simulates physical keys through the CURRENT layout: '
        'non-Latin symbols typed while an English layout is active come out as gibberish. '
        'Only for apps that ignore synthetic unicode input.'
    ),
    'paste_shortcut': (
        'Shortcut sent to paste from the clipboard.\n'
        '**Ctrl+V** - most applications.\n'
        '**Shift+Insert** - many terminals.'
    ),
    'clipboard_restore': (
        'Controls what stays on the clipboard after a dictation is pasted.\n'
        '**Unchecked** - the last recognized segment stays on the clipboard.\n'
        '**Checked** - the recognized segment is dropped and the previous clipboard '
        'value is restored.\n'
        'Note: only text can be restored - an image or file cannot be brought back.'
    ),
    'paste_delay_ms': 'Pause (ms) between writing text to the clipboard and pressing the paste shortcut. Increase if the target app pastes stale content.',
    'remove_trailing_period': 'Remove the final period from transcribed text if present.',
    'remove_capitalization': 'Convert the entire transcription to lowercase.',
    'writing_key_press_delay': (
        'Delay in seconds between simulated key presses (default: **0.005**).\n'
        'If characters are skipped, duplicated, or garbled in older apps '
        '(Notepad, legacy forms), increase to **0.01** or even **0.05**.'
    ),
    'hide_status_window': 'Hide the small recording/transcribing status overlay that appears on screen.',
    'noise_on_completion': 'Play a short beep sound when transcription is finished typing.',
    'desktop_icon': (
        'Keep a Desktop shortcut pointing to the running WhisperVox.exe.\n'
        'Unchecking removes the shortcut this option created.'
    ),
    'run_on_startup': (
        'Start Whisper Vox automatically when you sign in to Windows.\n'
        'Uses the per-user registry Run key - no admin rights needed.'
    ),
    'start_minimized': 'Launch straight to the tray without showing this window. Applies immediately.',
    'show_splash': (
        'Show a small **"Preparing..."** splash while the app starts up.\n'
        'Off by default. The very first launch always shows it. Takes effect on the next launch.'
    ),
    'auto_check_updates': (
        'Check GitHub once a day for a newer version.\n'
        '**No data is sent** - just a version check.\n'
        'The download always stays manual: you click the link and run the new file yourself.'
    ),
    'enable_logging': (
        'Write a log file of system events and errors (e.g. microphone problems) '
        'to help diagnose issues.\n'
        '**Off by default** - nothing is written.\n'
        '**Transcribed text is never logged.**\n'
        'The log holds one day at most: it refreshes automatically each day.'
    ),
}

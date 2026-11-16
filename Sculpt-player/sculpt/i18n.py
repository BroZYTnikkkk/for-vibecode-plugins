# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""The plugin's words in the language of the player around them. The Russian text in the code is the key."""

import time

from java import jclass

from .texts import EN, UK

LOCALE = "org.telegram.messenger.LocaleController"
STRINGS = "org.telegram.messenger.R$string"
# exteraGram can word its player in another language than the chats: this title tells which one the player is in
PLAYER_TITLE = {"Знайти текст пісні?": "uk", "Найти текст песни?": "ru", "Find the Lyrics?": "en"}
SOURCE = "ru"  # what the code is written in
CHECK_EVERY = 3.0  # seconds; the words are asked for many at a time, and the language changes rarely
SLAVIC = ("ru", "uk")

_known = (0.0, SOURCE)


def language():
    global _known
    now = time.monotonic()
    if now < _known[0]:
        return _known[1]
    try:
        locale = jclass(LOCALE)
        code = PLAYER_TITLE.get(str(locale.getString(jclass(STRINGS).LyricsOfferTitle)))
        if code is None:
            code = str(locale.getInstance().getCurrentLocale().getLanguage())
        if not (code.isalpha() and code.islower() and len(code) <= 3):
            code = SOURCE
    except Exception:
        code = SOURCE
    _known = (now + CHECK_EVERY, code)
    return code


def _table():
    code = language()
    return None if code == SOURCE else UK if code == "uk" else EN


def tr(text):
    """The words for the screen, or the Russian ones where there is no translation yet."""
    table = _table()
    return text if table is None else table.get(text, text)


def source(text):
    """The Russian key of words already translated: what is saved stays the same in any language."""
    table = _table()
    if table is None:
        return text
    for key, value in table.items():
        if value == text:
            return key
    return text


def plural(count, one, few, many):
    if language() not in SLAVIC:
        return one if count == 1 else many
    tail = count % 100
    if 11 <= tail <= 14:
        return many
    return {1: one, 2: few, 3: few, 4: few}.get(count % 10, many)

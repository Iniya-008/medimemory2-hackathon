"""Languages MediMemory can speak, and which ElevenLabs voice model to use for each.

Source: ElevenLabs "What languages do you support?" help page (checked Nov 2026).
* Multilingual v2 is used where it supports the language (higher stability for long instructions).
* Eleven v3 (70+ languages) is used for everything else, which covers most Indian languages.
Speech-to-text (Scribe) understands 90+ languages, so questions can be asked in any of these.
Every translation is machine-made and marked "not checked" until a native speaker verifies it.
"""
from __future__ import annotations

V2 = "eleven_multilingual_v2"
V3 = "eleven_v3"

# code: (English name, native name, group)
_LANGS: dict[str, tuple[str, str, str]] = {
    # India first (order shown in the picker)
    "en": ("English", "English", "india"), "ta": ("Tamil", "தமிழ்", "india"), "hi": ("Hindi", "हिन्दी", "india"),
    "te": ("Telugu", "తెలుగు", "india"), "kn": ("Kannada", "ಕನ್ನಡ", "india"), "ml": ("Malayalam", "മലയാളം", "india"),
    "bn": ("Bengali", "বাংলা", "india"), "mr": ("Marathi", "मराठी", "india"), "gu": ("Gujarati", "ગુજરાતી", "india"),
    "pa": ("Punjabi", "ਪੰਜਾਬੀ", "india"), "ur": ("Urdu", "اردو", "india"), "or": ("Odia", "ଓଡ଼ିଆ", "india"),
    "as": ("Assamese", "অসমীয়া", "india"), "ne": ("Nepali", "नेपाली", "india"), "sd": ("Sindhi", "سنڌي", "india"),
    # rest of the world
    "ar": ("Arabic", "العربية", "world"), "zh": ("Chinese (Mandarin)", "中文", "world"), "es": ("Spanish", "Español", "world"),
    "fr": ("French", "Français", "world"), "de": ("German", "Deutsch", "world"), "pt": ("Portuguese", "Português", "world"),
    "ru": ("Russian", "Русский", "world"), "ja": ("Japanese", "日本語", "world"), "ko": ("Korean", "한국어", "world"),
    "id": ("Indonesian", "Bahasa Indonesia", "world"), "ms": ("Malay", "Bahasa Melayu", "world"), "vi": ("Vietnamese", "Tiếng Việt", "world"),
    "th": ("Thai", "ไทย", "world"), "tr": ("Turkish", "Türkçe", "world"), "it": ("Italian", "Italiano", "world"),
    "nl": ("Dutch", "Nederlands", "world"), "pl": ("Polish", "Polski", "world"), "fil": ("Filipino", "Filipino", "world"),
    "sw": ("Swahili", "Kiswahili", "world"), "fa": ("Persian", "فارسی", "world"), "he": ("Hebrew", "עברית", "world"),
    "uk": ("Ukrainian", "Українська", "world"), "ro": ("Romanian", "Română", "world"), "el": ("Greek", "Ελληνικά", "world"),
    "cs": ("Czech", "Čeština", "world"), "hu": ("Hungarian", "Magyar", "world"), "sv": ("Swedish", "Svenska", "world"),
    "da": ("Danish", "Dansk", "world"), "fi": ("Finnish", "Suomi", "world"), "no": ("Norwegian", "Norsk", "world"),
    "bg": ("Bulgarian", "Български", "world"), "hr": ("Croatian", "Hrvatski", "world"), "sk": ("Slovak", "Slovenčina", "world"),
    "sr": ("Serbian", "Српски", "world"), "my": ("Burmese", "မြန်မာ", "world"), "ps": ("Pashto", "پښتو", "world"),
    "uz": ("Uzbek", "Oʻzbek", "world"), "kk": ("Kazakh", "Қазақ", "world"), "az": ("Azerbaijani", "Azərbaycan", "world"),
    "ka": ("Georgian", "ქართული", "world"), "hy": ("Armenian", "Հայերեն", "world"), "yo": ("Yoruba", "Yorùbá", "world"),
    "ha": ("Hausa", "Hausa", "world"), "so": ("Somali", "Soomaali", "world"),
}
_V2_LANGS = {"en", "ja", "zh", "de", "hi", "fr", "ko", "pt", "it", "es", "id", "nl", "tr", "fil", "pl", "sv", "bg", "ro",
             "ar", "cs", "el", "fi", "hr", "ms", "sk", "da", "ta", "uk", "ru"}

# Scribe may report ISO 639-3 codes; map the ones we support back to our codes.
_ISO3 = {
    "eng": "en", "tam": "ta", "hin": "hi", "tel": "te", "kan": "kn", "mal": "ml", "ben": "bn", "mar": "mr", "guj": "gu",
    "pan": "pa", "urd": "ur", "ori": "or", "ory": "or", "asm": "as", "nep": "ne", "snd": "sd", "ara": "ar", "cmn": "zh",
    "zho": "zh", "spa": "es", "fra": "fr", "deu": "de", "por": "pt", "rus": "ru", "jpn": "ja", "kor": "ko", "ind": "id",
    "msa": "ms", "zsm": "ms", "vie": "vi", "tha": "th", "tur": "tr", "ita": "it", "nld": "nl", "pol": "pl", "fil": "fil",
    "tgl": "fil", "swa": "sw", "fas": "fa", "pes": "fa", "heb": "he", "ukr": "uk", "ron": "ro", "ell": "el", "ces": "cs",
    "hun": "hu", "swe": "sv", "dan": "da", "fin": "fi", "nor": "no", "nob": "no", "bul": "bg", "hrv": "hr", "slk": "sk",
    "srp": "sr", "mya": "my", "pus": "ps", "uzb": "uz", "kaz": "kk", "aze": "az", "kat": "ka", "hye": "hy", "yor": "yo",
    "hau": "ha", "som": "so",
}


def supported(code: str | None) -> bool:
    return bool(code) and code in _LANGS


def normalize(code: str | None) -> str | None:
    """Map whatever the speech-to-text service returns ('tam', 'ta', 'ta-IN') to one of our codes, or None."""
    if not code:
        return None
    c = code.strip().lower().replace("_", "-").split("-")[0]
    if c in _LANGS:
        return c
    return _ISO3.get(c)


def name(code: str) -> str:
    return _LANGS.get(code, (code,))[0]


def tts_model(code: str) -> str:
    return V2 if code in _V2_LANGS else V3


def catalogue() -> list[dict]:
    return [{"code": k, "name": v[0], "native": v[1], "group": v[2], "voice_model": tts_model(k)} for k, v in _LANGS.items()]

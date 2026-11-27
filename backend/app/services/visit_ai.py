"""AI steps of the after-visit loop: extraction, translation and question matching.

Every LLM output is treated as a suggestion and checked in code:
* an extracted instruction must quote a sentence that really appears in the transcript,
  and every number in it must appear in that sentence; otherwise it is flagged needs_check;
* question matching may only return ids of the patient's own CONFIRMED instructions.
Without an LLM, simple rule-based fallbacks are used and labelled as such.
"""
from __future__ import annotations

import difflib
import re

from app.core import languages as L
from app.core.llm import LLMUnavailable, chat_json
from app.models.visits import CATEGORIES

# ------------------------------------------------------------------ helpers
_SENT_SPLIT = re.compile(r"(?<=[.!?।])\s+|\n+")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(text or "") if s.strip()]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", (s or "").lower())).strip()


def _numbers(s: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", s or ""))


def quote_found(quote: str, transcript: str, threshold: float = 0.85) -> bool:
    q, t = _norm(quote), _norm(transcript)
    if not q:
        return False
    if q in t:
        return True
    words, qn = t.split(), len(q.split())
    for i in range(max(1, len(words) - qn + 1)):
        window = " ".join(words[i:i + qn])
        if difflib.SequenceMatcher(None, q, window).ratio() >= threshold:
            return True
    return False


def check_item(item: dict, transcript: str) -> dict:
    """Flag anything the code cannot trace back to the transcript."""
    reasons = []
    if not quote_found(item.get("source_sentence", ""), transcript):
        reasons.append("The doctor's wording could not be found in the transcript")
    extra = _numbers(item.get("simple_text", "")) - _numbers(item.get("source_sentence", ""))
    if extra:
        reasons.append(f"Number(s) {', '.join(sorted(extra))} are not in the doctor's words")
    if item.get("model_flagged"):
        reasons.append("The AI was unsure about this one")
    item["needs_check"] = bool(reasons)
    item["check_reason"] = "; ".join(reasons) or None
    return item


# ------------------------------------------------------------------ extraction
EXTRACT_SYSTEM = """You turn a doctor-patient consultation transcript into the doctor's instructions for the patient.
The transcript may mix Tamil and English and may contain speech-recognition errors.
Rules:
- Include ONLY instructions the doctor actually gave (medicines and how to take them, timings, diet, tests, follow-up visits, lifestyle).
- Never add advice, doses, medicines or tests that are not in the transcript. Never diagnose.
- source_sentence: copy the doctor's words EXACTLY as they appear in the transcript (one sentence or phrase).
- simple_text: one short, plain-English instruction a 68-year-old can follow. Keep medicine names, numbers and units exactly as said.
- category: one of medicine, timing, diet, test, follow_up, lifestyle, other.
- unsure: true if the transcript is unclear for this item.
- doctor_name: the doctor's name if it is said, else "".
Return JSON: {"doctor_name": "", "instructions": [{"category": "", "source_sentence": "", "simple_text": "", "unsure": false}]}"""

_RULE_CATS = [
    ("medicine", r"\b(tablets?|pills?|medicine|capsules?|insulin|mg|syrup|injection)\b"),
    ("test", r"\b(test|hba1c|scan|x-?ray|ecg|check (your|the) (sugar|bp|blood))\b"),
    ("follow_up", r"\b(come back|follow[- ]?up|next visit|review after|see me|after (one|two|\d+) (weeks?|months?))\b"),
    ("diet", r"\b(eat|food|diet|salt|sugar|sweets?|rice|oil|fried|drink|water|meals?|breakfast|lunch|dinner)\b"),
    ("lifestyle", r"\b(walk|exercise|sleep|smok\w*|alcohol|rest|weight)\b"),
]
# An instruction tells the patient to do something; findings ("your sugar is high") are skipped.
_IMPERATIVE = re.compile(r"(^|\b)(take|avoid|reduce|eat|drink|walk|do|come|check|continue|stop|start|use|apply|get|keep|"
                         r"don'?t|do not|never|always|have|cut|limit|sleep|rest|exercise|bring)\b", re.I)


def _rule_extract(transcript: str) -> list[dict]:
    items = []
    for s in sentences(transcript):
        body = re.sub(r"^\s*(doctor|dr\.?|patient)\s*:\s*", "", s, flags=re.I)
        if not _IMPERATIVE.search(body):
            continue
        for cat, rx in _RULE_CATS:
            if re.search(rx, body, re.I):
                items.append({"category": cat, "source_sentence": body, "simple_text": body})
                break
    return items


def extract(transcript: str) -> tuple[str, str, list[dict]]:
    """Returns (method, doctor_name, items). Items are checked with check_item()."""
    try:
        data = chat_json(EXTRACT_SYSTEM, f"TRANSCRIPT:\n{transcript}")
        method, doctor = "llm", str(data.get("doctor_name") or "")[:120]
        raw = data.get("instructions") or []
        items = []
        for r in raw if isinstance(raw, list) else []:
            if not isinstance(r, dict) or not str(r.get("simple_text", "")).strip():
                continue
            cat = r.get("category") if r.get("category") in CATEGORIES else "other"
            items.append({"category": cat, "source_sentence": str(r.get("source_sentence", "")).strip(),
                          "simple_text": str(r["simple_text"]).strip(), "model_flagged": bool(r.get("unsure"))})
    except LLMUnavailable:
        method, doctor, items = "rules", "", _rule_extract(transcript)
    return method, doctor, [check_item(i, transcript) for i in items][:30]


# ------------------------------------------------------------------ reading a photo (no Tesseract on the server)
READ_SYSTEM = """Transcribe the text in this medical document image exactly as written, line by line.
Do not interpret, correct, summarise or add anything. If a word is unreadable write [unclear].
Return JSON: {"text": "..."}"""


def read_image(png_or_jpeg: bytes, mime: str) -> str:
    """Raises LLMUnavailable. Output is only ever used as a draft the patient must review."""
    import base64
    url = f"data:{mime};base64,{base64.b64encode(png_or_jpeg).decode()}"
    data = chat_json(READ_SYSTEM, [{"type": "text", "text": "Transcribe this document."},
                                   {"type": "image_url", "image_url": {"url": url}}], timeout=60)
    return str(data.get("text") or "").strip()


# ------------------------------------------------------------------ translation
TRANSLATE_SYSTEM = """Translate each medical instruction for an elderly patient into simple, spoken {lang}.
Rules: keep the meaning exactly; do not add or remove advice; keep medicine names in their original spelling;
write numbers as digits; keep it short and natural to listen to.
Return JSON: {{"translations": [{{"id": <id>, "text": "..."}}]}}"""


def translate(items: list[tuple[int, str]], lang: str) -> dict[int, str]:
    """items: [(instruction_id, english_text)] -> {id: translated_text}. Raises LLMUnavailable."""
    if lang == "en":
        return {i: t for i, t in items}
    lines = "\n".join(f'{{"id": {i}, "text": {t!r}}}' for i, t in items)
    data = chat_json(TRANSLATE_SYSTEM.format(lang=L.name(lang)), f"INSTRUCTIONS:\n{lines}")
    out = {}
    for r in data.get("translations") or []:
        try:
            iid = int(r["id"])
        except (KeyError, TypeError, ValueError):
            continue
        txt = str(r.get("text") or "").strip()
        if txt and iid in dict(items):
            out[iid] = txt
    return out


TO_ENGLISH_SYSTEM = """Translate the patient's question into plain English, word for word in meaning.
Do not answer it, soften it or add anything. Keep medicine names and numbers unchanged.
Return JSON: {"english": "..."}"""


def needs_english(text: str) -> bool:
    """True when the question is not plain English (non-Latin script or a lot of non-ASCII)."""
    t = text or ""
    return sum(ord(ch) > 127 for ch in t) > max(2, len(t) * 0.15)


def to_english(text: str) -> str | None:
    """English rendering of a question so the safety rules and matching can read it. None if no LLM."""
    try:
        return str(chat_json(TO_ENGLISH_SYSTEM, text, timeout=15).get("english") or "").strip() or None
    except LLMUnavailable:
        return None


# ------------------------------------------------------------------ question matching
MATCH_SYSTEM = """A patient asks a question about instructions their doctor gave them. The question may be in Tamil or English.
Pick the instruction ids that directly answer it, from the numbered list only. If none answer it, return an empty list.
Do not answer the question yourself. Return JSON: {"ids": [<id>, ...]}"""

_STOP = set("""a an the i me my is are was were be to of in on at for with and or it this that do does did should can will
what when where which who how much many please tell about doctor said say told you your have has had am get go""".split())
_HINTS = {
    "timing": r"\b(when|time|morning|night|evening|before|after|daily|times?)\b|எப்போது|காலை|இரவு|நேரம்",
    "diet": r"\b(eat|food|diet|salt|sugar|sweet|rice|drink|meal)\b|சாப்பா|உணவு|உப்பு|சர்க்கரை|இனிப்பு",
    "test": r"\b(test|blood|hba1c|report|check)\b|பரிசோதனை|டெஸ்ட்|ரத்த",
    "follow_up": r"\b(come back|next|visit|follow|appointment|again|review)\b|மறுபடி|அடுத்த|வர",
    "medicine": r"\b(tablet|medicine|pill|insulin|mg)\b|மாத்திரை|மருந்து",
    "lifestyle": r"\b(walk|exercise|sleep|rest|smok|alcohol)\b|நட",
}


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"\w+", (s or "").lower()) if t not in _STOP and len(t) > 1}


def keyword_match(question: str, candidates: list[dict]) -> list[int]:
    """candidates: [{id, category, texts: [..]}]. Returns best ids (may be empty)."""
    qt = _tokens(question)
    cats = {c for c, rx in _HINTS.items() if re.search(rx, question, re.I)}
    scored = []
    for c in candidates:
        overlap = len(qt & set().union(*(_tokens(t) for t in c["texts"])))
        score = overlap + (1.5 if c["category"] in cats else 0)
        if overlap >= 1 or c["category"] in cats:
            scored.append((score, c["id"]))
    if not scored:
        return []
    scored.sort(reverse=True)
    top = scored[0][0]
    return [i for s, i in scored if s >= max(1.0, top * 0.75)][:3]


def match(question: str, candidates: list[dict]) -> tuple[str, list[int]]:
    allowed = {c["id"] for c in candidates}
    if not candidates:
        return "none", []
    try:
        listing = "\n".join(f'{c["id"]}: {" / ".join(c["texts"])}' for c in candidates)
        data = chat_json(MATCH_SYSTEM, f"INSTRUCTIONS:\n{listing}\n\nQUESTION: {question}", timeout=20)
        ids = []
        for x in data.get("ids") or []:
            try:
                if int(x) in allowed and int(x) not in ids:
                    ids.append(int(x))
            except (TypeError, ValueError):
                continue
        return "llm", ids[:3]
    except LLMUnavailable:
        return "keywords", keyword_match(question, candidates)

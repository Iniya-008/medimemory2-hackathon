"""Safety rules for the after-visit assistant. Enforced in code, before any record lookup or LLM call.

Order of checks for every question:
1. EMERGENCY  -> fixed "call 108" message. Records are NOT consulted.
2. REFUSAL    -> diagnosis, new medicines, dose changes. Fixed message pointing to the doctor/pharmacist.
3. otherwise  -> the caller may answer, but only from the patient's CONFIRMED instructions.

The Tamil keywords and messages below were written by the development team and are
NOT yet verified by a native-speaker reviewer (see TAMIL_TEXT_VERIFIED).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

TAMIL_TEXT_VERIFIED = False

# ------------------------------------------------------------------ fixed messages
MESSAGES = {
    "emergency": {
        "en": "This could be an emergency. Please call 108 or go to the nearest hospital now. "
              "I can't help with emergencies.",
        "ta": "இது அவசர நிலையாக இருக்கலாம். உடனே 108-ஐ அழைக்கவும் அல்லது அருகிலுள்ள மருத்துவமனைக்குச் செல்லவும்.",
    },
    "dose_change": {
        "en": "I can't advise changing, skipping or stopping a medicine or its dose. Please ask your doctor or pharmacist.",
        "ta": "மருந்தின் அளவை மாற்றுவது, தவிர்ப்பது அல்லது நிறுத்துவது பற்றி என்னால் ஆலோசனை சொல்ல முடியாது. உங்கள் மருத்துவர் அல்லது மருந்தாளரிடம் கேளுங்கள்.",
    },
    "new_medicine": {
        "en": "I can't suggest new medicines. Please ask your doctor or pharmacist.",
        "ta": "புதிய மருந்துகளை என்னால் பரிந்துரைக்க முடியாது. உங்கள் மருத்துவர் அல்லது மருந்தாளரிடம் கேளுங்கள்.",
    },
    "diagnosis": {
        "en": "I can't diagnose or judge your health. I can only repeat what your doctor told you. Please ask your doctor.",
        "ta": "என்னால் நோயைக் கண்டறியவோ உங்கள் உடல்நிலையை மதிப்பிடவோ முடியாது. மருத்துவர் சொன்னதை மட்டுமே திரும்பச் சொல்ல முடியும். உங்கள் மருத்துவரிடம் கேளுங்கள்.",
    },
    "not_found": {
        "en": "That isn't in your saved instructions. Please ask your doctor.",
        "ta": "அது நீங்கள் சேமித்த அறிவுரைகளில் இல்லை. உங்கள் மருத்துவரிடம் கேளுங்கள்.",
    },
}


def message(kind: str, lang: str = "en") -> str:
    m = MESSAGES[kind]
    return m.get(lang) or m["en"]


# ------------------------------------------------------------------ patterns
_MED = r"(dose|dosage|tablets?|pills?|medicines?|medication|meds|insulin|units?|mg|capsules?|injection)"

EMERGENCY = [
    r"\bchest (pain|tightness|pressure)\b", r"\bpain in (my |the )?chest\b", r"\bheart attack\b",
    r"\b(can'?t|cannot|unable to|hard to|difficult(y)? (in )?|trouble) breath", r"\bbreathless", r"\bshort(ness)? of breath\b",
    r"\bfaint(ed|ing)?\b", r"\bpassed out\b", r"\bunconscious\b", r"\bcollaps(e|ed|ing)\b",
    r"\b(severe|heavy|a lot of|lots of) bleeding\b", r"\bbleeding (heavily|a lot|won'?t stop|that won'?t stop)\b",
    r"\b(vomit(ing|ed)?|cough(ing|ed)?) (up )?blood\b",
    r"\bstroke\b", r"\bface (is )?droop", r"\bslurred speech\b", r"\bcan'?t (move|lift|feel) (my )?(arm|leg|face|side)\b",
    r"\b(seizure|fits|convulsion)", r"\boverdose\b", r"\btook too many\b",
    r"\bsuicid", r"\bkill myself\b", r"\bend my life\b",
    # Tamil (unverified): chest pain, breathlessness, fainting/unconscious, bleeding, stroke/paralysis, fits
    r"நெஞ்சு ?வலி", r"நெஞ்சுவலி", r"மார்பு ?வலி", r"மூச்சு ?(த்)?திணறல்", r"மூச்சு விட முடிய",
    r"மயக்கம்", r"மயங்கி", r"ரத்தப்போக்கு", r"இரத்தப்போக்கு", r"பக்கவாதம்", r"வலிப்பு",
]

DOSE_CHANGE = [
    r"\b(double|increase|decrease|reduce|halve|raise|lower|change|adjust|cut)\b.{0,30}\b(dose|dosage|insulin|units?|mg)\b",
    r"\b(double|increase|decrease|reduce|halve|change|adjust|cut)\s+(the |my |this |that )?(tablets?|pills?|medicines?|medication|meds|capsules?)\b",
    r"\b(more|less|extra|another|fewer)\s+(of )?(the |my |this )?(dose|dosage|tablets?|pills?|medicines?|medication|meds|insulin|capsules?)\b",
    r"\b(dose|dosage)\b.{0,30}\b(double|increase|decrease|reduce|halve|higher|lower|change)\b",
    r"\b(stop|skip|quit|discontinue)\b.{0,25}\b(taking|tablets?|pills?|medicines?|medication|meds|insulin|it|them)\b",
    r"\btake (two|2|three|3|an extra|another|one more|double)\b",
    r"\bmissed\b.{0,40}\b(dose|tablets?|pills?|medicines?|insulin|it)\b.{0,40}\b(now|should|can|what do)\b",
    # Tamil (unverified): stop, increase, dose
    r"நிறுத்த", r"அதிகம(ா|ாக)?.{0,15}(மாத்திரை|மருந்து)", r"டோஸ்",
]

NEW_MEDICINE = [
    r"\bwhat (should|can|do) i take\b", r"\b(which|what) (medicine|tablet|pill|drug|syrup)s?\b.{0,20}\b(for|should|can|to)\b",
    r"\b(recommend|suggest|prescribe)\b.{0,20}\b(medicine|tablet|pill|drug|something)\b",
    r"\b(painkiller|antibiotic)s?\b.{0,20}\b(for|should|can)\b", r"\bcan i (take|have) (a |an |some )?(paracetamol|crocin|dolo|antibiotic|painkiller|ibuprofen)\b",
    r"\bfor (my|a|the) (headache|fever|cold|cough|pain)\b.{0,20}\b(take|medicine|tablet)\b",
    # Tamil (unverified): "what tablet", "what medicine"
    r"என்ன மாத்திரை", r"என்ன மருந்து",
]

DIAGNOSIS = [
    r"\bdo i have\b", r"\bdiagnos", r"\bwhat (disease|illness|condition|problem) (do i|have i|is)\b",
    r"\bis (it|this|my) (cancer|serious|dangerous|diabetes|infection)\b",
    r"\bis my (bp|blood pressure|sugar|blood sugar|report|result|level|hba1c|cholesterol)\b.{0,20}\b(normal|high|low|bad|ok(ay)?|dangerous|fine|good)\b",
    r"\bam i (sick|ok(ay)?|fine|diabetic|healthy|going to)\b", r"\bwhy (do|am) i (feel|have|get)\b",
    # Tamil (unverified): "what disease", "is it serious"
    r"என்ன நோய்", r"ஆபத்தா",
]

_COMPILED = {
    "emergency": [re.compile(p, re.I) for p in EMERGENCY],
    "dose_change": [re.compile(p, re.I) for p in DOSE_CHANGE],
    "new_medicine": [re.compile(p, re.I) for p in NEW_MEDICINE],
    "diagnosis": [re.compile(p, re.I) for p in DIAGNOSIS],
}


@dataclass
class Verdict:
    kind: str            # emergency | dose_change | new_medicine | diagnosis | ok
    pattern: str | None = None

    @property
    def blocked(self) -> bool:
        return self.kind != "ok"


def classify(question: str) -> Verdict:
    q = " ".join((question or "").split())
    for kind in ("emergency", "dose_change", "new_medicine", "diagnosis"):
        for rx in _COMPILED[kind]:
            if rx.search(q):
                return Verdict(kind, rx.pattern)
    return Verdict("ok")

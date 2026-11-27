"""After-visit loop: Record (consent) -> transcribe -> extract -> review/edit -> confirm -> translate -> hear -> ask.

Endpoints (all require login; data is always scoped to the signed-in patient):
  POST   /api/visits/record                 multipart audio + consent=true  -> draft visit with transcript
  POST   /api/visits/typed                  json transcript (typed / pasted)  -> draft visit
  POST   /api/visits/{id}/extract           LLM (or rules) -> draft instructions, each traced to the transcript
  PUT    /api/visits/{id}/instructions      patient edits the draft
  POST   /api/visits/{id}/confirm           only now is anything saved as the patient's record
  DELETE /api/visits/{id}                   discard
  GET    /api/visits, /api/visits/{id}
  POST   /api/visits/{id}/translate         machine translation of CONFIRMED instructions (marked unverified)
  PUT    /api/visits/instructions/{iid}/translations/{lang}   human edit / mark verified
  GET    /api/visits/instructions/{iid}/audio?lang=ta        cached ElevenLabs TTS for one instruction
  GET    /api/visits/phrases/{kind}/audio?lang=ta            cached TTS for fixed safety messages
  POST   /api/visits/{id}/prewarm           generate + cache all audio for a visit (demo prep)
  POST   /api/visits/ask                    safety rules -> match confirmed instructions only
"""
from __future__ import annotations

import hashlib
import re
import time
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core import languages as L
from app.core.config import settings
from app.core.deps import client_ip, get_current_user
from app.core.llm import LLMUnavailable
from app.core.ratelimit import limit
from app.database.session import get_db
from app.models import Consultation, DoctorInstruction, MedicalDocument, User, utcnow
from app.models.visits import CATEGORIES, AudioClip, InstructionTranslation, PhraseTranslation, Visit, VisitInstruction
from app.rag.indexer import index_source
from app.safety import MESSAGES, TAMIL_TEXT_VERIFIED, classify
from app.services import extraction as docx
from app.services import storage, visit_ai
from app.services.audit import audit
from app.voice import elevenlabs as el

router = APIRouter(prefix="/api/visits", tags=["visits"])
PHRASES = ("emergency", "dose_change", "new_medicine", "diagnosis", "not_found")


def _lang_ok(v: str) -> str:
    if not L.supported(v):
        raise ValueError("Unsupported language.")
    return v
MAX_AUDIO = 25 * 1024 * 1024
AUDIO_TYPES = ("audio/", "video/webm", "video/mp4", "application/octet-stream")


# ------------------------------------------------------------------ schemas
class TypedIn(BaseModel):
    transcript: str = Field(min_length=10, max_length=20000)
    doctor_name: str = Field(default="", max_length=120)
    visit_date: date | None = None
    source: str = Field(default="typed", pattern="^(typed|sample)$")


class InstructionIn(BaseModel):
    id: int | None = None
    category: str = "other"
    source_sentence: str = Field(default="", max_length=2000)
    simple_text: str = Field(min_length=2, max_length=600)


class InstructionsIn(BaseModel):
    doctor_name: str | None = Field(default=None, max_length=120)
    visit_date: date | None = None
    instructions: list[InstructionIn] = Field(max_length=30)


class TranslateIn(BaseModel):
    lang: str = Field(max_length=10)
    _v = field_validator("lang")(_lang_ok)


class TranslationEditIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    verified: bool = False
    reviewer: str | None = Field(default=None, max_length=120)


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    lang: str = Field(default="en", max_length=10)
    _v = field_validator("lang")(_lang_ok)


class PrewarmIn(BaseModel):
    langs: list[str] = Field(default_factory=lambda: ["en", "ta"])


# ------------------------------------------------------------------ helpers
def _ai_consent(user: User) -> None:
    if not (user.profile and user.profile.ai_data_consent):
        raise HTTPException(403, "This sends text or audio to AI and voice services. Turn on 'AI & voice processing' in Settings first.")


def _get(db: Session, user: User, vid: int) -> Visit:
    v = db.scalar(select(Visit).options(selectinload(Visit.instructions).selectinload(VisitInstruction.translations))
                  .where(Visit.id == vid, Visit.owner_id == user.id))
    if not v:
        raise HTTPException(404, "Visit not found.")
    return v


def _draft(v: Visit) -> None:
    if v.status != "draft":
        raise HTTPException(409, "This visit is already confirmed. Confirmed instructions can't be changed here.")


def _tr(ins: VisitInstruction, lang: str) -> InstructionTranslation | None:
    return next((t for t in ins.translations if t.lang == lang), None)


def _text(ins: VisitInstruction, lang: str) -> tuple[str | None, bool]:
    """Text to show/speak in a language and whether it is verified."""
    if lang == "en":
        return ins.simple_text, True
    t = _tr(ins, lang)
    return (t.text, t.verified) if t else (None, False)


def _ins_out(ins: VisitInstruction) -> dict:
    return {
        "id": ins.id, "position": ins.position, "category": ins.category, "source_sentence": ins.source_sentence,
        "simple_text": ins.simple_text, "needs_check": ins.needs_check, "check_reason": ins.check_reason,
        "edited_by_user": ins.edited_by_user,
        "translations": {t.lang: {"text": t.text, "method": t.method, "verified": t.verified, "verified_by": t.verified_by}
                         for t in ins.translations},
    }


def _out(v: Visit) -> dict:
    return {
        "id": v.id, "doctor_name": v.doctor_name, "visit_date": v.visit_date.isoformat(), "status": v.status,
        "source": v.source, "document_id": v.document_id, "text_method": v.text_method, "recording_consent_at": v.recording_consent_at.isoformat() if v.recording_consent_at else None,
        "transcript": v.transcript, "transcript_language": v.transcript_language,
        "extraction_method": v.extraction_method, "confirmed_at": v.confirmed_at.isoformat() if v.confirmed_at else None,
        "instructions": [_ins_out(i) for i in v.instructions],
        "tamil_ui_text_verified": TAMIL_TEXT_VERIFIED,
    }


def _voice_for(lang: str, user: User) -> str:
    if lang == "ta" and settings.elevenlabs_voice_id_ta:
        return settings.elevenlabs_voice_id_ta
    return (user.profile.voice_id if user.profile and user.profile.voice_id else None) or settings.elevenlabs_voice_id


def _clip_key(model: str, voice: str, lang: str, text: str) -> str:
    return hashlib.sha256(f"{model}|{voice}|{lang}|{text}".encode()).hexdigest()


def get_audio(db: Session, text: str, lang: str, voice: str) -> tuple[bytes, bool]:
    """Returns (mp3 bytes, cache_hit)."""
    model = settings.elevenlabs_tts_model if L.tts_model(lang) == L.V2 else L.V3
    key = _clip_key(model, voice, lang, text)
    clip = db.get(AudioClip, key)
    if clip:
        return clip.data, True
    try:
        data = el.synthesize(re.sub(r"[*#_`]", "", text)[:2500], voice, model)
    except el.VoiceNotConfigured as exc:
        raise HTTPException(503, str(exc))
    except el.VoiceProviderError as exc:
        raise HTTPException(exc.status, str(exc))
    db.add(AudioClip(key=key, lang=lang, model=model, voice_id=voice, data=data))
    db.commit()
    return data, False


def _mp3(data: bytes, hit: bool, verified: bool) -> Response:
    return Response(content=data, media_type="audio/mpeg", headers={
        "Cache-Control": "private, max-age=86400", "X-Audio-Cache": "hit" if hit else "miss",
        "X-Translation-Verified": "true" if verified else "false",
        "Access-Control-Expose-Headers": "X-Audio-Cache, X-Translation-Verified"})


def get_phrase(db: Session, kind: str, lang: str) -> tuple[str, str, bool]:
    """(text, text_lang, verified) for a fixed safety message. Falls back to English if it can't be translated."""
    if lang == "en":
        return MESSAGES[kind]["en"], "en", True
    if lang in MESSAGES[kind]:
        return MESSAGES[kind][lang], lang, TAMIL_TEXT_VERIFIED if lang == "ta" else False
    row = db.scalar(select(PhraseTranslation).where(PhraseTranslation.kind == kind, PhraseTranslation.lang == lang))
    if row:
        return row.text, lang, row.verified
    try:
        out = visit_ai.translate([(1, MESSAGES[kind]["en"])], lang)
    except LLMUnavailable:
        out = {}
    if not out.get(1):
        return MESSAGES[kind]["en"], "en", True
    db.add(PhraseTranslation(kind=kind, lang=lang, text=out[1]))
    db.commit()
    return out[1], lang, False


@router.get("/languages")
def list_languages(user: User = Depends(get_current_user)):
    return {"languages": L.catalogue(), "default": (user.profile.preferred_language if user.profile else None) or "en",
            "llm_configured": settings.llm_enabled}


# ------------------------------------------------------------------ capture
@router.post("/record", status_code=201)
async def record(request: Request, file: UploadFile = File(...), consent: bool = Form(...),
                 consent_note: str | None = Form(None), doctor_name: str = Form(""), visit_date: date | None = Form(None),
                 language_code: str | None = Form(None),
                 user: User = Depends(limit("visit_record", 6)), db: Session = Depends(get_db)):
    if not consent:
        raise HTTPException(400, "Recording needs the consent of everyone in the room. Please confirm consent first.")
    _ai_consent(user)
    audio = await file.read(MAX_AUDIO + 1)
    if not audio:
        raise HTTPException(400, "No audio was received. Please try again.")
    if len(audio) > MAX_AUDIO:
        raise HTTPException(413, "Recording is too large. Please keep it under about 15 minutes.")
    ctype = file.content_type or "application/octet-stream"
    if not ctype.startswith(AUDIO_TYPES):
        raise HTTPException(415, "Unsupported audio format.")
    if language_code and not re.fullmatch(r"[a-z]{2,3}", language_code):
        language_code = None
    try:
        result = el.transcribe(audio, file.filename or "visit.webm", ctype, language_code)
    except el.VoiceNotConfigured as exc:
        raise HTTPException(503, str(exc))
    except el.VoiceProviderError as exc:
        raise HTTPException(exc.status, str(exc))
    if not result["text"]:
        raise HTTPException(422, "No speech was detected in the recording.")
    # The audio itself is NOT stored; only the transcript, as a draft.
    v = Visit(owner_id=user.id, doctor_name=doctor_name.strip()[:120], visit_date=visit_date or date.today(),
              source="recording", recording_consent_at=utcnow(), consent_note=(consent_note or "")[:255] or None,
              transcript=result["text"], transcript_language=result.get("language_code"), text_method="speech_to_text")
    db.add(v)
    db.flush()
    audit(db, user.id, "visit.record", "visit", v.id, detail=f"{len(audio)} bytes, audio not stored", ip=client_ip(request))
    db.commit()
    return _out(_get(db, user, v.id))


@router.post("/document", status_code=201)
async def from_document(request: Request, file: UploadFile = File(...), doctor_name: str = Form(""),
                        visit_date: date | None = Form(None),
                        user: User = Depends(limit("visit_document", 10)), db: Session = Depends(get_db)):
    """A prescription / doctor's note becomes a draft visit, reviewed exactly like a recording."""
    max_bytes = settings.max_upload_mb * 1024 * 1024
    content = await file.read(max_bytes + 1)
    if not content:
        raise HTTPException(400, "The file is empty.")
    if len(content) > max_bytes:
        raise HTTPException(413, f"File is too large. Maximum size is {settings.max_upload_mb} MB.")
    filename = (file.filename or "document").split("/")[-1].split("\\")[-1][:200]
    mime = docx.sniff_mime(content, filename)
    if mime not in docx.ALLOWED_TYPES:
        raise HTTPException(415, "Please upload a PDF, photo (JPG/PNG/WEBP) or text file.")
    res = docx.extract_text(content, mime)
    text, method = res.text.strip(), res.method
    if len(text) < 40 and mime != "text/plain" and settings.llm_enabled:
        _ai_consent(user)
        img, img_mime = content, mime
        if mime == "application/pdf":
            import pymupdf
            img, img_mime = pymupdf.open(stream=content, filetype="pdf")[0].get_pixmap(dpi=170).tobytes("png"), "image/png"
        try:
            text, method = visit_ai.read_image(img, img_mime), "ai_vision"
        except LLMUnavailable:
            pass
    if len(text) < 10:
        raise HTTPException(422, "I couldn't read text from this file. Try a clearer, well-lit photo, or type the instructions.")
    stored = storage.save_file(user.id, content, docx.ALLOWED_TYPES[mime])
    doc = MedicalDocument(owner_id=user.id, title=(filename.rsplit(".", 1)[0] or "Document")[:200], doc_type="prescription",
                          original_filename=filename, stored_filename=stored, mime_type=mime, size_bytes=len(content),
                          status="pending_review", document_date=visit_date)
    db.add(doc)
    db.flush()
    v = Visit(owner_id=user.id, doctor_name=doctor_name.strip()[:120], visit_date=visit_date or date.today(), source="document",
              document_id=doc.id, transcript=text[:20000], text_method=method)
    db.add(v)
    db.flush()
    audit(db, user.id, "visit.document", "visit", v.id, detail=f"{mime}, {len(content)} bytes, {method}", ip=client_ip(request))
    db.commit()
    return _out(_get(db, user, v.id))


@router.post("/typed", status_code=201)
def typed(body: TypedIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    v = Visit(owner_id=user.id, doctor_name=body.doctor_name.strip(), visit_date=body.visit_date or date.today(),
              source=body.source, transcript=body.transcript.strip(), text_method="typed")
    db.add(v)
    db.flush()
    audit(db, user.id, "visit.typed", "visit", v.id, ip=client_ip(request))
    db.commit()
    return _out(_get(db, user, v.id))


@router.post("/{vid}/extract")
def extract(vid: int, request: Request, user: User = Depends(limit("visit_extract", 10)), db: Session = Depends(get_db)):
    v = _get(db, user, vid)
    _draft(v)
    if settings.llm_enabled:
        _ai_consent(user)
    t0 = time.perf_counter()
    method, doctor, items = visit_ai.extract(v.transcript)
    v.instructions.clear()
    db.flush()
    for i, it in enumerate(items):
        v.instructions.append(VisitInstruction(owner_id=user.id, position=i, category=it["category"],
                                               source_sentence=it["source_sentence"], simple_text=it["simple_text"],
                                               needs_check=it["needs_check"], check_reason=it["check_reason"]))
    v.extraction_method = method
    if doctor and not v.doctor_name:
        v.doctor_name = doctor
    audit(db, user.id, "visit.extract", "visit", v.id, detail=f"{method}, {len(items)} items", ip=client_ip(request))
    db.commit()
    out = _out(_get(db, user, vid))
    out["timing_ms"] = round((time.perf_counter() - t0) * 1000)
    return out


@router.put("/{vid}/instructions")
def edit_instructions(vid: int, body: InstructionsIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    v = _get(db, user, vid)
    _draft(v)
    old = {i.id: i for i in v.instructions}
    v.instructions.clear()
    db.flush()
    for pos, it in enumerate(body.instructions):
        prev = old.get(it.id) if it.id else None
        changed = prev is None or prev.simple_text != it.simple_text or prev.source_sentence != it.source_sentence
        checked = visit_ai.check_item({"source_sentence": it.source_sentence, "simple_text": it.simple_text}, v.transcript)
        v.instructions.append(VisitInstruction(
            owner_id=user.id, position=pos, category=it.category if it.category in CATEGORIES else "other",
            source_sentence=it.source_sentence, simple_text=it.simple_text.strip(),
            # a patient edit is the patient's own check; keep only the machine checks as a hint
            needs_check=False if changed else checked["needs_check"],
            check_reason=None if changed else checked["check_reason"],
            edited_by_user=bool(prev and prev.edited_by_user) or changed))
    if body.doctor_name is not None:
        v.doctor_name = body.doctor_name.strip()
    if body.visit_date:
        v.visit_date = body.visit_date
    db.commit()
    return _out(_get(db, user, vid))


@router.post("/{vid}/confirm")
def confirm(vid: int, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    v = _get(db, user, vid)
    _draft(v)
    if not v.instructions:
        raise HTTPException(400, "There are no instructions to confirm.")
    c = Consultation(owner_id=user.id, doctor_name=v.doctor_name or "Doctor", consultation_date=v.visit_date,
                     doctor_notes="Instructions confirmed by the patient after the visit.", status="confirmed")
    c.instructions = [DoctorInstruction(text=i.simple_text) for i in v.instructions]
    db.add(c)
    db.flush()
    v.consultation_id, v.status, v.confirmed_at = c.id, "confirmed", utcnow()
    if v.document_id:
        d = db.get(MedicalDocument, v.document_id)
        if d and d.owner_id == user.id:
            d.status, d.consultation_id = "confirmed", c.id
    for i in v.instructions:
        i.needs_check = False
    index_source(db, user.id, "consultation", c)
    audit(db, user.id, "visit.confirm", "visit", v.id, detail=f"{len(v.instructions)} instructions", ip=client_ip(request))
    db.commit()
    return _out(_get(db, user, vid))


@router.delete("/{vid}", status_code=204)
def discard(vid: int, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    v = _get(db, user, vid)
    db.delete(v)
    audit(db, user.id, "visit.delete", "visit", vid, ip=client_ip(request))
    db.commit()


@router.get("")
def list_visits(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    vs = db.scalars(select(Visit).options(selectinload(Visit.instructions).selectinload(VisitInstruction.translations))
                    .where(Visit.owner_id == user.id).order_by(Visit.visit_date.desc(), Visit.id.desc())).all()
    return [_out(v) for v in vs]


@router.get("/{vid}")
def get_visit(vid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _out(_get(db, user, vid))


# ------------------------------------------------------------------ translate & listen
@router.post("/{vid}/translate")
def translate(vid: int, body: TranslateIn, request: Request, user: User = Depends(limit("visit_translate", 10)),
              db: Session = Depends(get_db)):
    v = _get(db, user, vid)
    if v.status != "confirmed":
        raise HTTPException(409, "Confirm the instructions first. Only confirmed instructions are translated.")
    if body.lang == "en":
        return _out(v)
    _ai_consent(user)
    todo = [(i.id, i.simple_text) for i in v.instructions if not (_tr(i, body.lang) and _tr(i, body.lang).method == "human")]
    try:
        result = visit_ai.translate(todo, body.lang) if todo else {}
    except LLMUnavailable as exc:
        raise HTTPException(503, f"Translation is unavailable: {exc}")
    for i in v.instructions:
        if i.id in result:
            t = _tr(i, body.lang)
            if t:
                t.text, t.method, t.verified, t.verified_by, t.verified_at = result[i.id], "machine", False, None, None
            else:
                i.translations.append(InstructionTranslation(lang=body.lang, text=result[i.id]))
    audit(db, user.id, "visit.translate", "visit", v.id, detail=f"{body.lang}: {len(result)}", ip=client_ip(request))
    db.commit()
    return _out(_get(db, user, vid))


@router.put("/instructions/{iid}/translations/{lang}")
def edit_translation(iid: int, lang: str, body: TranslationEditIn, request: Request,
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not L.supported(lang) or lang == "en":
        raise HTTPException(400, "Unsupported language.")
    ins = db.scalar(select(VisitInstruction).options(selectinload(VisitInstruction.translations))
                    .where(VisitInstruction.id == iid, VisitInstruction.owner_id == user.id))
    if not ins:
        raise HTTPException(404, "Instruction not found.")
    if body.verified and not (body.reviewer or "").strip():
        raise HTTPException(400, "Enter the reviewer's name to mark a translation as verified.")
    t = _tr(ins, lang)
    if not t:
        t = InstructionTranslation(lang=lang, text=body.text)
        ins.translations.append(t)
    t.text, t.method = body.text.strip(), "human"
    t.verified, t.verified_by = body.verified, (body.reviewer or "").strip() or None
    t.verified_at = utcnow() if body.verified else None
    audit(db, user.id, "translation.edit", "instruction", iid, detail=f"{lang} verified={body.verified}", ip=client_ip(request))
    db.commit()
    return _ins_out(ins)


@router.get("/instructions/{iid}/audio")
def instruction_audio(iid: int, lang: str = "en", user: User = Depends(limit("visit_audio", 120)), db: Session = Depends(get_db)):
    if not L.supported(lang):
        raise HTTPException(400, "Unsupported language.")
    ins = db.scalar(select(VisitInstruction).options(selectinload(VisitInstruction.translations), selectinload(VisitInstruction.visit))
                    .where(VisitInstruction.id == iid, VisitInstruction.owner_id == user.id))
    if not ins:
        raise HTTPException(404, "Instruction not found.")
    if ins.visit.status != "confirmed":
        raise HTTPException(409, "Only confirmed instructions can be played.")
    text, verified = _text(ins, lang)
    if not text:
        raise HTTPException(404, "No translation in this language yet. Translate the visit first.")
    _ai_consent(user)
    data, hit = get_audio(db, text, lang, _voice_for(lang, user))
    return _mp3(data, hit, verified)


@router.get("/phrases/{kind}/audio")
def phrase_audio(kind: str, lang: str = "en", user: User = Depends(limit("visit_audio", 120)), db: Session = Depends(get_db)):
    if not L.supported(lang) or kind not in PHRASES:
        raise HTTPException(400, "Unknown phrase.")
    _ai_consent(user)
    text, tlang, verified = get_phrase(db, kind, lang)
    data, hit = get_audio(db, text, tlang, _voice_for(tlang, user))
    return _mp3(data, hit, verified)


@router.post("/{vid}/prewarm")
def prewarm(vid: int, body: PrewarmIn, user: User = Depends(limit("visit_prewarm", 5)), db: Session = Depends(get_db)):
    v = _get(db, user, vid)
    if v.status != "confirmed":
        raise HTTPException(409, "Confirm the visit first.")
    _ai_consent(user)
    made = cached = missing = 0
    for lang in dict.fromkeys(x for x in body.langs if L.supported(x)):
        texts = [(_text(i, lang)[0], lang) for i in v.instructions]
        texts += [get_phrase(db, k, lang)[:2] for k in PHRASES]
        for t, tl in texts:
            if not t:
                missing += 1
                continue
            _, hit = get_audio(db, t, tl, _voice_for(tl, user))
            cached += hit
            made += not hit
    return {"generated": made, "already_cached": cached, "missing_translation": missing}


# ------------------------------------------------------------------ ask
@router.post("/ask")
def ask(body: AskIn, request: Request, user: User = Depends(limit("visit_ask", 30)), db: Session = Depends(get_db)):
    t0 = time.perf_counter()
    lang = body.lang
    ai_ok = settings.llm_enabled and bool(user.profile and user.profile.ai_data_consent)
    # Safety rules read English (and Tamil) patterns. For other scripts, also check an English rendering.
    english = visit_ai.to_english(body.question) if ai_ok and visit_ai.needs_english(body.question) else None
    verdict = classify(body.question)
    if not verdict.blocked and english:
        verdict = classify(english)
    base = {"question": body.question, "question_english": english, "lang": lang, "matches": [], "matcher": None,
            "safety_checked_in": "original+english" if english else ("original" if not visit_ai.needs_english(body.question) or body.question.isascii() else "original-only (no AI to translate)")}

    def fixed(kind: str, atype: str, reason: str) -> dict:
        text, tlang, verified = get_phrase(db, kind, lang)
        return {**base, "type": atype, "reason": reason, "message": text, "message_lang": tlang, "phrase": kind,
                "message_verified": verified, "timing_ms": round((time.perf_counter() - t0) * 1000)}

    if verdict.blocked:
        audit(db, user.id, f"ask.{verdict.kind}", detail=body.question[:200], ip=client_ip(request))
        db.commit()
        out = fixed(verdict.kind, "emergency" if verdict.kind == "emergency" else "refusal", verdict.kind)
        if verdict.kind == "emergency" and out["message_lang"] != "en":
            out["message_english"] = MESSAGES["emergency"]["en"]  # the 108 instruction is always also shown in English
        return out

    ins_list = db.scalars(select(VisitInstruction).join(Visit)
                          .options(selectinload(VisitInstruction.translations), selectinload(VisitInstruction.visit))
                          .where(VisitInstruction.owner_id == user.id, Visit.status == "confirmed")).all()
    candidates = [{"id": i.id, "category": i.category,
                   "texts": [i.simple_text, i.source_sentence] + [t.text for t in i.translations]} for i in ins_list]
    query = f"{body.question}\n(English: {english})" if english else body.question
    if ai_ok:
        matcher, ids = visit_ai.match(query, candidates)
    else:
        matcher, ids = "keywords", visit_ai.keyword_match(english or body.question, candidates)
    by_id = {i.id: i for i in ins_list}
    if not ids:
        return {**fixed("not_found", "not_found", "not_in_instructions"), "matcher": matcher}

    # Translate any matched instruction that has no text in this language yet (stored, marked unverified).
    if lang != "en" and ai_ok:
        todo = [(i, by_id[i].simple_text) for i in ids if not _tr(by_id[i], lang)]
        if todo:
            try:
                for iid, txt in visit_ai.translate(todo, lang).items():
                    by_id[iid].translations.append(InstructionTranslation(lang=lang, text=txt))
                db.commit()
            except LLMUnavailable:
                pass
    matches = []
    for iid in ids:
        i = by_id[iid]
        text, verified = _text(i, lang)
        matches.append({
            "instruction_id": i.id, "visit_id": i.visit_id, "doctor_name": i.visit.doctor_name,
            "visit_date": i.visit.visit_date.isoformat(), "category": i.category,
            "text": text or i.simple_text, "text_lang": lang if text else "en",
            "translation_verified": verified if text else False,
            "english": i.simple_text, "source_sentence": i.source_sentence})
    return {**base, "type": "grounded", "message": None, "matcher": matcher, "matches": matches,
            "timing_ms": round((time.perf_counter() - t0) * 1000)}

"""End-to-end tests of the after-visit loop with the LLM and ElevenLabs mocked (no network, no keys)."""
import pytest

from app.api import visits as visits_api
from app.core import ratelimit
from app.core.llm import LLMUnavailable
from app.services import visit_ai

TRANSCRIPT = (
    "Doctor: Good morning Lakshmi amma. Your sugar is a little high. "
    "Take Metformin 500 mg one tablet after breakfast and one after dinner. "
    "Take Amlodipine 5 mg once in the morning. "
    "Avoid sweets and reduce rice at night. "
    "Walk for 30 minutes every evening. "
    "Do an HbA1c blood test before the next visit. "
    "Come back after one month."
)


@pytest.fixture(autouse=True)
def _reset_limits():
    ratelimit.reset()
    yield


@pytest.fixture
def no_llm(monkeypatch):
    def fail(*a, **k):
        raise LLMUnavailable("off")
    monkeypatch.setattr(visit_ai, "chat_json", fail)


@pytest.fixture
def fake_tts(monkeypatch):
    calls = []

    def synth(text, voice_id=None, model_id=None):
        calls.append((text, voice_id))
        return b"ID3fake-mp3-" + text.encode()[:20]
    monkeypatch.setattr(visits_api.el, "synthesize", synth)
    return calls


def consent(client, auth):
    client.patch("/api/auth/me", headers=auth, json={"ai_data_consent": True})


def make_confirmed(client, auth):
    v = client.post("/api/visits/typed", headers=auth, json={"transcript": TRANSCRIPT, "doctor_name": "Dr. Kavitha Rao"}).json()
    v = client.post(f"/api/visits/{v['id']}/extract", headers=auth).json()
    v = client.post(f"/api/visits/{v['id']}/confirm", headers=auth).json()
    return v


# ---------------------------------------------------------------- capture & review
def test_record_requires_consent_flag(client, auth):
    consent(client, auth)
    r = client.post("/api/visits/record", headers=auth, data={"consent": "false"},
                    files={"file": ("a.webm", b"x" * 10, "audio/webm")})
    assert r.status_code == 400 and "consent" in r.json()["detail"].lower()


def test_record_requires_login(client):
    r = client.post("/api/visits/record", data={"consent": "true"}, files={"file": ("a.webm", b"x", "audio/webm")})
    assert r.status_code == 401


def test_record_transcribes_and_stores_draft_only(client, auth, monkeypatch):
    consent(client, auth)
    monkeypatch.setattr(visits_api.el, "transcribe", lambda *a, **k: {"text": TRANSCRIPT, "language_code": "en"})
    r = client.post("/api/visits/record", headers=auth, data={"consent": "true", "doctor_name": "Dr. Kavitha Rao"},
                    files={"file": ("a.webm", b"x" * 100, "audio/webm")})
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["status"] == "draft" and v["recording_consent_at"] and v["transcript"].startswith("Doctor:")
    # nothing confirmed yet -> Ask cannot use it
    a = client.post("/api/visits/ask", headers=auth, json={"question": "When do I take Metformin?"}).json()
    assert a["type"] == "not_found"


def test_rule_extraction_without_llm(client, auth, no_llm):
    v = client.post("/api/visits/typed", headers=auth, json={"transcript": TRANSCRIPT}).json()
    v = client.post(f"/api/visits/{v['id']}/extract", headers=auth).json()
    assert v["extraction_method"] == "rules"
    cats = {i["category"] for i in v["instructions"]}
    assert {"medicine", "diet", "test", "follow_up", "lifestyle"} <= cats
    assert all(not i["needs_check"] for i in v["instructions"])  # rules quote the transcript verbatim


def test_llm_extraction_hallucination_is_flagged(client, auth, monkeypatch):
    consent(client, auth)
    monkeypatch.setattr(visit_ai, "chat_json", lambda *a, **k: {"doctor_name": "Dr. Kavitha Rao", "instructions": [
        {"category": "medicine", "source_sentence": "Take Metformin 500 mg one tablet after breakfast and one after dinner.",
         "simple_text": "Take Metformin 500 mg after breakfast and after dinner."},
        {"category": "medicine", "source_sentence": "Take Metformin 500 mg one tablet after breakfast",
         "simple_text": "Take Metformin 1000 mg after breakfast."},                       # number not said
        {"category": "medicine", "source_sentence": "Take aspirin 75 mg daily.",            # never said
         "simple_text": "Take aspirin 75 mg daily."},
    ]})
    v = client.post("/api/visits/typed", headers=auth, json={"transcript": TRANSCRIPT}).json()
    v = client.post(f"/api/visits/{v['id']}/extract", headers=auth).json()
    ok, bad_num, invented = v["instructions"]
    assert v["extraction_method"] == "llm" and v["doctor_name"] == "Dr. Kavitha Rao"
    assert not ok["needs_check"]
    assert bad_num["needs_check"] and "1000" in bad_num["check_reason"]
    assert invented["needs_check"] and "could not be found" in invented["check_reason"]


def test_edit_then_confirm_then_locked(client, auth, no_llm):
    v = client.post("/api/visits/typed", headers=auth, json={"transcript": TRANSCRIPT}).json()
    v = client.post(f"/api/visits/{v['id']}/extract", headers=auth).json()
    items = [{"id": i["id"], "category": i["category"], "source_sentence": i["source_sentence"], "simple_text": i["simple_text"]}
             for i in v["instructions"]]
    items[0]["simple_text"] = "Take Metformin 500 mg after breakfast and after dinner."
    v = client.put(f"/api/visits/{v['id']}/instructions", headers=auth, json={"instructions": items, "doctor_name": "Dr. K"}).json()
    assert v["instructions"][0]["edited_by_user"] and v["doctor_name"] == "Dr. K"
    v = client.post(f"/api/visits/{v['id']}/confirm", headers=auth).json()
    assert v["status"] == "confirmed"
    r = client.put(f"/api/visits/{v['id']}/instructions", headers=auth, json={"instructions": items})
    assert r.status_code == 409
    # confirmed visit also appears as a normal consultation record
    cons = client.get("/api/consultations", headers=auth).json()
    assert any(c["doctor_name"] == "Dr. K" for c in cons)


def test_other_user_cannot_see_visit(client, auth, other_auth, no_llm):
    v = make_confirmed(client, auth)
    assert client.get(f"/api/visits/{v['id']}", headers=other_auth).status_code == 404
    iid = v["instructions"][0]["id"]
    assert client.get(f"/api/visits/instructions/{iid}/audio", headers=other_auth).status_code == 404
    a = client.post("/api/visits/ask", headers=other_auth, json={"question": "When do I take Metformin?"}).json()
    assert a["type"] == "not_found"


# ---------------------------------------------------------------- translation & audio
def test_translate_requires_confirmed_and_marks_unverified(client, auth, monkeypatch, no_llm):
    consent(client, auth)
    v = client.post("/api/visits/typed", headers=auth, json={"transcript": TRANSCRIPT}).json()
    v = client.post(f"/api/visits/{v['id']}/extract", headers=auth).json()
    assert client.post(f"/api/visits/{v['id']}/translate", headers=auth, json={"lang": "ta"}).status_code == 409
    v = client.post(f"/api/visits/{v['id']}/confirm", headers=auth).json()
    monkeypatch.setattr(visit_ai, "chat_json", lambda *a, **k: {
        "translations": [{"id": i["id"], "text": f"தமிழ் {n}"} for n, i in enumerate(v["instructions"])]})
    v = client.post(f"/api/visits/{v['id']}/translate", headers=auth, json={"lang": "ta"}).json()
    ta = v["instructions"][0]["translations"]["ta"]
    assert ta["method"] == "machine" and ta["verified"] is False


def test_translation_verify_needs_reviewer(client, auth, no_llm):
    v = make_confirmed(client, auth)
    iid = v["instructions"][0]["id"]
    r = client.put(f"/api/visits/instructions/{iid}/translations/ta", headers=auth, json={"text": "தமிழ்", "verified": True})
    assert r.status_code == 400
    r = client.put(f"/api/visits/instructions/{iid}/translations/ta", headers=auth,
                   json={"text": "மெட்ஃபார்மின் 500 mg", "verified": True, "reviewer": "Reviewer A"})
    assert r.status_code == 200 and r.json()["translations"]["ta"]["verified"] is True


def test_audio_cached_per_instruction_and_language(client, auth, no_llm, fake_tts):
    consent(client, auth)
    v = make_confirmed(client, auth)
    iid = v["instructions"][0]["id"]
    r1 = client.get(f"/api/visits/instructions/{iid}/audio?lang=en", headers=auth)
    r2 = client.get(f"/api/visits/instructions/{iid}/audio?lang=en", headers=auth)
    assert r1.status_code == 200 and r1.headers["x-audio-cache"] == "miss"
    assert r2.headers["x-audio-cache"] == "hit" and r2.content == r1.content
    assert len(fake_tts) == 1
    # Tamil not translated yet -> 404, never falls back to speaking English silently
    assert client.get(f"/api/visits/instructions/{iid}/audio?lang=ta", headers=auth).status_code == 404
    client.put(f"/api/visits/instructions/{iid}/translations/ta", headers=auth, json={"text": "தமிழ் உரை"})
    r3 = client.get(f"/api/visits/instructions/{iid}/audio?lang=ta", headers=auth)
    assert r3.status_code == 200 and r3.headers["x-translation-verified"] == "false"


def test_audio_needs_ai_consent(client, auth, no_llm, fake_tts):
    v = make_confirmed(client, auth)
    iid = v["instructions"][0]["id"]
    assert client.get(f"/api/visits/instructions/{iid}/audio", headers=auth).status_code == 403


def test_prewarm(client, auth, no_llm, fake_tts):
    consent(client, auth)
    v = make_confirmed(client, auth)
    r = client.post(f"/api/visits/{v['id']}/prewarm", headers=auth, json={"langs": ["en"]}).json()
    assert r["generated"] == len(v["instructions"]) + 5
    r = client.post(f"/api/visits/{v['id']}/prewarm", headers=auth, json={"langs": ["en"]}).json()
    assert r["generated"] == 0 and r["already_cached"] == len(v["instructions"]) + 5


# ---------------------------------------------------------------- ask
def test_ask_grounded_with_source_sentence(client, auth, no_llm):
    make_confirmed(client, auth)
    a = client.post("/api/visits/ask", headers=auth, json={"question": "When should I take Metformin?"}).json()
    assert a["type"] == "grounded" and a["matcher"] == "keywords"
    assert any("Metformin" in m["source_sentence"] for m in a["matches"])
    assert all(m["doctor_name"] == "Dr. Kavitha Rao" for m in a["matches"])


def test_ask_not_in_record(client, auth, no_llm):
    make_confirmed(client, auth)
    a = client.post("/api/visits/ask", headers=auth, json={"question": "Can I play cricket on Sunday?"}).json()
    assert a["type"] == "not_found" and a["matches"] == []
    assert a["message"] == "That isn't in your saved instructions. Please ask your doctor."


@pytest.mark.parametrize("q,reason", [
    ("Can I double the dose of Metformin?", "dose_change"),
    ("What should I take for a headache?", "new_medicine"),
    ("Do I have diabetes?", "diagnosis"),
])
def test_ask_refusals_do_not_use_records(client, auth, no_llm, q, reason):
    make_confirmed(client, auth)
    a = client.post("/api/visits/ask", headers=auth, json={"question": q}).json()
    assert a["type"] == "refusal" and a["reason"] == reason and a["matches"] == []


def test_ask_emergency_returns_108_and_no_records(client, auth, monkeypatch, no_llm):
    make_confirmed(client, auth)
    called = []
    monkeypatch.setattr(visit_ai, "match", lambda *a, **k: called.append(1) or ("llm", []))
    a = client.post("/api/visits/ask", headers=auth, json={"question": "I have chest pain and need my tablet", "lang": "ta"}).json()
    assert a["type"] == "emergency" and "108" in a["message"] and a["matches"] == []
    assert called == []  # records were never consulted


def test_llm_matcher_cannot_return_foreign_ids(client, auth, other_auth, monkeypatch, no_llm):
    consent(client, auth)
    other = make_confirmed(client, other_auth)
    make_confirmed(client, auth)
    foreign = other["instructions"][0]["id"]
    monkeypatch.setattr(visits_api.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(visit_ai, "chat_json", lambda *a, **k: {"ids": [foreign, 99999]})
    a = client.post("/api/visits/ask", headers=auth, json={"question": "When do I take Metformin?"}).json()
    assert a["type"] == "not_found" and a["matcher"] == "llm"


def test_ask_in_tamil_returns_tamil_text_and_flag(client, auth, no_llm):
    v = make_confirmed(client, auth)
    iid = next(i["id"] for i in v["instructions"] if "Metformin" in i["simple_text"])
    client.put(f"/api/visits/instructions/{iid}/translations/ta", headers=auth, json={"text": "மெட்ஃபார்மின் காலை உணவுக்குப் பின்"})
    a = client.post("/api/visits/ask", headers=auth, json={"question": "When should I take Metformin?", "lang": "ta"}).json()
    m = next(m for m in a["matches"] if m["instruction_id"] == iid)
    assert m["text_lang"] == "ta" and m["translation_verified"] is False


def test_rate_limit_on_ask(client, auth, no_llm):
    for _ in range(30):
        client.post("/api/visits/ask", headers=auth, json={"question": "hello there"})
    assert client.post("/api/visits/ask", headers=auth, json={"question": "hello there"}).status_code == 429


# ---------------------------------------------------------------- documents go through the same review
def test_document_upload_becomes_reviewable_visit(client, auth, no_llm):
    note = ("Dr. Kavitha Rao, General Physician\nTake Metformin 500 mg after breakfast and after dinner.\n"
            "Avoid sweets. Come back after one month.").encode()
    v = client.post("/api/visits/document", headers=auth, files={"file": ("note.txt", note, "text/plain")}).json()
    assert v["source"] == "document" and v["text_method"] == "text" and v["status"] == "draft" and v["document_id"]
    v = client.post(f"/api/visits/{v['id']}/extract", headers=auth).json()
    assert any("Metformin" in i["simple_text"] for i in v["instructions"])
    v = client.post(f"/api/visits/{v['id']}/confirm", headers=auth).json()
    doc = client.get(f"/api/documents/{v['document_id']}", headers=auth).json()
    assert doc["status"] == "confirmed"


def test_document_rejects_unknown_type(client, auth):
    r = client.post("/api/visits/document", headers=auth, files={"file": ("x.exe", b"MZ\x90\x00binary", "application/octet-stream")})
    assert r.status_code == 415


def test_unreadable_image_without_llm_gives_clear_message(client, auth, no_llm):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buf, "PNG")
    r = client.post("/api/visits/document", headers=auth, files={"file": ("blank.png", buf.getvalue(), "image/png")})
    assert r.status_code == 422 and "couldn't read" in r.json()["detail"].lower()



# ---------------------------------------------------------------- many languages
def fake_llm(monkeypatch, english, ids_for=None, translated="అనువాదం"):
    """Routes the stubbed LLM by its system prompt."""
    def chat(system, user, **k):
        if system.startswith("Translate the patient's question"):
            return {"english": english}
        if system.startswith("Translate each medical instruction"):
            import re as _re
            return {"translations": [{"id": int(i), "text": f"{translated} {i}"} for i in _re.findall(r'"id": (\d+)', user)]}
        if system.startswith("A patient asks"):
            return {"ids": ids_for or []}
        raise LLMUnavailable("not stubbed")
    monkeypatch.setattr(visits_api.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(visit_ai, "chat_json", chat)


def test_language_catalogue(client, auth):
    langs = {l["code"]: l for l in client.get("/api/visits/languages", headers=auth).json()["languages"]}
    assert {"en", "ta", "hi", "te", "kn", "ml", "bn", "mr"} <= set(langs)
    assert langs["ta"]["voice_model"] == "eleven_multilingual_v2" and langs["te"]["voice_model"] == "eleven_v3"
    assert len(langs) >= 50


def test_unsupported_language_rejected(client, auth):
    assert client.post("/api/visits/ask", headers=auth, json={"question": "hello there", "lang": "xx"}).status_code == 422


def test_hindi_emergency_detected_through_english(client, auth, monkeypatch, no_llm):
    consent(client, auth)
    make_confirmed(client, auth)
    fake_llm(monkeypatch, english="I have severe chest pain")
    a = client.post("/api/visits/ask", headers=auth, json={"question": "मेरे सीने में तेज़ दर्द है", "lang": "hi"}).json()
    assert a["type"] == "emergency" and a["matches"] == []
    assert a["message_english"].startswith("This could be an emergency") and a["question_english"] == "I have severe chest pain"


def test_telugu_answer_translated_on_the_fly_and_unverified(client, auth, monkeypatch, no_llm):
    consent(client, auth)
    v = make_confirmed(client, auth)
    met = next(i["id"] for i in v["instructions"] if "Metformin" in i["simple_text"])
    fake_llm(monkeypatch, english="When should I take Metformin?", ids_for=[met])
    a = client.post("/api/visits/ask", headers=auth, json={"question": "మెట్ఫార్మిన్ ఎప్పుడు వేసుకోవాలి?", "lang": "te"}).json()
    assert a["type"] == "grounded" and a["matches"][0]["text_lang"] == "te"
    assert a["matches"][0]["translation_verified"] is False and a["matches"][0]["text"].startswith("అనువాదం")
    stored = client.get(f"/api/visits/{v['id']}", headers=auth).json()
    assert "te" in next(i for i in stored["instructions"] if i["id"] == met)["translations"]


def test_refusal_phrase_translated_and_cached(client, auth, monkeypatch, no_llm):
    consent(client, auth)
    make_confirmed(client, auth)
    fake_llm(monkeypatch, english="Can I double the dose?", translated="ಕನ್ನಡ")
    a1 = client.post("/api/visits/ask", headers=auth, json={"question": "Can I double the dose?", "lang": "kn"}).json()
    assert a1["type"] == "refusal" and a1["message_lang"] == "kn" and a1["message_verified"] is False
    monkeypatch.setattr(visit_ai, "chat_json", lambda *a, **k: (_ for _ in ()).throw(LLMUnavailable("down")))
    a2 = client.post("/api/visits/ask", headers=auth, json={"question": "Can I double the dose?", "lang": "kn"}).json()
    assert a2["message"] == a1["message"]  # served from cache


def test_phrase_falls_back_to_english_without_ai(client, auth, no_llm):
    make_confirmed(client, auth)
    a = client.post("/api/visits/ask", headers=auth, json={"question": "Can I double the dose?", "lang": "hi"}).json()
    assert a["type"] == "refusal" and a["message_lang"] == "en"


def test_voice_model_per_language(client, auth, no_llm, fake_tts, monkeypatch):
    consent(client, auth)
    v = make_confirmed(client, auth)
    iid = v["instructions"][0]["id"]
    models = []
    monkeypatch.setattr(visits_api.el, "synthesize", lambda t, vid=None, model_id=None: models.append(model_id) or b"ID3x")
    client.put(f"/api/visits/instructions/{iid}/translations/te", headers=auth, json={"text": "తెలుగు"})
    client.get(f"/api/visits/instructions/{iid}/audio?lang=te", headers=auth)
    client.get(f"/api/visits/instructions/{iid}/audio?lang=en", headers=auth)
    assert models == ["eleven_v3", "eleven_multilingual_v2"]

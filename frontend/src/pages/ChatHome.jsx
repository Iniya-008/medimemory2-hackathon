import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowUp, AudioLines, FileText, Loader2, Mic, Paperclip, Plus, ShieldCheck, Sparkles, Square, Stethoscope, Upload, X } from "lucide-react";
import LanguagePicker from "../components/LanguagePicker";
import VoiceMode from "../components/VoiceMode";
import { word } from "../hooks/useLanguages";
import {
  AnswerCard, Bubble, InstructionsCard, ReviewCard, Steps, UserBubble, audioPath, phrasePath,
} from "../components/VisitCards";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { useClips } from "../hooks/useClips";
import { mmss, useRecorder } from "../hooks/useRecorder";
import { api, errorMessage, todayISO } from "../services/api";

const VISIT_STEPS = ["Recording", "ElevenLabs speech-to-text", "AI finds the instructions", "Your check"];
const DOC_STEPS = ["Uploading", "Reading the document", "AI finds the instructions", "Your check"];
const SAMPLE_STEPS = ["Sample transcript (pre-written)", "No recording needed", "AI finds the instructions", "Your check"];
const ASK_STEPS_VOICE = ["Heard you · ElevenLabs", "Safety check", "Your confirmed instructions", "Voice · ElevenLabs"];
const SAMPLE_VISIT = (
  "[SAMPLE — pre-written for demonstration, not a real consultation]\n" +
  "Doctor: Lakshmi amma, your sugar and BP readings are a little high this time. " +
  "Take Metformin 500 mg, one tablet after breakfast and one after dinner. " +
  "Take Amlodipine 5 mg once in the morning. " +
  "Avoid sweets and reduce rice at night. " +
  "Walk for 30 minutes every evening. " +
  "Do an HbA1c blood test before the next visit. " +
  "Come back after one month."
);
const SUGGEST = {
  en: ["When should I take my sugar tablet?", "What did the doctor say about food?", "When is my next visit?"],
  ta: ["சர்க்கரை மாத்திரை எப்போது சாப்பிடணும்?", "சாப்பாடு பற்றி டாக்டர் என்ன சொன்னார்?", "அடுத்த முறை எப்போது வரணும்?"],
};

let seq = 0;
const nid = () => `${Date.now()}-${seq++}`;
const visitsChanged = () => window.dispatchEvent(new Event("mm:visits-changed"));

export default function ChatHome() {
  const { user, setUser } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const storeKey = `mm_thread_${user.id}`;
  const [lang, setLang] = useState(() => {
    try { return localStorage.getItem("mm_lang") || user.profile?.preferred_language || "en"; } catch { return "en"; }
  });
  const [thread, setThread] = useState(() => {
    try { return JSON.parse(sessionStorage.getItem(storeKey) || "[]").filter((m) => !["progress", "recordSetup"].includes(m.kind)); } catch { return []; }
  });
  const [visits, setVisits] = useState({});
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [menu, setMenu] = useState(false);
  const [drag, setDrag] = useState(false);
  const [voiceMode, setVoiceMode] = useState(false);
  const recMode = useRef(null); // "visit" | "question"
  const recSetupId = useRef(null);
  const fileRef = useRef(null);
  const endRef = useRef(null);
  const inputRef = useRef(null);
  const rec = useRecorder({ maxSeconds: 900 });
  const onClipError = useCallback((m) => toast.info(m), [toast]);
  const clips = useClips(onClipError);
  const consent = !!user.profile?.ai_data_consent;
  const firstName = (user.full_name || "").split(" ")[0];

  const menuRef = useRef(null);
  useEffect(() => {
    if (!menu) return undefined;
    const close = (e) => { if (menuRef.current && !menuRef.current.contains(e.target)) setMenu(false); };
    const esc = (e) => e.key === "Escape" && setMenu(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [menu]);
  useEffect(() => { try { localStorage.setItem("mm_lang", lang); } catch { /* ignore */ } }, [lang]);
  useEffect(() => { try { sessionStorage.setItem(storeKey, JSON.stringify(thread.slice(-60))); } catch { /* ignore */ } }, [thread, storeKey]);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [thread.length, rec.state]);
  useEffect(() => { if (rec.error) { toast.error(rec.error); rec.setError(""); } }, [rec.error]); // eslint-disable-line

  const loadVisits = useCallback(async () => {
    try {
      const list = (await api.get("/api/visits")).data;
      setVisits(Object.fromEntries(list.map((v) => [v.id, v])));
      return list;
    } catch { return []; }
  }, []);
  useEffect(() => { loadVisits(); }, [loadVisits]);

  // Opening a visit from the sidebar: /app?visit=12
  useEffect(() => {
    const id = Number(params.get("visit"));
    if (!id) return;
    setParams({}, { replace: true });
    api.get(`/api/visits/${id}`).then((r) => {
      putVisit(r.data);
      push({ role: "assistant", kind: r.data.status === "confirmed" ? "visit" : "review", visitId: id });
    }).catch((e) => toast.error(errorMessage(e)));
  }, [params]); // eslint-disable-line
  useEffect(() => {
    const clear = () => { setThread([]); clips.stop(); };
    window.addEventListener("mm:new-chat", clear);
    return () => window.removeEventListener("mm:new-chat", clear);
  }, [clips]);

  const push = (m) => { const msg = { id: nid(), ...m }; setThread((t) => [...t, msg]); return msg.id; };
  const update = (id, patch) => setThread((t) => t.map((m) => (m.id === id ? { ...m, ...patch } : m)));
  const remove = (id) => setThread((t) => t.filter((m) => m.id !== id));
  const putVisit = (v) => setVisits((vs) => ({ ...vs, [v.id]: v }));

  const enableConsent = async () => {
    try {
      const r = await api.patch("/api/auth/me", { ai_data_consent: true });
      setUser(r.data);
      toast.success("AI and voice features are on. You can turn this off any time in Settings.");
    } catch (e) { toast.error(errorMessage(e)); }
  };
  const needConsent = () => {
    if (consent) return false;
    push({ role: "assistant", kind: "consent" });
    return true;
  };

  /* -------------------------------------------------------------- shared: draft -> extract -> review */
  const extractAndReview = async (visit, progressId, steps) => {
    update(progressId, { active: 2 });
    const v = (await api.post(`/api/visits/${visit.id}/extract`)).data;
    putVisit(v);
    update(progressId, { active: steps.length, note: v.extraction_method === "rules" ? "AI is not configured, so simple rules were used. Check carefully." : null });
    push({ role: "assistant", kind: "review", visitId: v.id });
    visitsChanged();
  };

  /* -------------------------------------------------------------- record a doctor visit */
  const openRecordSetup = () => {
    setMenu(false);
    if (needConsent()) return;
    recSetupId.current = push({ role: "assistant", kind: "recordSetup", doctor: "", agreed: false });
  };
  const startVisitRecording = async (setupId) => {
    recMode.current = "visit";
    recSetupId.current = setupId;
    const ok = await rec.start();
    if (!ok) recMode.current = null;
  };
  const finishVisitRecording = async () => {
    const setup = thread.find((m) => m.id === recSetupId.current);
    const secs = rec.seconds;
    const blob = await rec.stop();
    recMode.current = null;
    if (!blob) return;
    remove(recSetupId.current);
    push({ role: "user", kind: "record", text: `Recorded ${mmss(secs)}${setup?.doctor ? ` with ${setup.doctor}` : ""}` });
    const pid = push({ role: "assistant", kind: "progress", steps: VISIT_STEPS, active: 1 });
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", blob, `visit.${blob.type.includes("mp4") ? "m4a" : "webm"}`);
      fd.append("consent", "true");
      fd.append("consent_note", "Everyone in the room agreed to the recording");
      fd.append("doctor_name", setup?.doctor || "");
      fd.append("visit_date", todayISO());
      const v = (await api.post("/api/visits/record", fd)).data;
      putVisit(v);
      await extractAndReview(v, pid, VISIT_STEPS);
    } catch (e) {
      update(pid, { failed: true, note: errorMessage(e) });
    } finally { setBusy(false); }
  };

  /* -------------------------------------------------------------- upload a document */
  const uploadFile = async (file) => {
    setMenu(false);
    if (!file) return;
    if (needConsent()) return;
    push({ role: "user", kind: "file", text: file.name });
    const pid = push({ role: "assistant", kind: "progress", steps: DOC_STEPS, active: 0 });
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("visit_date", todayISO());
      update(pid, { active: 1 });
      const v = (await api.post("/api/visits/document", fd)).data;
      putVisit(v);
      await extractAndReview(v, pid, DOC_STEPS);
    } catch (e) {
      update(pid, { failed: true, note: errorMessage(e) });
    } finally { setBusy(false); if (fileRef.current) fileRef.current.value = ""; }
  };

  const runSample = async () => {
    setMenu(false);
    push({ role: "user", kind: "text", text: "Show me with a sample visit" });
    const pid = push({ role: "assistant", kind: "progress", steps: SAMPLE_STEPS, active: 1 });
    setBusy(true);
    try {
      const v = (await api.post("/api/visits/typed", { transcript: SAMPLE_VISIT, doctor_name: "Dr. Kavitha Rao", source: "sample" })).data;
      putVisit(v);
      await extractAndReview(v, pid, SAMPLE_STEPS);
    } catch (e) { update(pid, { failed: true, note: errorMessage(e) }); }
    finally { setBusy(false); }
  };

  /* -------------------------------------------------------------- ask */
  const ask = async (text, kind = "text") => {
    const q = text.trim();
    if (!q || busy) return;
    setInput("");
    push({ role: "user", kind, text: q });
    const pid = push({ role: "assistant", kind: "progress", steps: kind === "voice" ? ASK_STEPS_VOICE : ASK_STEPS_VOICE.slice(1, 3), active: kind === "voice" ? 1 : 0 });
    setBusy(true);
    try {
      const a = (await api.post("/api/visits/ask", { question: q, lang })).data;
      remove(pid);
      push({ role: "assistant", kind: "answer", a });
      if (consent) {
        const path = a.matches?.length ? audioPath(a.matches[0].instruction_id, a.matches[0].text_lang) : phrasePath(a.phrase, lang);
        clips.play(path);
      }
    } catch (e) {
      update(pid, { failed: true, note: errorMessage(e) });
    } finally { setBusy(false); }
  };

  const startQuestion = async () => {
    if (needConsent()) return;
    clips.stop();
    recMode.current = "question";
    const ok = await rec.start();
    if (!ok) recMode.current = null;
  };
  const finishQuestion = async () => {
    const blob = await rec.stop();
    recMode.current = null;
    if (!blob) return;
    setBusy(true);
    const pid = push({ role: "assistant", kind: "progress", steps: ASK_STEPS_VOICE, active: 0 });
    try {
      const fd = new FormData();
      fd.append("file", blob, `question.${blob.type.includes("mp4") ? "m4a" : "webm"}`);
      const heard = (await api.post("/api/voice/transcribe", fd)).data.text;
      remove(pid);
      setBusy(false);
      await ask(heard, "voice");
    } catch (e) {
      update(pid, { failed: true, note: errorMessage(e) });
      setBusy(false);
    }
  };

  const discard = async (visitId, msgId) => {
    try { await api.delete(`/api/visits/${visitId}`); } catch { /* already gone */ }
    remove(msgId);
    push({ role: "assistant", kind: "note", text: "Discarded. Nothing was saved." });
    visitsChanged();
  };

  /* -------------------------------------------------------------- render */
  const recordingQuestion = rec.state !== "idle" && recMode.current === "question";
  const lastConfirmed = Object.values(visits).filter((v) => v.status === "confirmed").sort((a, b) => (a.visit_date < b.visit_date ? 1 : -1))[0];

  const renderMsg = (m) => {
    if (m.role === "user") return <UserBubble m={m} onEdit={(t) => { setInput(t); inputRef.current?.focus(); }} />;
    switch (m.kind) {
      case "progress":
        return (
          <Bubble tone={m.failed ? "red" : "white"}>
            <Steps steps={m.steps} active={m.active} failed={m.failed} />
            {m.note && <p className={`mt-2 text-sm ${m.failed ? "text-red-700" : "text-muted"}`}>{m.note}</p>}
          </Bubble>
        );
      case "consent":
        return (
          <Bubble tone="amber">
            <p className="font-semibold text-ink">One permission first</p>
            <p className="mt-1 text-sm text-ink/80">To record, read documents and speak answers, MediMemory sends audio and text to ElevenLabs (voice) and an AI service (understanding and translation). Only synthetic demo data should be used.</p>
            {consent ? <p className="mt-2 text-sm font-semibold text-emerald-700">Allowed ✓</p>
              : <button className="btn-primary mt-3" onClick={enableConsent}><ShieldCheck className="h-4 w-4" /> Allow and continue</button>}
          </Bubble>
        );
      case "recordSetup": {
        const live = rec.state !== "idle" && recMode.current === "visit" && recSetupId.current === m.id;
        return (
          <Bubble>
            <p className="flex items-center gap-2 font-semibold text-ink"><Stethoscope className="h-5 w-5 text-teal" /> Record your doctor visit</p>
            {!live ? (
              <>
                <input className="input mt-3" placeholder="Doctor's name (optional)" value={m.doctor} onChange={(e) => update(m.id, { doctor: e.target.value })} />
                <label className="mt-3 flex items-start gap-2 rounded-xl bg-canvas p-3 text-sm text-ink">
                  <input type="checkbox" className="mt-1 h-5 w-5" checked={m.agreed} onChange={(e) => update(m.id, { agreed: e.target.checked })} />
                  <span><b>The doctor and everyone in the room agreed to this recording.</b> The audio is turned into text and is not stored. Nothing is saved until you check and confirm it.</span>
                </label>
                <div className="mt-3 flex gap-2">
                  <button className="btn-danger rounded-full px-5" disabled={!m.agreed || rec.state !== "idle"} onClick={() => startVisitRecording(m.id)}>
                    {rec.state === "starting" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Mic className="h-4 w-4" />} Start recording
                  </button>
                  <button className="btn-ghost" onClick={() => remove(m.id)}>Cancel</button>
                </div>
              </>
            ) : (
              <div className="mt-3">
                <div className="flex items-center gap-3">
                  <span className="relative flex h-3 w-3"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-400 opacity-75" /><span className="relative inline-flex h-3 w-3 rounded-full bg-red-600" /></span>
                  <span className="font-mono text-lg font-semibold text-ink">{mmss(rec.seconds)}</span>
                  <div className="flex h-10 flex-1 items-center gap-[3px]" aria-hidden="true">
                    {rec.levels.map((l, i) => <span key={i} className="w-[3px] rounded-full bg-teal" style={{ height: `${Math.max(3, l * 40)}px` }} />)}
                  </div>
                </div>
                <div className="mt-3 flex gap-2">
                  <button className="btn-primary rounded-full px-5" onClick={finishVisitRecording}><Square className="h-4 w-4" /> Stop and continue</button>
                  <button className="btn-ghost" onClick={() => { rec.cancel(); recMode.current = null; }}>Cancel</button>
                </div>
              </div>
            )}
          </Bubble>
        );
      }
      case "review": {
        const v = visits[m.visitId];
        if (!v) return null;
        if (v.status === "confirmed") return <InstructionsCard visit={v} lang={lang} clips={clips} onChange={putVisit} toast={toast} />;
        return <ReviewCard visit={v} toast={toast} onChange={putVisit} onDiscard={() => discard(v.id, m.id)}
          onConfirmed={(cv) => {
            visitsChanged();
            push({ role: "assistant", kind: "note", text: "Saved. You can now hear it in your language and ask questions about it.", tone: "ok" });
            if (consent) api.post(`/api/visits/${cv.id}/prewarm`, { langs: ["en"] }).catch(() => {});
          }} />;
      }
      case "visit": {
        const v = visits[m.visitId];
        return v ? <InstructionsCard visit={v} lang={lang} clips={clips} onChange={putVisit} toast={toast} /> : null;
      }
      case "answer":
        return <AnswerCard a={m.a} clips={clips} />;
      case "note":
        return <p className={`px-1 text-sm ${m.tone === "ok" ? "font-medium text-emerald-700" : "text-muted"}`}>{m.text}</p>;
      default:
        return null;
    }
  };

  return (
    <div className="relative flex h-[calc(100dvh-65px)] flex-col"
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); uploadFile(e.dataTransfer.files?.[0]); }}>
      {voiceMode && (
        <VoiceMode lang={lang} onClose={() => setVoiceMode(false)}
          onExchange={(q, a) => { push({ role: "user", kind: "voice", text: q }); push({ role: "assistant", kind: "answer", a }); }} />
      )}
      {drag && (
        <div className="pointer-events-none absolute inset-3 z-20 flex items-center justify-center rounded-3xl border-2 border-dashed border-teal bg-teal-50/90 text-lg font-semibold text-teal-700">
          Drop your prescription or report here
        </div>
      )}

      {/* top bar: language */}
      <div className="flex items-center justify-between gap-3 border-b border-line/70 bg-white px-4 py-2.5 sm:px-6">
        <p className="text-sm font-semibold text-ink">Ask MediMemory</p>
        <LanguagePicker value={lang} onChange={(v) => { setLang(v); clips.stop(); }} />
      </div>

      {/* thread */}
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl space-y-4 px-4 py-6 sm:px-6">
          {thread.length === 0 && (
            <div className="pt-1 text-center sm:pt-4">
              <span className="mx-auto hidden h-14 w-14 items-center justify-center rounded-full bg-orb text-white shadow-glow sm:flex"><Sparkles className="h-6 w-6" /></span>
              <h1 className="mt-2 text-2xl sm:mt-5 font-semibold text-ink sm:text-3xl">{word("hello", lang)}, {firstName}</h1>
              <p className="mx-auto mt-2 max-w-md text-sm text-muted sm:text-base">Never miss what your doctor told you. Record the visit or upload the prescription, check it once, then hear it in your language any time.</p>
              <div className="mt-5 grid gap-2 text-left sm:mt-6 sm:grid-cols-3 sm:gap-3">
                <button onClick={openRecordSetup} className="card grid grid-cols-[auto_1fr] items-center gap-x-3 p-3 text-left transition hover:border-teal hover:shadow-lg sm:flex sm:flex-col sm:items-start sm:gap-2 sm:p-4">
                  <Mic className="row-span-2 h-6 w-6 text-red-500" /><span className="font-semibold text-ink">Record my doctor visit</span><span className="col-start-2 text-xs text-muted">With everyone's consent</span>
                </button>
                <button onClick={() => fileRef.current?.click()} className="card grid grid-cols-[auto_1fr] items-center gap-x-3 p-3 text-left transition hover:border-teal hover:shadow-lg sm:flex sm:flex-col sm:items-start sm:gap-2 sm:p-4">
                  <Upload className="row-span-2 h-6 w-6 text-brand" /><span className="font-semibold text-ink">Upload a prescription</span><span className="col-start-2 text-xs text-muted">Photo or PDF</span>
                </button>
                <button onClick={() => (lastConfirmed ? inputRef.current?.focus() : runSample())} className="card grid grid-cols-[auto_1fr] items-center gap-x-3 p-3 text-left transition hover:border-teal hover:shadow-lg sm:flex sm:flex-col sm:items-start sm:gap-2 sm:p-4">
                  <Sparkles className="row-span-2 h-6 w-6 text-teal" /><span className="font-semibold text-ink">{lastConfirmed ? "Ask a question" : "Try a sample visit"}</span>
                  <span className="col-start-2 text-xs text-muted">{lastConfirmed ? "Type or tap the mic" : "Pre-written, for a quick look"}</span>
                </button>
              </div>
              {!consent && (
                <p className="mx-auto mt-5 max-w-lg rounded-xl bg-amber-50 px-4 py-3 text-sm text-amber-800">
                  Voice and AI features are off. <button className="font-semibold underline" onClick={enableConsent}>Allow them</button> to record, read documents and hear answers.
                </p>
              )}
              {lastConfirmed && (
                <div className="mt-6 text-left">
                  <p className="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-muted">Your last visit</p>
                  <InstructionsCard visit={lastConfirmed} lang={lang} clips={clips} onChange={putVisit} toast={toast} compact />
                </div>
              )}
            </div>
          )}
          {thread.map((m) => <div key={m.id} className={m.role === "user" ? "flex" : ""}>{renderMsg(m)}</div>)}
          <div ref={endRef} />
        </div>
      </div>

      {/* composer */}
      <div className="border-t border-line/70 bg-white/90 px-3 pb-3 pt-2 backdrop-blur sm:px-6">
        <div className="mx-auto max-w-3xl">
          {thread.length === 0 && lastConfirmed && (
            <div className="-mx-1 mb-2 flex gap-2 overflow-x-auto px-1 pb-1">
              {(SUGGEST[lang] || SUGGEST.en).map((s) => <button key={s} className="shrink-0 whitespace-nowrap rounded-full border border-line bg-white px-3 py-1.5 text-xs font-medium text-navy hover:border-teal" onClick={() => ask(s)}>{s}</button>)}
            </div>
          )}
          {recordingQuestion ? (
            <div className="flex items-center gap-3 rounded-3xl border-2 border-teal bg-teal-50 px-4 py-3">
              <span className="relative flex h-3 w-3"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-400 opacity-75" /><span className="relative inline-flex h-3 w-3 rounded-full bg-red-600" /></span>
              <span className="text-sm font-semibold text-teal-700">{word("listening", lang)} {mmss(rec.seconds)}</span>
              <div className="flex h-8 flex-1 items-center gap-[3px]" aria-hidden="true">
                {rec.levels.map((l, i) => <span key={i} className="w-[3px] rounded-full bg-teal" style={{ height: `${Math.max(3, l * 30)}px` }} />)}
              </div>
              <button className="rounded-full p-2 text-muted hover:bg-white" aria-label="Cancel" onClick={() => { rec.cancel(); recMode.current = null; }}><X className="h-5 w-5" /></button>
              <button className="flex h-12 w-12 items-center justify-center rounded-full bg-teal text-white shadow-lg" aria-label="Stop and ask" onClick={finishQuestion}><Square className="h-5 w-5" /></button>
            </div>
          ) : (
            <div className="relative flex items-end gap-2 rounded-3xl border border-line bg-white p-2 shadow-card focus-within:border-teal">
              <div className="relative" ref={menuRef}>
                <button className="flex h-11 w-11 items-center justify-center rounded-full text-navy hover:bg-canvas" aria-label="Add: record a visit or upload a document" aria-expanded={menu} onClick={() => setMenu(!menu)}>
                  <Plus className={`h-6 w-6 transition ${menu ? "rotate-45" : ""}`} />
                </button>
                {menu && (
                  <div className="absolute bottom-14 left-0 z-30 w-72 overflow-hidden rounded-2xl border border-line bg-white py-1 shadow-card">
                    <button className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm hover:bg-canvas" onClick={openRecordSetup}><Mic className="h-5 w-5 text-red-500" /><span><b>Record doctor visit</b><br /><span className="text-xs text-muted">With consent; turned into text</span></span></button>
                    <button className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm hover:bg-canvas" onClick={() => fileRef.current?.click()}><Paperclip className="h-5 w-5 text-brand" /><span><b>Upload prescription or report</b><br /><span className="text-xs text-muted">Photo, PDF or text file</span></span></button>
                    <button className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm hover:bg-canvas" onClick={runSample}><FileText className="h-5 w-5 text-muted" /><span><b>Use a sample visit</b><br /><span className="text-xs text-muted">Pre-written, clearly labelled</span></span></button>
                  </div>
                )}
              </div>
              <textarea ref={inputRef} rows={1} value={input} disabled={busy}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(input); } }}
                placeholder={word("ask", lang)}
                className="max-h-40 min-h-[44px] flex-1 resize-none bg-transparent px-1 py-2.5 text-[16px] text-ink placeholder:text-muted/70 focus:outline-none" aria-label="Your question" />
              {input.trim() ? (
                <button className="flex h-11 w-11 items-center justify-center rounded-full bg-navy text-white disabled:opacity-50" disabled={busy} aria-label="Send" onClick={() => ask(input)}>
                  {busy ? <Loader2 className="h-5 w-5 animate-spin" /> : <ArrowUp className="h-5 w-5" />}
                </button>
              ) : (
                <>
                  <button className="flex h-11 w-11 items-center justify-center rounded-full text-navy hover:bg-canvas disabled:opacity-50" disabled={busy || rec.state !== "idle"}
                    aria-label="Dictate a question" title="Dictate a question" onClick={startQuestion}>
                    <Mic className="h-6 w-6" />
                  </button>
                  <button className="flex h-12 w-12 items-center justify-center rounded-full bg-teal text-white shadow-lg shadow-teal/30 disabled:opacity-50" disabled={busy || rec.state !== "idle"}
                    aria-label="Talk with MediMemory (voice conversation)" title="Voice conversation"
                    onClick={() => { if (!needConsent()) { clips.stop(); setVoiceMode(true); } }}>
                    {busy ? <Loader2 className="h-5 w-5 animate-spin" /> : <AudioLines className="h-6 w-6" />}
                  </button>
                </>
              )}
            </div>
          )}
          <input ref={fileRef} type="file" className="hidden" accept=".pdf,.png,.jpg,.jpeg,.webp,.txt" onChange={(e) => uploadFile(e.target.files?.[0])} />
          <p className="mt-2 text-center text-[11px] text-muted">
            MediMemory repeats what your doctor told you. It does not diagnose or change medicines. In an emergency call <a href="tel:108" className="font-semibold text-red-600">108</a>.
          </p>
        </div>
      </div>
    </div>
  );
}

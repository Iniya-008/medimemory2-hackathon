import { useCallback, useEffect, useRef, useState } from "react";
import { Mic, MicOff, Phone, X } from "lucide-react";
import { api, blobErrorMessage, errorMessage } from "../services/api";
import { audioPath, phrasePath } from "./VisitCards";
import { useLanguages, word } from "../hooks/useLanguages";

/**
 * Hands-free voice conversation (like ChatGPT voice mode):
 * listen -> detect end of speech -> ElevenLabs speech-to-text -> safety rules + confirmed instructions
 * -> ElevenLabs voice reply -> listen again. Emergencies stop the loop and show Call 108.
 */
const SILENCE_MS = 1300;
const MAX_UTTERANCE_MS = 30000;
const IDLE_RESTART_MS = 20000;

function pickMime() {
  if (typeof MediaRecorder === "undefined") return "";
  return ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((t) => MediaRecorder.isTypeSupported?.(t)) || "";
}

export default function VoiceMode({ lang, onClose, onExchange }) {
  const { byCode } = useLanguages();
  const [state, setState] = useState("starting"); // starting|listening|hearing|thinking|speaking|paused|emergency|error
  const [level, setLevel] = useState(0);
  const [heard, setHeard] = useState("");
  const [reply, setReply] = useState("");
  const [replyNote, setReplyNote] = useState("");
  const [error, setError] = useState("");
  const [matchLang, setMatchLang] = useState(true); // reply in the language I speak
  const [spokenLang, setSpokenLang] = useState(null);

  const st = useRef("starting");
  const stream = useRef(null);
  const ctx = useRef(null);
  const analyser = useRef(null);
  const rec = useRef(null);
  const chunks = useRef([]);
  const raf = useRef(null);
  const timing = useRef({});
  const audio = useRef(null);
  const alive = useRef(true);
  const matchLangRef = useRef(true);
  matchLangRef.current = matchLang;
  const ctxRef = useRef({});
  ctxRef.current = { lang, byCode, onExchange };

  const set = (s) => { st.current = s; setState(s); };

  const stopRecorder = (discard) => new Promise((resolve) => {
    const r = rec.current;
    if (!r || r.state === "inactive") { resolve(null); return; }
    r.onstop = () => resolve(discard ? null : new Blob(chunks.current, { type: r.mimeType || "audio/webm" }));
    r.stop();
  });

  const listen = useCallback(() => {
    if (!alive.current || !stream.current) return;
    const mime = pickMime();
    const r = new MediaRecorder(stream.current, mime ? { mimeType: mime } : undefined);
    chunks.current = [];
    r.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
    r.start(200);
    rec.current = r;
    timing.current = { start: performance.now(), floor: 0.008, speech: 0, last: 0 };
    set("listening");
  }, []);

  const speakPaths = async (paths) => {
    for (const p of paths) {
      if (!alive.current || st.current !== "speaking") return;
      try {
        const blob = (await api.get(p, { responseType: "blob" })).data;
        const url = URL.createObjectURL(blob);
        await new Promise((resolve) => {
          const a = new Audio(url);
          audio.current = a;
          a.onended = resolve; a.onerror = resolve; a.onpause = resolve;
          a.play().catch(resolve);
        });
        URL.revokeObjectURL(url);
      } catch (e) {
        setReplyNote(await blobErrorMessage(e, "Couldn't play the voice reply."));
        return;
      }
    }
  };

  const handleUtterance = useCallback(async () => {
    set("thinking");
    const blob = await stopRecorder(false);
    if (!blob || blob.size < 2000) { listen(); return; }
    try {
      const fd = new FormData();
      fd.append("file", blob, `voice.${blob.type.includes("mp4") ? "m4a" : "webm"}`);
      const t = (await api.post("/api/voice/transcribe", fd)).data;
      if (!alive.current) return;
      const text = (t.text || "").trim();
      if (!text) { listen(); return; }
      setHeard(text);
      setSpokenLang(t.lang || null);
      const { lang: chosen, byCode: known, onExchange: report } = ctxRef.current;
      const answerLang = matchLangRef.current && t.lang && known[t.lang] ? t.lang : chosen;
      const a = (await api.post("/api/visits/ask", { question: text, lang: answerLang })).data;
      if (!alive.current) return;
      report?.(text, a);
      const shown = a.matches?.length ? a.matches.map((m) => m.text).join(" ") : a.message;
      setReply(shown);
      setReplyNote(a.type === "grounded" ? `From ${a.matches[0].doctor_name || "your doctor"}'s instructions${a.matches.some((m) => m.text_lang !== "en" && !m.translation_verified) ? " · machine translation, not yet checked" : ""}`
        : a.type === "emergency" ? (a.message_english || "") : "");
      const paths = a.matches?.length ? a.matches.map((m) => audioPath(m.instruction_id, m.text_lang)) : [phrasePath(a.phrase, answerLang)];
      set("speaking");
      await speakPaths(paths);
      if (!alive.current) return;
      if (a.type === "emergency") { set("emergency"); return; }
      if (st.current === "speaking") listen();
    } catch (e) {
      setError(errorMessage(e));
      set("paused");
    }
  }, [listen]); // eslint-disable-line

  // voice-activity detection loop
  const tick = useCallback(() => {
    raf.current = requestAnimationFrame(tick);
    const an = analyser.current;
    if (!an) return;
    const buf = new Float32Array(an.fftSize);
    an.getFloatTimeDomainData(buf);
    let sum = 0;
    for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
    const rms = Math.sqrt(sum / buf.length);
    setLevel(rms);
    const s = st.current;
    if (s !== "listening" && s !== "hearing") return;
    const now = performance.now(), tm = timing.current;
    if (now - tm.start < 400) { tm.floor = Math.max(tm.floor, rms); return; } // calibrate room noise
    const threshold = Math.max(0.02, tm.floor * 2.2);
    if (rms > threshold) {
      if (!tm.speech) { tm.speech = now; set("hearing"); }
      tm.last = now;
    }
    if (tm.speech && (now - tm.last > SILENCE_MS || now - tm.speech > MAX_UTTERANCE_MS)) {
      handleUtterance();
    } else if (!tm.speech && now - tm.start > IDLE_RESTART_MS) {
      tm.start = Infinity; // run once
      stopRecorder(true).then(listen); // keep recordings short while nobody is talking
    }
  }, [handleUtterance, listen]);

  useEffect(() => {
    alive.current = true;
    (async () => {
      try {
        stream.current = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      } catch (e) {
        setError(e?.name === "NotAllowedError" ? "Microphone permission was blocked. Allow it in the browser's address bar." : "No microphone found.");
        set("error");
        return;
      }
      const AC = window.AudioContext || window.webkitAudioContext;
      ctx.current = new AC();
      analyser.current = ctx.current.createAnalyser();
      analyser.current.fftSize = 1024;
      ctx.current.createMediaStreamSource(stream.current).connect(analyser.current);
      listen();
      tick();
    })();
    return () => {
      alive.current = false;
      cancelAnimationFrame(raf.current);
      try { rec.current?.state !== "inactive" && rec.current?.stop(); } catch { /* ignore */ }
      audio.current?.pause();
      stream.current?.getTracks().forEach((t) => t.stop());
      ctx.current?.close().catch(() => {});
    };
  }, []); // eslint-disable-line

  const pause = async () => { audio.current?.pause(); await stopRecorder(true); set("paused"); };
  const resume = () => { setError(""); listen(); };
  const interrupt = async () => { if (st.current === "speaking") { set("listening"); audio.current?.pause(); listen(); } };

  const label = {
    starting: "Starting the microphone…", listening: word("listening", lang), hearing: word("listening", lang),
    thinking: "Finding it in your doctor's instructions…", speaking: "Speaking · tap the circle to interrupt",
    paused: "Paused", emergency: "Emergency", error: "Microphone unavailable",
  }[state];
  const scale = state === "hearing" || state === "listening" ? 1 + Math.min(0.45, level * 6) : 1;
  const orb = { speaking: "animate-pulse", thinking: "animate-spin [animation-duration:2.5s]" }[state] || "";
  const langName = spokenLang && byCode[spokenLang] ? byCode[spokenLang].native : null;

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-navy text-white" role="dialog" aria-label="Voice conversation">
      <div className="flex items-center justify-between px-5 py-4">
        <p className="text-sm font-semibold text-navy-100">Voice conversation · ElevenLabs</p>
        <label className="flex items-center gap-2 text-xs text-navy-100">
          <input type="checkbox" checked={matchLang} onChange={(e) => setMatchLang(e.target.checked)} className="h-4 w-4" />
          Reply in the language I speak
        </label>
      </div>

      <div className="flex flex-1 flex-col items-center justify-center px-6 text-center">
        {state === "emergency" ? (
          <div className="max-w-md">
            <p className="text-2xl font-semibold leading-snug">{reply}</p>
            {replyNote && <p className="mt-2 text-sm text-red-200">{replyNote}</p>}
            <a href="tel:108" className="mt-6 inline-flex items-center gap-3 rounded-full bg-red-600 px-8 py-4 text-xl font-bold shadow-xl"><Phone className="h-6 w-6" /> Call 108</a>
            <p className="mt-4 text-xs text-navy-100">MediMemory does not look at your records in an emergency.</p>
          </div>
        ) : (
          <>
            <button onClick={interrupt} aria-label="Voice orb" className="relative flex h-48 w-48 items-center justify-center sm:h-56 sm:w-56">
              {(state === "listening" || state === "hearing") && <span className="absolute inset-0 animate-pulseRing rounded-full bg-teal/40" />}
              <span className={`absolute inset-0 rounded-full bg-orb shadow-glow transition-transform duration-100 ${orb}`} style={{ transform: `scale(${scale})` }} />
              {state === "paused" && <MicOff className="relative h-12 w-12" />}
            </button>
            <p className="mt-10 text-lg font-semibold">{label}</p>
            {langName && <p className="mt-1 text-xs text-navy-100">Heard in {langName}</p>}
            {heard && <p className="mt-6 max-w-xl text-base text-navy-100">“{heard}”</p>}
            {reply && <p className="mt-4 max-w-xl text-xl leading-relaxed">{reply}</p>}
            {replyNote && <p className="mt-2 max-w-xl text-xs text-amber-200">{replyNote}</p>}
            {error && <p className="mt-4 max-w-md rounded-xl bg-red-500/20 px-4 py-2 text-sm text-red-100">{error}</p>}
          </>
        )}
      </div>

      <div className="flex items-center justify-center gap-6 pb-10 pt-4">
        {state === "paused" || state === "emergency" || state === "error"
          ? <button onClick={resume} disabled={state === "error"} className="flex h-16 w-16 items-center justify-center rounded-full bg-white/10 disabled:opacity-40" aria-label="Resume listening"><Mic className="h-7 w-7" /></button>
          : <button onClick={pause} className="flex h-16 w-16 items-center justify-center rounded-full bg-white/10" aria-label="Pause"><MicOff className="h-7 w-7" /></button>}
        <button onClick={onClose} className="flex h-16 w-16 items-center justify-center rounded-full bg-red-600" aria-label="End voice conversation"><X className="h-8 w-8" /></button>
      </div>
      <p className="pb-4 text-center text-[11px] text-navy-100/80">Repeats only what your doctor told you. Not for emergencies: call 108.</p>
    </div>
  );
}

import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle, Check, CheckCircle2, ChevronDown, Circle, FileText, Loader2, Mic, Pause, Pencil, Phone, Play, Plus,
  ShieldAlert, Stethoscope, Trash2, Volume2, X,
} from "lucide-react";
import { api, errorMessage, fmtDate } from "../services/api";
import { useLanguages, word } from "../hooks/useLanguages";

export const CATEGORY = {
  medicine: { label: "Medicine", ta: "மருந்து", tone: "bg-brand-50 text-brand-700" },
  timing: { label: "Timing", ta: "நேரம்", tone: "bg-brand-50 text-brand-700" },
  diet: { label: "Food", ta: "உணவு", tone: "bg-mint text-teal-700" },
  test: { label: "Test", ta: "பரிசோதனை", tone: "bg-amber-50 text-amber-700" },
  follow_up: { label: "Next visit", ta: "அடுத்த வருகை", tone: "bg-violet-50 text-violet-700" },
  lifestyle: { label: "Daily habit", ta: "பழக்கம்", tone: "bg-mint text-teal-700" },
  other: { label: "Other", ta: "மற்றவை", tone: "bg-canvas text-muted" },
};
const SOURCE = { recording: "Recorded visit", document: "Uploaded document", typed: "Typed notes", sample: "Sample visit (pre-written, not a real recording)" };
const METHOD = { speech_to_text: "ElevenLabs speech-to-text", pdf_text: "PDF text", ocr: "OCR", ai_vision: "AI read the photo", text: "Text file", typed: "Typed" };

export const audioPath = (iid, lang) => `/api/visits/instructions/${iid}/audio?lang=${lang}`;
export const phrasePath = (kind, lang) => `/api/visits/phrases/${kind}/audio?lang=${lang}`;

/* ------------------------------------------------------------------ small pieces */
function PlayBtn({ path, clips, label = "Hear it", big }) {
  const on = clips.playing === path, busy = clips.loading === path;
  return (
    <button onClick={() => clips.play(path)} aria-label={on ? "Stop" : label}
      className={`inline-flex shrink-0 items-center justify-center gap-1.5 rounded-full font-semibold transition ${big ? "px-4 py-2 text-sm" : "px-3 py-1.5 text-xs"} ${on ? "bg-teal text-white" : "bg-teal-50 text-teal-700 hover:bg-teal-100"}`}>
      {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : on ? <Pause className="h-4 w-4" /> : <Volume2 className="h-4 w-4" />}
      {on ? "Stop" : label}
    </button>
  );
}

function TranslationBadge({ t }) {
  if (!t) return null;
  return t.verified
    ? <span className="chip bg-emerald-50 text-emerald-700"><CheckCircle2 className="h-3 w-3" /> Checked by {t.verified_by}</span>
    : <span className="chip bg-amber-50 text-amber-700"><AlertTriangle className="h-3 w-3" /> Machine translation · not yet checked by a native speaker</span>;
}

export function Steps({ steps, active, failed }) {
  return (
    <ol className="flex flex-wrap items-center gap-x-2 gap-y-1.5 text-xs" aria-label="Progress">
      {steps.map((s, i) => {
        const done = i < active, cur = i === active;
        return (
          <li key={s} className="flex items-center gap-2">
            <span className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 font-semibold ${done ? "bg-teal-50 text-teal-700" : cur ? (failed ? "bg-red-50 text-red-700" : "bg-brand-50 text-brand-700") : "bg-canvas text-muted"}`}>
              {done ? <Check className="h-3.5 w-3.5" /> : cur && !failed ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : cur ? <X className="h-3.5 w-3.5" /> : <Circle className="h-3 w-3" />}
              {s}
            </span>
            {i < steps.length - 1 && <span className="h-px w-3 bg-line" />}
          </li>
        );
      })}
    </ol>
  );
}

export function Bubble({ children, tone = "white" }) {
  const t = { white: "bg-white border-line/80", red: "bg-red-50 border-red-200", amber: "bg-amber-50/70 border-amber-200", grey: "bg-canvas border-line" }[tone];
  return <div className={`w-full rounded-2xl border p-4 shadow-sm sm:p-5 ${t}`}>{children}</div>;
}

/* ------------------------------------------------------------------ review (draft) */
export function ReviewCard({ visit, onChange, onConfirmed, onDiscard, toast }) {
  const [items, setItems] = useState(() => visit.instructions.map((i) => ({ ...i })));
  const [doctor, setDoctor] = useState(visit.doctor_name || "");
  const [date, setDate] = useState(visit.visit_date);
  const [showText, setShowText] = useState(false);
  const [busy, setBusy] = useState("");
  useEffect(() => { setItems(visit.instructions.map((i) => ({ ...i }))); setDoctor(visit.doctor_name || ""); setDate(visit.visit_date); }, [visit]);

  const set = (idx, patch) => setItems((xs) => xs.map((x, i) => (i === idx ? { ...x, ...patch } : x)));
  const flagged = items.filter((i) => i.needs_check).length;

  const openOriginal = async () => {
    try {
      const r = await api.get(`/api/documents/${visit.document_id}/file`, { responseType: "blob" });
      window.open(URL.createObjectURL(r.data), "_blank", "noopener");
    } catch (e) { toast.error(errorMessage(e)); }
  };

  const confirm = async () => {
    setBusy("confirm");
    try {
      const body = { doctor_name: doctor, visit_date: date, instructions: items.filter((i) => i.simple_text.trim()).map((i) => ({
        id: i.id || null, category: i.category, source_sentence: i.source_sentence || "", simple_text: i.simple_text.trim() })) };
      await api.put(`/api/visits/${visit.id}/instructions`, body);
      const r = await api.post(`/api/visits/${visit.id}/confirm`);
      onChange(r.data);
      onConfirmed(r.data);
    } catch (e) { toast.error(errorMessage(e)); }
    finally { setBusy(""); }
  };

  return (
    <Bubble>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-base font-semibold text-ink">Please check what I understood</p>
          <p className="text-xs text-muted">{SOURCE[visit.source]} · read with {METHOD[visit.text_method] || "—"} · nothing is saved until you confirm</p>
        </div>
        <span className="chip bg-amber-50 text-amber-700">Draft</span>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <label className="text-xs font-semibold text-muted">Doctor
          <input className="input mt-1" value={doctor} onChange={(e) => setDoctor(e.target.value)} placeholder="e.g. Dr. Kavitha Rao" />
        </label>
        <label className="text-xs font-semibold text-muted">Visit date
          <input type="date" className="input mt-1" value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <button className="btn-ghost px-2 py-1 text-xs" onClick={() => setShowText(!showText)}>
          <ChevronDown className={`h-4 w-4 transition ${showText ? "rotate-180" : ""}`} /> {visit.source === "document" ? "What I read from the document" : "Full transcript"}
        </button>
        {visit.document_id && <button className="btn-ghost px-2 py-1 text-xs" onClick={openOriginal}><FileText className="h-4 w-4" /> View original</button>}
      </div>
      {showText && <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap rounded-xl bg-canvas p-3 text-xs text-ink">{visit.transcript}</pre>}

      {flagged > 0 && (
        <p className="mt-3 flex items-center gap-2 rounded-xl bg-amber-50 px-3 py-2 text-xs font-medium text-amber-800">
          <AlertTriangle className="h-4 w-4 shrink-0" /> {flagged} item{flagged > 1 ? "s need" : " needs"} a careful check against what the doctor said.
        </p>
      )}

      <ul className="mt-3 space-y-3">
        {items.map((it, idx) => (
          <li key={it.id || `n${idx}`} className={`rounded-xl border p-3 ${it.needs_check ? "border-amber-300 bg-amber-50/40" : "border-line"}`}>
            <div className="flex items-center gap-2">
              <select className="rounded-lg border border-line bg-white px-2 py-1 text-xs font-semibold" value={it.category}
                onChange={(e) => set(idx, { category: e.target.value })} aria-label="Category">
                {Object.entries(CATEGORY).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
              </select>
              <span className="flex-1" />
              <button className="rounded-lg p-1.5 text-muted hover:bg-red-50 hover:text-red-600" aria-label="Remove"
                onClick={() => setItems((xs) => xs.filter((_, i) => i !== idx))}><Trash2 className="h-4 w-4" /></button>
            </div>
            <textarea className="input mt-2 min-h-[44px] text-[15px]" rows={2} value={it.simple_text}
              onChange={(e) => set(idx, { simple_text: e.target.value, needs_check: false })} aria-label="Instruction" />
            {it.source_sentence && <p className="mt-1.5 text-xs text-muted"><span className="font-semibold">Doctor said:</span> “{it.source_sentence}”</p>}
            {it.needs_check && it.check_reason && <p className="mt-1.5 flex items-start gap-1.5 text-xs font-medium text-amber-800"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{it.check_reason}</p>}
          </li>
        ))}
      </ul>
      <button className="btn-ghost mt-2 px-2 py-1 text-xs" onClick={() => setItems((xs) => [...xs, { category: "other", simple_text: "", source_sentence: "" }])}>
        <Plus className="h-4 w-4" /> Add an instruction
      </button>

      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-line pt-4">
        <button className="btn-primary" disabled={busy || !items.some((i) => i.simple_text.trim())} onClick={confirm}>
          {busy === "confirm" ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />} Confirm &amp; save
        </button>
        <button className="btn-outline" disabled={!!busy} onClick={onDiscard}>Discard</button>
      </div>
    </Bubble>
  );
}

/* ------------------------------------------------------------------ confirmed instructions */
function TranslationEditor({ ins, lang, onSaved, toast }) {
  const t = ins.translations?.[lang];
  const [text, setText] = useState(t?.text || "");
  const [reviewer, setReviewer] = useState(t?.verified_by || "");
  const [verified, setVerified] = useState(!!t?.verified);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try { onSaved((await api.put(`/api/visits/instructions/${ins.id}/translations/${lang}`, { text, verified, reviewer: reviewer || null })).data); }
    catch (e) { toast.error(errorMessage(e)); }
    finally { setBusy(false); }
  };
  return (
    <div className="mt-2 space-y-2 rounded-xl bg-canvas p-3">
      <textarea className="input text-[15px]" rows={2} value={text} onChange={(e) => setText(e.target.value)} />
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <label className="flex items-center gap-1.5"><input type="checkbox" checked={verified} onChange={(e) => setVerified(e.target.checked)} /> Checked by a native speaker</label>
        <input className="input w-44 py-1.5 text-xs" placeholder="Reviewer name" value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
        <button className="btn-primary px-3 py-1.5 text-xs" disabled={busy || !text.trim()} onClick={save}>Save</button>
      </div>
    </div>
  );
}

export function InstructionsCard({ visit, lang, clips, onChange, toast, compact }) {
  const { byCode } = useLanguages();
  const native = byCode[lang]?.native || lang;
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState({});
  const [editing, setEditing] = useState(null);
  const tried = useRef(false);
  const missing = lang !== "en" && visit.instructions.some((i) => !i.translations?.[lang]);

  const translate = async () => {
    setBusy(true);
    try { onChange((await api.post(`/api/visits/${visit.id}/translate`, { lang })).data); }
    catch (e) { toast.error(errorMessage(e)); }
    finally { setBusy(false); }
  };
  useEffect(() => { tried.current = false; }, [lang]);
  useEffect(() => { if (missing && !tried.current) { tried.current = true; translate(); } }, [missing, lang]); // eslint-disable-line

  const textOf = (i) => (lang === "en" ? i.simple_text : i.translations?.[lang]?.text);
  const trs = visit.instructions.map((i) => i.translations?.[lang]).filter(Boolean);
  const allUnverified = lang !== "en" && trs.length > 0 && trs.every((t) => !t.verified);
  const allVerified = lang !== "en" && trs.length > 0 && trs.every((t) => t.verified);
  const playable = visit.instructions.filter((i) => textOf(i));
  const shown = compact ? visit.instructions.slice(0, 3) : visit.instructions;

  return (
    <Bubble>
      <div className="flex flex-wrap items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-full bg-teal-50 text-teal"><Stethoscope className="h-5 w-5" /></span>
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-ink">{visit.doctor_name || "Your doctor"} · {fmtDate(visit.visit_date)}</p>
          <p className="text-xs text-muted">{SOURCE[visit.source]} · <span className="font-semibold text-emerald-700">Confirmed by you</span></p>
        </div>
        {playable.length > 0 && (
          <button className="btn-primary rounded-full px-4" onClick={() => clips.play(playable.map((i) => audioPath(i.id, lang)))}>
            <Play className="h-4 w-4" /> {word("playAll", lang)}
          </button>
        )}
      </div>
      {allUnverified && <p className="mt-3"><TranslationBadge t={{ verified: false }} /></p>}
      {allVerified && <p className="mt-3 chip bg-emerald-50 text-emerald-700"><CheckCircle2 className="h-3 w-3" /> {native} checked by a native speaker</p>}
      {missing && (
        <p className="mt-3 flex items-center gap-2 text-sm text-muted">
          {busy ? <><Loader2 className="h-4 w-4 animate-spin" /> Translating to {native}…</> :
            <button className="btn-outline px-3 py-1.5 text-xs" onClick={translate}>Translate to {native}</button>}
        </p>
      )}
      <ul className="mt-3 divide-y divide-line">
        {shown.map((i) => {
          const text = textOf(i), cat = CATEGORY[i.category] || CATEGORY.other;
          return (
            <li key={i.id} className="py-3">
              <div className="flex items-start gap-3">
                <span className={`chip mt-1 shrink-0 ${cat.tone}`}>{lang === "ta" ? cat.ta : cat.label}</span>
                <p className={`min-w-0 flex-1 text-[17px] leading-relaxed ${text ? "text-ink" : "text-muted"}`}>{text || i.simple_text}</p>
                {text && <PlayBtn path={audioPath(i.id, lang)} clips={clips} label={word("hear", lang)} />}
              </div>
              <div className="ml-0 mt-1.5 flex flex-wrap items-center gap-2 sm:ml-[84px]">
                {lang !== "en" && !allUnverified && !allVerified && <TranslationBadge t={i.translations?.[lang]} />}
                <button className="text-xs font-semibold text-brand" onClick={() => setOpen((o) => ({ ...o, [i.id]: !o[i.id] }))}>
                  {open[i.id] ? "Hide" : "What the doctor said"}
                </button>
                {lang !== "en" && i.translations?.[lang] && (
                  <button className="inline-flex items-center gap-1 text-xs font-semibold text-muted" onClick={() => setEditing(editing === i.id ? null : i.id)}>
                    <Pencil className="h-3 w-3" /> Review translation
                  </button>
                )}
              </div>
              {open[i.id] && (
                <p className="mt-1.5 rounded-lg bg-canvas px-3 py-2 text-xs text-muted sm:ml-[84px]">
                  “{i.source_sentence || i.simple_text}”{lang !== "en" && <><br /><span className="font-semibold">In simple English:</span> {i.simple_text}</>}
                </p>
              )}
              {editing === i.id && (
                <div className="sm:ml-[84px]"><TranslationEditor ins={i} lang={lang} toast={toast} onSaved={(ins) => {
                  onChange({ ...visit, instructions: visit.instructions.map((x) => (x.id === ins.id ? ins : x)) });
                  setEditing(null);
                }} /></div>
              )}
            </li>
          );
        })}
      </ul>
      {compact && visit.instructions.length > 3 && <p className="text-xs text-muted">+ {visit.instructions.length - 3} more</p>}
    </Bubble>
  );
}

/* ------------------------------------------------------------------ answers */
export function AnswerCard({ a, clips }) {
  const lang = a.lang;
  if (a.type === "emergency") {
    return (
      <Bubble tone="red">
        <div className="flex items-start gap-3">
          <ShieldAlert className="mt-0.5 h-7 w-7 shrink-0 text-red-600" />
          <div className="flex-1">
            <p className="text-lg font-semibold text-red-800">{a.message}</p>
            {a.message_english && <p className="mt-1 text-sm font-medium text-red-700">{a.message_english}</p>}
            <div className="mt-3 flex flex-wrap gap-2">
              <a href="tel:108" className="btn-danger rounded-full px-5 text-base"><Phone className="h-5 w-5" /> Call 108</a>
              <PlayBtn path={phrasePath("emergency", lang)} clips={clips} big label={word("hear", lang)} />
            </div>
            <p className="mt-2 text-xs text-red-700/80">For emergencies MediMemory does not look at your records.</p>
          </div>
        </div>
      </Bubble>
    );
  }
  if (a.type === "refusal" || a.type === "not_found") {
    return (
      <Bubble tone={a.type === "refusal" ? "amber" : "grey"}>
        <div className="flex items-start gap-3">
          {a.type === "refusal" ? <ShieldAlert className="mt-0.5 h-6 w-6 shrink-0 text-amber-600" /> : <FileText className="mt-0.5 h-6 w-6 shrink-0 text-muted" />}
          <div className="flex-1">
            <p className="text-[16px] text-ink">{a.message}</p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <PlayBtn path={phrasePath(a.phrase, lang)} clips={clips} label={word("hear", lang)} />
              {!a.message_verified && <span className="chip bg-amber-50 text-amber-700">Translated wording · not yet checked by a native speaker</span>}
            </div>
          </div>
        </div>
      </Bubble>
    );
  }
  const first = a.matches[0];
  return (
    <Bubble>
      <p className="text-xs font-semibold uppercase tracking-wide text-muted">
        From your visit with {first.doctor_name || "your doctor"} · {fmtDate(first.visit_date)}
      </p>
      <ul className="mt-2 space-y-3">
        {a.matches.map((m) => (
          <li key={m.instruction_id} className="rounded-xl bg-canvas p-3">
            <div className="flex items-start gap-3">
              <p className="min-w-0 flex-1 text-[17px] leading-relaxed text-ink">{m.text}</p>
              <PlayBtn path={audioPath(m.instruction_id, m.text_lang)} clips={clips} label={word("hear", m.text_lang)} />
            </div>
            <p className="mt-2 text-xs text-muted"><span className="font-semibold">Source, what the doctor said:</span> “{m.source_sentence || m.english}”</p>
            {m.text_lang === "ta" && !m.translation_verified && <span className="chip mt-2 bg-amber-50 text-amber-700"><AlertTriangle className="h-3 w-3" /> Machine translation · not yet checked</span>}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[11px] text-muted">Answered only from instructions you confirmed · {a.timing_ms} ms</p>
    </Bubble>
  );
}

export function UserBubble({ m, onEdit }) {
  return (
    <div className="ml-auto max-w-[85%] rounded-2xl rounded-br-md bg-navy px-4 py-3 text-[15px] text-white shadow-sm">
      {m.kind === "voice" && <span className="mb-1 flex items-center gap-1 text-[11px] font-semibold text-sky-200"><Mic className="h-3 w-3" /> Heard</span>}
      {m.kind === "file" && <span className="mb-1 flex items-center gap-1 text-[11px] font-semibold text-sky-200"><FileText className="h-3 w-3" /> Document</span>}
      {m.kind === "record" && <span className="mb-1 flex items-center gap-1 text-[11px] font-semibold text-sky-200"><Mic className="h-3 w-3" /> Doctor visit recording</span>}
      <p className="whitespace-pre-wrap">{m.text}</p>
      {m.kind === "voice" && onEdit && <button className="mt-1 text-[11px] font-semibold text-sky-200 underline" onClick={() => onEdit(m.text)}>Not right? Edit and ask again</button>}
    </div>
  );
}

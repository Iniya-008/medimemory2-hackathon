import { useEffect, useState } from "react";
import { api } from "../services/api";

let cached = null;
const FALLBACK = [
  { code: "en", name: "English", native: "English", group: "india" },
  { code: "ta", name: "Tamil", native: "தமிழ்", group: "india" },
];

/** Languages the server can translate into and speak (from ElevenLabs' supported list). */
export function useLanguages() {
  const [langs, setLangs] = useState(cached || FALLBACK);
  useEffect(() => {
    if (cached) return;
    api.get("/api/visits/languages").then((r) => {
      if (Array.isArray(r.data?.languages) && r.data.languages.length) { cached = r.data.languages; setLangs(cached); }
    }).catch(() => {});
  }, []);
  const byCode = Object.fromEntries(langs.map((l) => [l.code, l]));
  return { langs, byCode };
}

/** A few UI words in the user's language; other languages fall back to English. */
const WORDS = {
  hear: { en: "Hear it", ta: "கேளுங்கள்", hi: "सुनिए" },
  playAll: { en: "Play all", ta: "எல்லாம் கேளுங்கள்", hi: "सब सुनिए" },
  ask: { en: "Ask a question…", ta: "கேள்வி கேளுங்கள்…", hi: "सवाल पूछिए…" },
  hello: { en: "Vanakkam", ta: "வணக்கம்", hi: "नमस्ते" },
  listening: { en: "Listening…", ta: "கேட்கிறேன்…", hi: "सुन रहा हूँ…" },
};
export const word = (key, lang) => WORDS[key]?.[lang] || WORDS[key]?.en || key;

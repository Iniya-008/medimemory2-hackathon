import { useCallback, useEffect, useRef, useState } from "react";

function pickMime() {
  if (typeof MediaRecorder === "undefined") return "";
  return ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"].find((t) => MediaRecorder.isTypeSupported?.(t)) || "";
}

/** Microphone recorder with live level meter. stop() resolves to a Blob (or null if cancelled). */
export function useRecorder({ maxSeconds = 600, bars = 24 } = {}) {
  const [state, setState] = useState("idle"); // idle | starting | recording
  const [seconds, setSeconds] = useState(0);
  const [levels, setLevels] = useState(() => Array(bars).fill(0.08));
  const [error, setError] = useState("");
  const rec = useRef(null);
  const chunks = useRef([]);
  const stream = useRef(null);
  const ctx = useRef(null);
  const raf = useRef(null);
  const timer = useRef(null);
  const resolver = useRef(null);
  const cancelled = useRef(false);

  const cleanup = useCallback(() => {
    cancelAnimationFrame(raf.current);
    clearInterval(timer.current);
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    ctx.current?.close().catch(() => {});
    ctx.current = null;
    setLevels(Array(bars).fill(0.08));
  }, [bars]);

  useEffect(() => () => cleanup(), [cleanup]);

  const start = useCallback(async () => {
    setError("");
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("This browser can't record audio. Please type instead, or use Chrome on your phone.");
      return false;
    }
    setState("starting");
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch (e) {
      setState("idle");
      setError(e?.name === "NotAllowedError"
        ? "Microphone permission was blocked. Allow the microphone in your browser's address bar, then try again."
        : "No microphone was found. Please connect one, or type instead.");
      return false;
    }
    const mime = pickMime();
    const r = new MediaRecorder(stream.current, mime ? { mimeType: mime } : undefined);
    chunks.current = [];
    cancelled.current = false;
    r.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
    r.onstop = () => {
      const blob = cancelled.current ? null : new Blob(chunks.current, { type: r.mimeType || "audio/webm" });
      cleanup();
      setState("idle");
      resolver.current?.(blob);
      resolver.current = null;
    };
    try {
      const AC = window.AudioContext || window.webkitAudioContext;
      ctx.current = new AC();
      const an = ctx.current.createAnalyser();
      an.fftSize = 256;
      ctx.current.createMediaStreamSource(stream.current).connect(an);
      const buf = new Uint8Array(an.frequencyBinCount);
      const loop = () => {
        an.getByteFrequencyData(buf);
        const step = Math.floor(buf.length / bars);
        setLevels(Array.from({ length: bars }, (_, i) => Math.min(1, (buf[i * step] || 0) / 200 + 0.06)));
        raf.current = requestAnimationFrame(loop);
      };
      loop();
    } catch { /* level meter is optional */ }
    r.start(250);
    rec.current = r;
    setSeconds(0);
    timer.current = setInterval(() => setSeconds((s) => {
      if (s + 1 >= maxSeconds) rec.current?.state === "recording" && rec.current.stop();
      return s + 1;
    }), 1000);
    setState("recording");
    return true;
  }, [bars, cleanup, maxSeconds]);

  const stop = useCallback(() => new Promise((resolve) => {
    if (!rec.current || rec.current.state !== "recording") { resolve(null); return; }
    resolver.current = resolve;
    rec.current.stop();
  }), []);

  const cancel = useCallback(() => {
    cancelled.current = true;
    if (rec.current?.state === "recording") rec.current.stop(); else cleanup();
  }, [cleanup]);

  return { state, seconds, levels, error, setError, start, stop, cancel };
}

export const mmss = (s) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

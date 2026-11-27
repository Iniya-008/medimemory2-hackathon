import { useCallback, useEffect, useRef, useState } from "react";
import { api, blobErrorMessage } from "../services/api";

/**
 * Plays cached ElevenLabs clips served by the backend (auth header required, so we fetch blobs).
 * key = a URL path like /api/visits/instructions/12/audio?lang=ta
 */
export function useClips(onError) {
  const cache = useRef(new Map());
  const audio = useRef(null);
  const queue = useRef([]);
  const [playing, setPlaying] = useState(null);
  const [loading, setLoading] = useState(null);
  const lastWarn = useRef(0);
  const warn = (msg) => { if (Date.now() - lastWarn.current > 8000) { lastWarn.current = Date.now(); onError?.(msg); } };

  useEffect(() => () => {
    audio.current?.pause();
    cache.current.forEach((u) => URL.revokeObjectURL(u));
  }, []);

  const stop = useCallback(() => {
    queue.current = [];
    audio.current?.pause();
    setPlaying(null);
  }, []);

  const fetchUrl = useCallback(async (path) => {
    let url = cache.current.get(path);
    if (!url) {
      const r = await api.get(path, { responseType: "blob" });
      url = URL.createObjectURL(r.data);
      cache.current.set(path, url);
    }
    return url;
  }, []);

  const playOne = useCallback(async (path) => {
    setLoading(path);
    try {
      const url = await fetchUrl(path);
      setLoading(null);
      await new Promise((resolve) => {
        const a = new Audio(url);
        audio.current?.pause();
        audio.current = a;
        a.onended = resolve;
        a.onpause = resolve;
        setPlaying(path);
        a.onerror = () => { warn("This audio couldn't be played. Please try again."); resolve(); };
        a.play().catch((err) => {
          warn(err?.name === "NotAllowedError" ? "Tap the play button to hear it (your browser blocked autoplay)." : "This audio couldn't be played. Please try again.");
          resolve();
        });
      });
    } catch (e) {
      setLoading(null);
      warn(await blobErrorMessage(e, "Couldn't play the audio."));
      queue.current = [];
    } finally {
      setPlaying((p) => (p === path ? null : p));
    }
  }, [fetchUrl, onError]);

  /** Play one path, or several in order. Pressing the same single path again stops it. */
  const play = useCallback(async (paths) => {
    const list = Array.isArray(paths) ? paths : [paths];
    if (list.length === 1 && playing === list[0]) { stop(); return; }
    stop();
    queue.current = [...list];
    while (queue.current.length) {
      const next = queue.current.shift();
      await playOne(next);
    }
  }, [playOne, playing, stop]);

  const prefetch = useCallback((paths) => { paths.forEach((p) => fetchUrl(p).catch(() => {})); }, [fetchUrl]);

  return { play, stop, prefetch, playing, loading };
}

"""Exit check for the after-visit loop against a running backend (local or staging).

Usage:
  python scripts/core_loop_check.py --base https://YOUR-STAGING.onrender.com --email demo@medimemory.app --password Demo@1234
  python scripts/core_loop_check.py --base http://127.0.0.1:8000 --audio sample_visit.webm --runs 10

It never prints API keys. It uses ONLY synthetic data. Results are also written to core_loop_results.json.
Latency measured = question sent -> answer JSON received -> first instruction audio fully downloaded.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time

import httpx

SAMPLE = (
    "Doctor: Lakshmi amma, your sugar and BP are a little high. "
    "Take Metformin 500 mg one tablet after breakfast and one after dinner. "
    "Take Amlodipine 5 mg once in the morning. "
    "Avoid sweets and reduce rice at night. "
    "Walk for 30 minutes every evening. "
    "Do an HbA1c blood test before the next visit. "
    "Come back after one month."
)
QUESTIONS = [
    ("When should I take Metformin?", "grounded"),
    ("What did the doctor say about food?", "grounded"),
    ("Can I play cricket on Sunday?", "not_found"),
    ("Can I double the dose today?", "refusal"),
    ("What should I take for a headache?", "refusal"),
    ("I have chest pain", "emergency"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--email", default="demo@medimemory.app")
    ap.add_argument("--password", default="Demo@1234")
    ap.add_argument("--audio", help="optional recorded consultation (webm/mp3/m4a/wav)")
    ap.add_argument("--lang", default="ta", choices=["en", "ta"])
    ap.add_argument("--runs", type=int, default=5, help="latency runs per grounded question")
    a = ap.parse_args()
    base = a.base.rstrip("/") + "/api"
    c = httpx.Client(timeout=120)
    ok = True

    def step(name, resp, expect=(200, 201)):
        nonlocal ok
        good = resp.status_code in expect
        ok &= good
        print(f"[{'OK ' if good else 'FAIL'}] {name}: HTTP {resp.status_code}" + ("" if good else f" -> {resp.text[:300]}"))
        if not good:
            sys.exit(1)
        return resp

    t = step("login", c.post(f"{base}/auth/login", json={"email": a.email, "password": a.password})).json()["access_token"]
    c.headers["Authorization"] = f"Bearer {t}"
    step("enable AI & voice consent (demo account)", c.patch(f"{base}/auth/me", json={"ai_data_consent": True}))
    status = c.get(f"{base}/assistant/status").json()
    print(f"      LLM configured: {status.get('llm_configured')}  model: {status.get('model')}")

    t0 = time.perf_counter()
    if a.audio:
        with open(a.audio, "rb") as f:
            v = step("record -> ElevenLabs speech-to-text", c.post(
                f"{base}/visits/record", data={"consent": "true", "doctor_name": "Dr. Kavitha Rao",
                                               "consent_note": "Synthetic test recording"},
                files={"file": (a.audio, f.read(), "audio/webm")})).json()
    else:
        v = step("typed sample transcript", c.post(f"{base}/visits/typed",
                                                   json={"transcript": SAMPLE, "doctor_name": "Dr. Kavitha Rao", "source": "sample"})).json()
    print(f"      transcript ({v.get('transcript_language')}): {v['transcript'][:160]}...")
    v = step("extract instructions", c.post(f"{base}/visits/{v['id']}/extract")).json()
    print(f"      method: {v['extraction_method']}, {len(v['instructions'])} instructions, extract {v.get('timing_ms')} ms")
    for i in v["instructions"]:
        flag = f"  <-- CHECK: {i['check_reason']}" if i["needs_check"] else ""
        print(f"        - [{i['category']}] {i['simple_text']}{flag}")
    v = step("confirm", c.post(f"{base}/visits/{v['id']}/confirm")).json()
    if a.lang != "en":
        v = step(f"translate -> {a.lang}", c.post(f"{base}/visits/{v['id']}/translate", json={"lang": a.lang})).json()
        for i in v["instructions"]:
            tr = i["translations"].get(a.lang, {})
            print(f"        {a.lang}: {tr.get('text')}  (verified={tr.get('verified')})")
    pw = step("prewarm audio", c.post(f"{base}/visits/{v['id']}/prewarm", json={"langs": sorted({"en", a.lang})})).json()
    print(f"      audio generated {pw['generated']}, cached {pw['already_cached']}, missing {pw['missing_translation']}")
    print(f"      record->ready total: {time.perf_counter() - t0:.1f} s")

    results = []
    for q, expected in QUESTIONS:
        times = []
        for _ in range(a.runs if expected == "grounded" else 1):
            s = time.perf_counter()
            ans = step(f"ask: {q}", c.post(f"{base}/visits/ask", json={"question": q, "lang": a.lang})).json()
            if ans["matches"]:
                c.get(f"{base}/visits/instructions/{ans['matches'][0]['instruction_id']}/audio", params={"lang": a.lang})
            elif ans.get("phrase"):
                c.get(f"{base}/visits/phrases/{ans['phrase']}/audio", params={"lang": a.lang})
            times.append((time.perf_counter() - s) * 1000)
        passed = ans["type"] == expected
        ok &= passed
        results.append({"question": q, "expected": expected, "got": ans["type"], "pass": passed, "matcher": ans.get("matcher"),
                        "median_ms": round(statistics.median(times)), "worst_ms": round(max(times)), "runs": len(times),
                        "answer": [m["text"] for m in ans["matches"]] or ans.get("message")})
        print(f"[{'PASS' if passed else 'FAIL'}] {q!r}: {ans['type']} (expected {expected}); "
              f"median {round(statistics.median(times))} ms, worst {round(max(times))} ms over {len(times)} run(s)")

    with open("core_loop_results.json", "w", encoding="utf-8") as f:
        json.dump({"base": a.base, "lang": a.lang, "llm": status, "results": results}, f, ensure_ascii=False, indent=2)
    print("\nALL CHECKS PASSED" if ok else "\nSOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

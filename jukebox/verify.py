#!/usr/bin/env python3
"""AI Jukebox — library integrity gate (stdlib only).

Checks every setlist in library/: playlist.js parses and matches setlist.json,
track audio/wav/cover/lyrics/dj files exist, WAVs decode as non-silent stereo
of sane length, covers are well-formed SVG, DJ clips are speakable-length.
Exit 0 = all green. Used by humans and by Claude Code (/verify).
"""
from __future__ import annotations
import array, glob, hashlib, json, os, sys, wave

ROOT = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(ROOT, "library")


def parse_js(path: str) -> dict | None:
    txt = open(path, encoding="utf-8").read()
    i = txt.find("{")
    if i < 0:
        return None
    return json.loads(txt[i:].rstrip().rstrip(";"))


def wav_stats(path: str) -> tuple[float, float, int] | None:
    """(duration_s, rms, channels) — None if not a decodable WAV."""
    try:
        with wave.open(path, "rb") as w:
            ch, sw, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
            if sw != 2 or ch not in (1, 2):
                return None
            dur = n / sr
            data = w.readframes(n)
        a = array.array("h")
        a.frombytes(data)
        if not len(a):
            return None
        step = max(1, len(a) // 400_000)          # downsample for RMS
        rms = (sum(v * v for v in a[::step]) / len(a[::step])) ** 0.5
        return round(dur, 1), round(rms / 32768.0, 4), ch
    except Exception:
        return None


def main() -> int:
    if not os.path.isdir(LIB):
        print("no library/ — run: python3 generate.py demo")
        return 1
    failures, ok_count, checks = [], 0, []

    for sl in sorted(glob.glob(os.path.join(LIB, "*", "setlist.json"))):
        sid = os.path.basename(os.path.dirname(sl))
        try:
            data = json.load(open(sl))
        except Exception as e:
            failures.append(f"[{sid}] setlist.json unreadable: {e}")
            continue
        pj = os.path.join(os.path.dirname(sl), "playlist.js")
        js = parse_js(pj) if os.path.exists(pj) else None
        checks.append(f"{sid}: playlist.js parses" if js else f"{sid}: playlist.js missing/bad")
        if js is None or js != data:
            failures.append(f"[{sid}] playlist.js does not match setlist.json")
        if len(data.get("tracks", [])) == 0:
            failures.append(f"[{sid}] empty track list")
        for t in data.get("tracks", []):
            tag = f"[{sid}/{t.get('id', '?')}]"
            for k, min_s in (("audio", 5), ("wav", 5)):
                p = os.path.join(ROOT, t.get(k, ""))
                if not os.path.exists(p):
                    failures.append(f"{tag} missing {k}: {t.get(k)}")
                    continue
                if os.path.getsize(p) < 40_000:
                    failures.append(f"{tag} {k} suspiciously small")
            wav_p = os.path.join(ROOT, t.get("wav", ""))
            if os.path.exists(wav_p):
                st = wav_stats(wav_p)
                if st is None:
                    failures.append(f"{tag} undecodable WAV")
                else:
                    dur, rms, ch = st
                    if dur < 8:
                        failures.append(f"{tag} too short ({dur}s)")
                    if rms < 0.005:
                        failures.append(f"{tag} silent (rms {rms})")
                    if ch != 2:
                        failures.append(f"{tag} not stereo")
                    checks.append(f"{tag} wav {dur}s rms {rms}")
            cover = os.path.join(ROOT, t.get("cover", ""))
            if os.path.exists(cover):
                svg = open(cover, encoding="utf-8", errors="replace").read()
                if not svg.lstrip().startswith("<svg") or "</svg>" not in svg:
                    failures.append(f"{tag} cover.svg malformed")
            else:
                failures.append(f"{tag} missing cover")
            lyr = os.path.join(ROOT, os.path.dirname(t.get("wav", "")), "lyrics.txt")
            if not os.path.exists(lyr):
                failures.append(f"{tag} missing lyrics.txt")
            dj = t.get("dj")
            if dj:
                dp = os.path.join(ROOT, dj["audio"])
                if not os.path.exists(dp):
                    failures.append(f"{tag} dj audio missing")
                else:
                    st = wav_stats(dp)
                    if st is None:
                        failures.append(f"{tag} dj undecodable")
                    elif not 1.5 <= st[0] <= 45:
                        failures.append(f"{tag} dj weird length {st[0]}s")
        lead = data.get("lead")
        if lead:
            lp = os.path.join(ROOT, lead["audio"])
            if not os.path.exists(lp):
                failures.append(f"[{sid}] lead dj audio missing")

    print(f"checked {len(glob.glob(os.path.join(LIB, '*', 'setlist.json')))} setlists, "
          f"{sum(1 for c in checks if c)} integrity points")
    for c in checks:
        pass
    if failures:
        print("\nFAILURES:")
        for f in failures:
            print("  ✗", f)
        return 1
    print("ALL GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""AI Jukebox — generator CLI.

Commands:
  python3 generate.py song     <args>   one song (wav/mp3 + cover + lyrics + info)
  python3 generate.py setlist  <args>   a themed setlist with DJ commentary
  python3 generate.py dj       <args>   one DJ voice clip
  python3 generate.py art      <args>   one cover (SVG, optional PNG)
  python3 generate.py demo              build the two demo setlists
  python3 generate.py serve             serve the library over http
  python3 generate.py list              show built setlists

Library lives in ./library/<setlist>/ with playlist.js for player.html.
player.html loads library/index.js (setlist picker) + a setlist's playlist.js.
"""
from __future__ import annotations
import argparse, json, os, random, shutil, subprocess, sys, wave

import numpy as np
import engine, lyrics as lyrics_mod, art as art_mod, dj as dj_mod

ROOT = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(ROOT, "library")
NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
SCALES = list(engine.SCALES.keys())
GENRES = list(engine.GENRES.keys())
FFMPEG = shutil.which("ffmpeg")


def key_name(midi: int) -> str:
    return NOTES[midi % 12]


def check_ffmpeg() -> bool:
    if not FFMPEG:
        print("[warn] ffmpeg not found — skipping mp3 encodes (wav only).")
    return bool(FFMPEG)


def to_mp3(wav_path: str, mp3_path: str) -> bool:
    if not FFMPEG:
        return False
    r = subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", wav_path,
                        "-b:a", "192k", mp3_path], capture_output=True)
    return r.returncode == 0 and os.path.exists(mp3_path)


def make_song(seed: int, genre: str, out_dir: str, bpm: int | None = None,
              key_note: int | None = None, scale: str | None = None,
              mood: float | None = None, length: str = "medium",
              title: str | None = None, artist: str | None = None,
              llm: bool = False, vocals: bool = False) -> dict:
    """Generate one complete song + cover + lyrics into out_dir. Returns info dict."""
    os.makedirs(out_dir, exist_ok=True)
    rng = np.random.default_rng(seed)
    rnd = random.Random(seed)
    g = engine.GENRES[genre]
    bpm = bpm or int(rnd.uniform(*g["bpm"]))
    scale = scale or g["keys"]
    key_note = key_note if key_note is not None else int(rng.integers(45, 60))
    mood = round(mood if mood is not None else 0.35 + rng.random() * 0.55, 2)
    title = title or lyrics_mod.title_for(seed, genre, rng)
    artist = artist or lyrics_mod.artist_for(genre, rng)
    scale_name = scale if scale != "pent_minor" else "minor pentatonic"

    song = engine.Song(seed=seed, genre=genre, bpm=bpm, key_note=key_note,
                       scale=scale, mood=mood, length=length, title=title)
    L, R, dur = engine.render(song, length)

    wav_path = os.path.join(out_dir, "song.wav")
    engine.write_wav(wav_path, L, R)
    mp3_path = os.path.join(out_dir, "song.mp3")
    to_mp3(wav_path, mp3_path)

    lines = lyrics_mod.lyrics_for(seed, genre, title, rng)
    if llm:
        ll = dj_mod._llm(
            f"Write original song lyrics, no intro comment, for a {genre} track "
            f"titled '{title}'. Structure: [Verse 1] 4 lines, [Chorus] 4 lines, "
            f"[Verse 2] 4 lines, [Chorus] 4 lines, [Bridge] 2 lines, [Outro] 1 line. "
            "Plain lines only, no labels except the brackets, ~9 syllables per line.",
            max_tokens=320, timeout=40)
        if ll and "[Verse" in ll:
            lines = [ln.strip() for ln in ll.splitlines() if ln.strip()]
    with open(os.path.join(out_dir, "lyrics.txt"), "w") as f:
        f.write(f"{title}\n{artist}\n{'=' * 40}\n")
        f.write("\n".join(lines))

    cover = os.path.join(out_dir, "cover.svg")
    art_mod.write_cover(cover, seed, genre, title, artist, mood, bpm, dur,
                        scale=scale_name)

    info = dict(id=os.path.basename(out_dir), seed=seed, title=title, artist=artist,
                genre=genre, bpm=bpm, key=key_name(key_note), key_note=key_note,
                scale=scale_name, mood=mood,
                mood_label=lyrics_mod.MOOD_LABELS[int(rng.integers(len(lyrics_mod.MOOD_LABELS)))],
                length_s=round(dur, 1), length=length,
                audio="song.mp3" if os.path.exists(mp3_path) else "song.wav",
                wav="song.wav", cover="cover.svg")
    vox_path = os.path.join(out_dir, "vox.wav")
    if vocals:
        _vocoder_vocal(lines, song, key_note, vox_path, dur)
        info["vox"] = "vox.wav"
    with open(os.path.join(out_dir, "info.json"), "w") as f:
        json.dump({k: v for k, v in info.items() if isinstance(v, (str, int, float))},
                  f, indent=1)
    # lyrics in playlist payload
    info["lyrics"] = lines
    return info


def _vocoder_vocal(lines: list[str], song: engine.Song, key_note: int,
                   out_wav: str, song_dur: float) -> bool:
    """Experimental: TTS the chorus lines, pitch-shift up, drop into chorus slots."""
    try:
        chords = " ".join(lines)
        chorus_lines = [l for l in lines if not l.startswith("[") and l.strip()][:4]
        if not chorus_lines:
            return False
        # find chorus start times
        secs = song.sections(song.length if hasattr(song, "length") else "medium")
        t = 0.0
        chorus_t = []
        for name, bars, _e in secs:
            if name == "chorus":
                chorus_t.append(t + 0.4)
            t += bars * song.bar
        if not chorus_t:
            return False
        SR = engine.SR
        buf = np.zeros(int(song_dur * SR) + SR)
        for li, line in enumerate(chorus_lines):
            import tempfile
            aiff = tempfile.mktemp(suffix=".aiff")
            w = tempfile.mktemp(suffix=".wav")
            subprocess.run(["say", "-v", "Zarvox", "-r", "200", "-o", aiff, line],
                           capture_output=True, timeout=40)
            subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@22050", aiff, w],
                           capture_output=True, timeout=30)
            with wave.open(w, "rb") as fh:
                fr = fh.getframerate()
                n = fh.getnframes()
                raw = np.frombuffer(fh.readframes(n), dtype=np.int16).astype(np.float64) / 32768.0
            os.unlink(aiff)
            os.unlink(w)
            # pitch up 7 semitones via resample, then time-stretch back
            f_up = 2 ** (7 / 12)
            up = np.interp(np.arange(0, len(raw), 1 / f_up), np.arange(len(raw)), raw)
            # extreme chipmunk: waveshape + slight ring mod
            up = np.tanh(up * 1.9) + 0.18 * np.sin(2 * np.pi * 82 * np.arange(len(up)) / fr) * up
            seg = min(len(up), int(song_dur * SR))
            start = chorus_t[li % len(chorus_t)]
            i0 = min(int(start * SR), max(0, SR * int(song_dur) - seg))
            fade = int(0.05 * SR)
            wseg = up[:seg].copy()
            wseg[:fade] *= np.linspace(0, 1, fade)
            wseg[-fade:] *= np.linspace(1, 0, fade)
            buf[i0:i0 + seg] += wseg * 0.5
        # 2x speed for wordiness? no — keep
        with wave.open(out_wav, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SR)
            pcm = np.clip(buf, -1, 1)
            wf.writeframes((pcm * 32767).astype(np.int16).tobytes())
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[vocoder] skipped ({exc})")
        return False


def make_dj_clip(out_dir: str, idx: int, track: dict, persona: str = "nova",
                 use_llm: bool = True, prev: dict | None = None,
                 voice_ref: bytes | None = None) -> dict:
    script = dj_mod.script_for(persona, track, "intro", use_llm=use_llm, prev=prev)
    audio = dj_mod.synth_voice(persona, script, os.path.join(out_dir, f"dj_{idx:02d}"),
                               ref=voice_ref)
    with open(os.path.join(out_dir, f"dj_{idx:02d}.txt"), "w") as f:
        f.write(script)
    return dict(audio=os.path.basename(audio or f"dj_{idx:02d}.wav"), text=script,
                persona=persona, ok=audio is not None)


def _voice_ref(path: str | None) -> bytes | None:
    """Load --voice-ref / JUKEBOX_DJ_VOICE_REF, or exit with a readable error."""
    path = path or os.environ.get("JUKEBOX_DJ_VOICE_REF")
    if not path:
        return None
    try:
        return dj_mod.load_voice_ref(path)
    except ValueError as exc:
        sys.exit(f"[dj] {exc}")


def setlist_slug(name: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "setlist"


def make_setlist(name: str, theme: str, genres: list[str], count: int,
                 seed: int = 20261022, length: str = "medium", dj_on: bool = True,
                 mix_persona: bool = True, vocals_on: bool = False,
                 llm: bool = False, force: bool = False,
                 voice_ref: bytes | None = None) -> str:
    slug = setlist_slug(name)
    out = os.path.join(LIB, slug)
    if os.path.exists(out):
        if not force:
            print(f"[skip] {slug} exists — rerun with --force to rebuild")
            return slug
        shutil.rmtree(out)
    os.makedirs(out, exist_ok=True)
    rng = np.random.default_rng(seed)
    rnd = random.Random(seed * 7)
    genre_pool = genres or GENRES

    # mood arc for the setlist: build-up then wind-down
    mood_arc = np.linspace(0.35, 0.92, max(2, count // 2)) if count > 3 else [0.55]
    tracks = []
    for i in range(1, count + 1):
        genre = genre_pool[(i - 1) % len(genre_pool)]
        gseed = seed + i * 7919
        mood = float(np.clip(_arc_mood(i, count, rng), 0.25, 0.95))
        tdir = os.path.join(out, f"song_{i:02d}")
        info = make_song(gseed, genre, tdir, mood=mood, length=length,
                         llm=llm, vocals=vocals_on and i == 1)
        info["rel"] = {k: info[k] for k in ("audio", "cover", "wav")}
        moves = {k: f"library/{slug}/song_{i:02d}/{v}" for k, v in info["rel"].items()}
        info.update(moves)
        info.pop("rel", None)
        tracks.append(info)

    lead = None
    added = 0
    if dj_on:
        # station id at top
        lead_text, lead_persona = _lead_script(theme, name, len(tracks))
        lead_audio = dj_mod.synth_voice(lead_persona, lead_text, os.path.join(out, "dj_00"),
                                        ref=voice_ref)
        # a failed clip is left out so the queue goes straight to the song
        lead = dict(audio=f"library/{slug}/{os.path.basename(lead_audio)}", text=lead_text,
                    persona=lead_persona, ok=True) if lead_audio else None
        # per-track intros, each bridging from the song before it
        for i, t in enumerate(tracks):
            persona = dj_mod.pick_persona(t["genre"], rnd) if mix_persona else "nova"
            clip = make_dj_clip(out, i + 1, t, persona, use_llm=llm,
                                prev=tracks[i - 1] if i else None, voice_ref=voice_ref)
            if clip["ok"]:
                clip["audio"] = f"library/{slug}/{clip['audio']}"
                t["dj"] = clip
                added += 1
        if added < len(tracks):
            print(f"[dj] WARNING: {len(tracks) - added} of {len(tracks)} DJ clips failed; "
                  f"those songs play without an intro. Check JUKEBOX_TTS_URL / key.")

    accent = art_mod.palette(seed + 1, tracks[0]["genre"], 0.5)
    acc_hex = _hsl_hex(accent["hue2"], accent["sat"] * 1.15, min(0.7, accent["bri"] + 0.5))
    payload = dict(id=slug, name=name, theme=theme, genres=list(dict.fromkeys([t["genre"] for t in tracks])),
                   count=len(tracks), accent=acc_hex, lead=lead, tracks=tracks,
                   generated=dict(seed=seed, length=length, dj_on=dj_on))
    with open(os.path.join(out, "playlist.js"), "w", encoding="utf-8") as f:
        f.write("// AI Jukebox setlist — regenerate with generate.py\n")
        f.write("window.JUKEBOX_SETLIST = " + json.dumps(payload, ensure_ascii=False, indent=1) + ";\n")
    with open(os.path.join(out, "setlist.json"), "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    # genre -> mood_label standalone json used by nothing yet (kept for parity)
    _write_index()
    print(f"[ok] setlist '{name}' -> {out}  ({len(tracks)} tracks, {added} DJ clips)")
    return slug


def _arc_mood(i, count, rng):
    if count <= 3:
        return 0.4 + rng.random() * 0.3
    peak = int(count * 0.65)
    if i <= peak:
        return 0.4 + 0.5 * (i / max(1, peak))
    return 0.9 - 0.35 * ((i - peak) / max(1, count - peak))


def _lead_script(theme: str, name: str, n: int) -> tuple[str, str]:
    return (f"Welcome to the AI Jukebox. This is {name} — {theme.lower()}. "
            f"{n} handmade transmissions, generated fresh, and me. "
            f"Press play, put your headphones on, and let's begin."), "nova"


def _hsl_hex(h, s, l):
    import colorsys
    h %= 360
    r, g, b = colorsys.hls_to_rgb(h / 360, min(1, l), min(1, s))
    return "#" + "".join(f"{int(round(c * 255)):02x}" for c in (r, g, b))


def _write_index():
    entries = []
    if os.path.isdir(LIB):
        for d in sorted(os.listdir(LIB)):
            pj = os.path.join(LIB, d, "playlist.js")
            if os.path.exists(pj):
                entries.append(dict(id=d, name=d.replace("-", " ").title(),
                                    has_setlist=os.path.exists(os.path.join(LIB, d, "setlist.json"))))
    with open(os.path.join(LIB, "index.js"), "w") as f:
        f.write("// generated by generate.py — setlist picker\n")
        f.write("window.JUKEBOX_INDEX = " + json.dumps(entries) + ";\n")


def cmd_song(a):
    out = os.path.join(LIB, "single-" + setlist_slug(a.title or f"{a.genre}-{a.seed}"))
    info = make_song(a.seed, a.genre, out, bpm=a.bpm, key_note=a.key_note,
                     scale=a.scale, mood=a.mood, length=a.length, title=a.title,
                     artist=a.artist, llm=a.llm, vocals=a.vocals)
    _write_index()
    print(json.dumps({k: info[k] for k in ("id", "title", "artist", "genre", "bpm",
                                           "key", "scale", "mood", "length_s")},
                     indent=1))


def cmd_setlist(a):
    make_setlist(a.name, a.theme or a.name, a.genres.split(",") if a.genres else [],
                 a.count, seed=a.seed, length=a.length, dj_on=not a.no_dj,
                 mix_persona=not a.one_voice, vocals_on=a.vocals, llm=a.llm,
                 force=a.force, voice_ref=_voice_ref(a.voice_ref))


def cmd_dj(a):
    os.makedirs(a.out_dir, exist_ok=True)
    prev = dict(title=a.prev_title) if a.prev_title else None
    clip = make_dj_clip(a.out_dir, a.idx, dict(title=a.title, genre=a.genre, bpm=a.bpm or 100,
                                               seed=a.seed, mood_label=a.mood or "blue hour"),
                        a.persona, use_llm=a.llm, prev=prev, voice_ref=_voice_ref(a.voice_ref))
    print(json.dumps(clip, indent=1))


def cmd_art(a):
    os.makedirs(a.out_dir, exist_ok=True)
    path = os.path.join(a.out_dir, "cover.svg")
    art_mod.write_cover(path, a.seed, a.genre, a.title, a.artist or "AI Jukebox",
                        a.mood or 0.5, a.bpm or 100, a.length or 60, scale=a.scale or "",
                        style=a.style)
    print(path)
    if a.png:
        ok = art_mod.svg_to_png(path, path.replace(".svg", ".png"), a.size)
        print("png:", "ok" if ok else "failed (qlmanage)")


def cmd_demo(a):
    make_setlist("Synthwave Sunday", "chrome nights, midnight freeways, radios that never sleep",
                 ["synthwave", "techno"], 5, seed=20261022, length="medium",
                 dj_on=True, force=a.force, vocals_on=False, llm=a.llm)
    make_setlist("Rainy Study Hour", "rain on glass, warm lamps, homework in stereo",
                 ["lofi", "ambient"], 5, seed=20261023, length="medium",
                 dj_on=True, force=a.force, vocals_on=False, llm=a.llm)


def cmd_serve(a):
    os.makedirs(LIB, exist_ok=True)
    os.chdir(ROOT)
    print(f"Serving {ROOT} at http://localhost:{a.port}/player.html")
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    handler = SimpleHTTPRequestHandler
    ThreadingHTTPServer(("127.0.0.1", a.port), handler).serve_forever()


def cmd_list(a):
    _write_index()
    if not os.path.isdir(LIB):
        print("no library yet")
        return
    for d in sorted(os.listdir(LIB)):
        p = os.path.join(LIB, d, "setlist.json")
        if os.path.exists(p):
            with open(p) as f:
                j = json.load(f)
            print(f"{j['id']:24s} {j['name']!r:26s} {len(j['tracks'])} tracks  "
                  f"accent={j['accent']}")
        elif os.path.isdir(os.path.join(LIB, d)):
            print(f"{d:24s} (no setlist.json)")


def main():
    ap = argparse.ArgumentParser(description="AI Jukebox generator", prog="generate.py")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("song", help="generate one song")
    p.add_argument("--seed", type=int, default=20261022)
    p.add_argument("--genre", choices=GENRES, default="lofi")
    p.add_argument("--bpm", type=int)
    p.add_argument("--key-note", type=int, dest="key_note", help="MIDI root (60=C4)")
    p.add_argument("--scale", choices=SCALES)
    p.add_argument("--mood", type=float)
    p.add_argument("--length", choices=("short", "medium", "long"), default="medium")
    p.add_argument("--title"); p.add_argument("--artist")
    p.add_argument("--llm", action="store_true", help="LLM-written lyrics")
    p.add_argument("--vocals", action="store_true", help="robotic vocoder vocals")
    p.set_defaults(func=cmd_song)

    p = sub.add_parser("setlist", help="generate a themed setlist")
    p.add_argument("--name", required=True)
    p.add_argument("--theme")
    p.add_argument("--genres")
    p.add_argument("--count", type=int, default=5)
    p.add_argument("--seed", type=int, default=20261022)
    p.add_argument("--length", choices=("short", "medium", "long"), default="medium")
    p.add_argument("--no-dj", action="store_true", dest="no_dj")
    p.add_argument("--voice-ref", dest="voice_ref",
                   help="local MP3/WAV (<=10 MB) to clone the DJ voice; kept out of library/")
    p.add_argument("--one-voice", action="store_true", dest="one_voice")
    p.add_argument("--vocals", action="store_true", help="vocoder on track 1")
    p.add_argument("--llm", action="store_true", help="LLM scripts+lyrics")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_setlist)

    p = sub.add_parser("dj", help="one DJ clip")
    p.add_argument("--title", required=True); p.add_argument("--genre", default="lofi")
    p.add_argument("--bpm", type=int); p.add_argument("--seed", type=int, default=1)
    p.add_argument("--mood", default="blue hour")
    p.add_argument("--persona", choices=dj_mod.persona_names(), default="nova")
    p.add_argument("--out-dir", default=os.path.join(LIB, "dj"))
    p.add_argument("--idx", type=int, default=1)
    p.add_argument("--llm", action="store_true")
    p.add_argument("--prev-title", dest="prev_title", help="title of the song that just ended")
    p.add_argument("--voice-ref", dest="voice_ref",
                   help="local MP3/WAV (<=10 MB) to clone the DJ voice")
    p.set_defaults(func=cmd_dj)

    p = sub.add_parser("art", help="one cover")
    p.add_argument("--seed", type=int, default=42); p.add_argument("--genre", default="lofi")
    p.add_argument("--title", default="Neon Rain"); p.add_argument("--artist")
    p.add_argument("--mood", type=float); p.add_argument("--bpm", type=int)
    p.add_argument("--length", type=float)
    p.add_argument("--scale"); p.add_argument("--style")
    p.add_argument("--out-dir", default=os.path.join(LIB, "single"))
    p.add_argument("--png", action="store_true"); p.add_argument("--size", type=int, default=1024)
    p.set_defaults(func=cmd_art)

    p = sub.add_parser("demo")
    p.add_argument("--force", action="store_true")
    p.add_argument("--llm", action="store_true")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("serve")
    p.add_argument("--port", type=int, default=8777)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("list")
    p.set_defaults(func=cmd_list)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

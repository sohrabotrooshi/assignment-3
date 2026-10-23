"""AI Jukebox — DJ commentary: script writer (Qwen on 9001, template fallback)
and TTS voice actor via Chatterbox on 9008 (default voice or a cloned voice
from a local MP3/WAV reference), falling back to macOS `say` when offline.
"""
from __future__ import annotations
import base64, json, os, random, subprocess, tempfile, zlib

PERSONAS = {
    "nova": dict(voice="Daniel",  vibe="energetic club host, hyped, big-voice",
                 opener=["Yo, welcome back to the booth —", "Listen up, night owls —",
                         "Ladies, gentlemen, and every synth in between —"],
                 mid=["this one's got teeth.", "trust me on this one.", "you are not ready for the drop."],
                 closer=["Let's go.", "Turn it up.", "This is what we came here for."]),
    "lana": dict(voice="Samantha", vibe="chill lo-fi host, soft, warm, studious",
                 opener=["Hey... settled in? Good.", "Alright, put your headphones on.",
                         "Pour yourself something warm."],
                 mid=["this is a real window-rain track.", "keep this one on loop.",
                      "zero place to be, and that's the point."],
                 closer=["Breathe in.", "Let it ride.", "See you on the other side."]),
    "rex":  dict(voice="Karen",    vibe="late-night radio announcer, smooth, theatrical",
                 opener=["You're tuned to the quiet hours.", "Good evening, wherever you are.",
                         "Somewhere out there, the city is still going."],
                 mid=["we've got a special transmission here.", "this next one rewards patience.",
                      "produced, allegedly, by a machine with taste."],
                 closer=["Stay golden.", "The night is young still.", "Back in a heartbeat."]),
    "vox":  dict(voice="Zarvox",   vibe="robotic alien jukebox AI, deadpan",
                 opener=["UNIT 6 SIGNING ON.", "MUSIC SEQUENCE INITIATED.",
                         "CALCULATING VIBE FREQUENCY."],
                 mid=["ALL PLEASURE CENTERS NOMINAL.", "RHYTHM PROTOCOL ONLINE.",
                      "ORGANIC LISTENERS DETECTED."],
                 closer=["PLAYING.", "VIBE.CONFIRMED.", "BYE."]),
    "moon": dict(voice="Whisper",  vibe="ethereal whisperer, slow, dreamy",
                 opener=["shhh...", "you made it.", "the night still holds us."],
                 mid=["this one dissolves the room.", "let the edges soften.",
                      "ordinary time is over."],
                 closer=["float on.", "goodnight.", "come back to the tide."]),
}

VOICE_OVERRIDES = {}   # persona -> exact voice name (runtime)


def persona_names():
    return list(PERSONAS)


def _say(text: str, voice: str, out_wav: str, rate: int | None = None) -> bool:
    try:
        with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as tf:
            aiff = tf.name
        cmd = ["say", "-v", voice, "-o", aiff]
        if rate:
            cmd = ["say", "-v", voice, "-r", str(rate), "-o", aiff]
        subprocess.run(cmd, input=text.encode(), capture_output=True, timeout=60)
        if not os.path.exists(aiff) or os.path.getsize(aiff) == 0:
            raise RuntimeError("say produced no output")
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@22050", "-c", "1",
                        aiff, out_wav], capture_output=True, check=True, timeout=60)
        os.unlink(aiff)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[dj] TTS failed for voice {voice}: {exc}")
        return False


# ------------------------------------------------------------ LLM writing ---
# Credentials are read from the environment or a GITIGNORED ./env file —
# never hardcode keys. Copy .env.example and fill it in locally.
def _load_dotenv() -> None:
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    except OSError:
        pass


_load_dotenv()
import os as _os

LLM_URL = _os.environ.get("JUKEBOX_LLM_URL", "http://dobolyi.com:9001/v1/chat/completions")
LLM_MODEL = _os.environ.get("JUKEBOX_LLM_MODEL", "cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit")
LLM_KEY = _os.environ.get("JUKEBOX_LLM_KEY", "") or None

TTS_URL = _os.environ.get("JUKEBOX_TTS_URL", "http://dobolyi.com:9008/v1/audio/speech")
TTS_MODEL = _os.environ.get("JUKEBOX_TTS_MODEL", "chatterbox-v3")
TTS_KEY = _os.environ.get("JUKEBOX_TTS_KEY", "") or LLM_KEY
TTS_TIMEOUT = int(_os.environ.get("JUKEBOX_TTS_TIMEOUT", "120"))

# ------------------------------------------------------- voice reference ---
# A reference recording is read from a local path at generation time and sent
# to Chatterbox; it is never copied into library/ or the repo.
VOICE_REF_EXTS = (".mp3", ".wav")
VOICE_REF_MAX_BYTES = 10 * 1024 * 1024


def load_voice_ref(path: str) -> bytes:
    """Read and validate an MP3/WAV voice reference. Raises ValueError with a
    message meant for the user."""
    path = os.path.expanduser(path)
    ext = os.path.splitext(path)[1].lower()
    if ext not in VOICE_REF_EXTS:
        raise ValueError(f"voice reference must be .mp3 or .wav, got '{ext or 'no extension'}'")
    if not os.path.isfile(path):
        raise ValueError(f"voice reference not found: {path}")
    size = os.path.getsize(path)
    if size == 0:
        raise ValueError("voice reference is empty (0 bytes)")
    if size > VOICE_REF_MAX_BYTES:
        raise ValueError(f"voice reference is {size / 1e6:.1f} MB; limit is "
                         f"{VOICE_REF_MAX_BYTES // (1024 * 1024)} MB")
    with open(path, "rb") as f:
        blob = f.read()
    is_wav = blob[:4] == b"RIFF" and blob[8:12] == b"WAVE"
    is_mp3 = blob[:3] == b"ID3" or (len(blob) > 1 and blob[0] == 0xFF and blob[1] & 0xE0 == 0xE0)
    if (ext == ".wav" and not is_wav) or (ext == ".mp3" and not is_mp3):
        raise ValueError(f"{os.path.basename(path)} is not a real {ext[1:].upper()} file")
    return blob


def _chatterbox(text: str, out_base: str, ref: bytes | None = None) -> str | None:
    """Speak `text` with Chatterbox. Writes out_base + .wav (or .mp3 if the
    server ignores the format hint) and returns that path, or None."""
    import urllib.request
    if not TTS_KEY:
        print("[dj] no JUKEBOX_TTS_KEY / JUKEBOX_LLM_KEY set — Chatterbox skipped (see .env.example).")
        return None
    payload = {"model": TTS_MODEL, "input": text, "language_id": "en", "response_format": "wav"}
    if ref:
        payload["ref_audio"] = base64.b64encode(ref).decode()
    req = urllib.request.Request(TTS_URL, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {TTS_KEY}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TTS_TIMEOUT) as r:
            audio = r.read()
    except Exception as exc:  # noqa: BLE001
        print(f"[dj] Chatterbox unavailable ({exc}).")
        return None
    if len(audio) < 1000:
        print(f"[dj] Chatterbox returned no usable audio ({len(audio)} bytes).")
        return None
    path = out_base + (".wav" if audio[:4] == b"RIFF" else ".mp3")
    with open(path, "wb") as f:
        f.write(audio)
    return path


def _llm(prompt: str, max_tokens: int = 220, timeout: int = 25) -> str | None:
    import urllib.request
    if not LLM_KEY:
        print("[dj] no JUKEBOX_LLM_KEY set — using template script (see .env.example).")
        return None
    body = json.dumps({
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens, "temperature": 0.8,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(LLM_URL, data=body, method="POST",
                                 headers={"Authorization": f"Bearer {LLM_KEY}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
        return data["choices"][0]["message"]["content"].strip()
    except Exception as exc:  # noqa: BLE001
        print(f"[dj] LLM unavailable ({exc}); using template script.")
        return None


def _template_script(persona: str, track: dict, kind: str = "intro",
                     prev: dict | None = None) -> str:
    p = PERSONAS[persona]
    # crc32, not hash(): str hashes change per process, which broke determinism.
    key = f"{persona}|{track.get('title', '')}|{track.get('seed', 0)}|{kind}"
    r = random.Random(zlib.crc32(key.encode()))
    o, m, c = p["opener"], p["mid"], p["closer"]
    title = track.get("title", "this next one")
    genre = track.get("genre", "??")
    bpm = track.get("bpm", "???")
    mood = track.get("mood_label", track.get("mood", 0.5))
    if kind == "intro":
        back = f"That was {prev['title']}. " if prev and prev.get("title") else ""
        return (f"{r.choice(o)} {back}Up next, {title} — {genre}, {bpm} beats per minute, "
                f"with a mood straight out of {mood}. {r.choice(m)} {r.choice(c)}")
    return f"{r.choice(o)} that was the block — {r.choice(m)} {r.choice(c)}"


def _track_facts(t: dict) -> str:
    keys = ("title", "artist", "genre", "bpm", "key", "mood_label", "theme")
    facts = {k: t[k] for k in keys if t.get(k) not in (None, "")}
    facts["vocals"] = bool(t.get("vocals"))
    return json.dumps(facts, ensure_ascii=False)


def script_for(persona: str, track: dict, kind: str = "intro", use_llm: bool = True,
               language: str = "english", prev: dict | None = None) -> str:
    """Write a short DJ script for `track`, bridging from `prev` when given."""
    if use_llm:
        p = PERSONAS[persona]
        bridge = (f"The song that just ended: {_track_facts(prev)}\n"
                  f"Mention both titles: briefly look back on it, then introduce the next one.\n"
                  if prev else "This is the first song of the set.\n")
        prompt = (
            f"You are \"{persona.upper()}\", a {p['vibe']} DJ on a radio station.\n"
            f"{bridge}The next song: {_track_facts(track)}\n"
            f"Speak exactly like your persona. 30-60 words of plain spoken speech — no emojis, "
            f"hashtags, or stage directions. Only use the facts above: do not invent artists, "
            f"dates, chart positions, places, or listener names, and do not read out numbers "
            f"like seeds. End with ONE short punchy line. Write in {language}. "
            f"Only output the spoken words."
        )
        s = _llm(prompt, max_tokens=180)
        if s and len(s) > 12:
            return s[:700]
    return _template_script(persona, track, kind, prev)


def synth_voice(persona: str, text: str, out_base: str, rate: int | None = None,
                ref: bytes | None = None) -> str | None:
    """Speak `text` to out_base + .wav/.mp3. Chatterbox first (cloned voice if
    `ref` is given), macOS `say` as offline fallback. Returns the file path
    written, or None if every engine failed."""
    path = _chatterbox(text, out_base, ref)
    if path:
        return path
    wav = out_base + ".wav"
    if _say(text, VOICE_OVERRIDES.get(persona, PERSONAS[persona]["voice"]), wav, rate):
        return wav
    return None


def pick_persona(genre: str, rng: random.Random) -> str:
    if genre in ("lofi", "ambient"):
        return rng.choice(["lana", "moon"])
    if genre == "techno":
        return "nova"
    if genre == "synthwave":
        return rng.choice(["nova", "rex"])
    if genre == "chiptune":
        return rng.choice(["vox", "nova"])
    return "rex"


def station_id(text: str, persona: str, out_base: str, ref: bytes | None = None) -> str | None:
    return synth_voice(persona, text, out_base, ref=ref)

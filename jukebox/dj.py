"""AI Jukebox — DJ commentary: script writer (LLM-first, template fallback)
and TTS voice actor via macOS `say` + `afconvert` (zero extra deps).
"""
from __future__ import annotations
import json, os, random, subprocess, tempfile

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


def _template_script(persona: str, track: dict, kind: str = "intro") -> str:
    p = PERSONAS[persona]
    r = random.Random(hash((persona, track.get("title", ""), track.get("seed", 0), kind)) & 0xffffffff)
    o, m, c = p["opener"], p["mid"], p["closer"]
    title = track.get("title", "this next one")
    genre = track.get("genre", "??")
    bpm = track.get("bpm", "???")
    mood = track.get("mood_label", track.get("mood", 0.5))
    seed = track.get("seed", 0)
    if kind == "intro":
        return (f"{r.choice(o)} up next, {title} — {genre}, {bpm} beats per minute, now "
                f"with a mood straight out of {mood}. {r.choice(m)} Seed {seed}, "
                f"fresh off the generative floor. {r.choice(c)}")
    return f"{r.choice(o)} that was the block — {r.choice(m)} {r.choice(c)}"


def script_for(persona: str, track: dict, kind: str = "intro", use_llm: bool = True,
               language: str = "english") -> str:
    """Write a short DJ script for a track. Returns (voice, script)."""
    if use_llm:
        p = PERSONAS[persona]
        t = track
        prompt = (
            f"You are \"{persona.upper()}\", a {p['vibe']} AI DJ on an infinite jukebox. "
            f"Write a SHORT spoken intro for the next track. Track: \"{t.get('title')}\" — "
            f"{t.get('genre')} at {t.get('bpm')} bpm, key {t.get('key_name', '?')}, "
            f"mood {t.get('mood_label', '?')}, seed {t.get('seed')}. "
            f"Speak exactly like your persona ({p['vibe']}). 35-60 words, plain spoken speech only — "
            f"no emojis, no hashtags, no 'hey y'all' if you wouldn't. Do not mention 'AI LLM'. "
            f"End with ONE short punchy line. Write in {language}. Only output the spoken words."
        )
        s = _llm(prompt, max_tokens=180)
        if s and len(s) > 12:
            return s[:700]
    return _template_script(persona, track, kind)


def synth_voice(persona: str, text: str, out_wav: str, rate: int | None = None) -> bool:
    return _say(text, VOICE_OVERRIDES.get(persona, PERSONAS[persona]["voice"]), out_wav, rate)


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


def station_id(text: str, persona: str, out_wav: str) -> bool:
    return _say(text, PERSONAS[persona]["voice"], out_wav)

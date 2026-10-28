#!/usr/bin/env python3
"""Standalone probe for the AI DJ class services (Qwen 9001, Chatterbox 9008,
optional Whisper 9009). Measures latency, saves the audio it gets back, and
records what the services do with bad voice-reference files.

Stdlib only — no pip installs. Independent of the app's own code, so it keeps
working whatever structure the Hermes build ends up with.

    python3 tools/dj_probe.py schema                 # list Chatterbox endpoints + fields
    python3 tools/dj_probe.py script                 # Qwen DJ scripts (prev/next aware)
    python3 tools/dj_probe.py tts --transcribe       # default voice, 3 script lengths
    python3 tools/dj_probe.py clone --ref ~/me.wav   # cloned voice (base64 + multipart)
    python3 tools/dj_probe.py badfiles               # empty / fake / oversize refs
    python3 tools/dj_probe.py all --ref ~/me.wav

Credentials: CLASS_API_KEY (or JUKEBOX_LLM_KEY) from the environment, or a
.env file passed with --env (default: jukebox/.env). The key is never printed.
Output goes to --out (default: dj_probe_out/, gitignored): audio files plus
results.jsonl, one JSON line per request — paste these into the README tests.
"""
from __future__ import annotations

import argparse
import base64
import difflib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

HOST = "http://dobolyi.com"
QWEN_URL = f"{HOST}:9001/v1/chat/completions"
QWEN_MODEL = "cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit"
TTS_URL = f"{HOST}:9008"
TTS_MODEL = "chatterbox-v3"
STT_URL = f"{HOST}:9009/v1/audio/transcriptions"
STT_MODEL = "openai/whisper-large-v3-turbo"

# Fictional queue used for the script tests — no real songs or artists.
QUEUE = [
    dict(title="Neon Tide", genre="synthwave", mood="nostalgic", vocal=True,
         theme="driving along the coast at night"),
    dict(title="Paper Lanterns", genre="lo-fi", mood="calm", vocal=False,
         theme="rainy afternoon study session"),
    dict(title="Iron Sunrise", genre="rock", mood="energetic", vocal=True,
         theme="starting over after a hard year"),
]

SCRIPTS = {
    "short": "That was Neon Tide. Up next, something calmer: Paper Lanterns.",
    "medium": ("You just heard Neon Tide, a nostalgic synthwave drive down the coast. "
               "Let's slow it down now. Here is Paper Lanterns, a calm lo-fi track "
               "made for a rainy afternoon with your books open."),
    "long": ("What a ride. Neon Tide took us down the coastline at midnight, all "
             "shimmering synths and late-night memories. Now we trade the open road "
             "for a quiet window seat. Paper Lanterns is pure lo-fi calm: soft keys, "
             "gentle rain, and nowhere you need to be. Get comfortable, take a breath, "
             "and let this one carry you through the afternoon."),
}


# ---------------------------------------------------------------- plumbing

def load_key(env_path: Path) -> str:
    for name in ("CLASS_API_KEY", "JUKEBOX_LLM_KEY"):
        if os.environ.get(name):
            return os.environ[name]
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            m = re.match(r"\s*(CLASS_API_KEY|JUKEBOX_LLM_KEY)\s*=\s*(.+)", line)
            if m:
                return m.group(2).strip().strip("'\"")
    sys.exit(f"No API key: set CLASS_API_KEY or add it to {env_path} (never commit it).")


class Probe:
    def __init__(self, key: str, out: Path, timeout: int):
        self.key, self.out, self.timeout = key, out, timeout
        out.mkdir(parents=True, exist_ok=True)
        self.log = out / "results.jsonl"

    def record(self, **row) -> dict:
        row["at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with self.log.open("a") as f:
            f.write(json.dumps(row) + "\n")
        status = row.get("status")
        secs = row.get("seconds")
        print(f"  [{status}] {row['test']:<28} {secs if secs is not None else '-':>6}s  "
              f"{row.get('note', '')}")
        return row

    def request(self, url: str, data: bytes | None = None,
                content_type: str = "application/json") -> tuple[int, bytes, float, str]:
        """Returns (http_status, body, seconds, content_type). Never raises on HTTP errors."""
        headers = {"Authorization": f"Bearer {self.key}"}
        if data is not None:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(url, data=data, headers=headers,
                                     method="POST" if data is not None else "GET")
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                body, status, ctype = r.read(), r.status, r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            body, status, ctype = e.read(), e.code, e.headers.get("Content-Type", "")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return 0, str(e).encode(), round(time.perf_counter() - t0, 2), "error"
        return status, body, round(time.perf_counter() - t0, 2), ctype

    def post_json(self, url: str, payload: dict):
        return self.request(url, json.dumps(payload).encode())

    def post_multipart(self, url: str, fields: dict[str, str],
                       files: dict[str, tuple[str, bytes, str]]):
        boundary = uuid.uuid4().hex
        parts: list[bytes] = []
        for name, value in fields.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'
                         f"\r\n\r\n{value}\r\n".encode())
        for name, (filename, blob, ctype) in files.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
                         f'filename="{filename}"\r\nContent-Type: {ctype}\r\n\r\n'.encode()
                         + blob + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        return self.request(url, b"".join(parts), f"multipart/form-data; boundary={boundary}")


def short_error(body: bytes) -> str:
    text = body.decode(errors="replace").strip().replace("\n", " ")
    return text[:200]


def is_audio(body: bytes, ctype: str) -> bool:
    return ctype.startswith("audio/") or body[:3] == b"ID3" or body[:4] in (b"RIFF", b"\xff\xfb")


def save_audio(p: Probe, name: str, body: bytes, ctype: str) -> Path:
    ext = ".wav" if ("wav" in ctype or body[:4] == b"RIFF") else ".mp3"
    path = p.out / f"{name}{ext}"
    path.write_bytes(body)
    return path


def audio_seconds(body: bytes) -> float | None:
    """Duration for WAV (exact) or MP3 (rough CBR estimate from the first frame)."""
    if body[:4] == b"RIFF" and len(body) > 44:
        byte_rate = int.from_bytes(body[28:32], "little")
        return round((len(body) - 44) / byte_rate, 2) if byte_rate else None
    i = 10 + int.from_bytes(body[6:10], "big") if body[:3] == b"ID3" else 0  # skip ID3 (approx)
    while i < len(body) - 4 and not (body[i] == 0xFF and body[i + 1] & 0xE0 == 0xE0):
        i += 1
    if i >= len(body) - 4:
        return None
    rates = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
    kbps = rates[body[i + 2] >> 4]
    return round((len(body) - i) * 8 / (kbps * 1000), 2) if kbps else None


def similarity(a: str, b: str) -> float:
    norm = lambda s: re.sub(r"[^a-z0-9 ]", "", s.lower()).split()
    return round(difflib.SequenceMatcher(None, norm(a), norm(b)).ratio(), 3)


# ---------------------------------------------------------------- tests

def cmd_schema(p: Probe, _args) -> None:
    status, body, secs, _ = p.request(f"{TTS_URL}/openapi.json")
    if status != 200:
        p.record(test="schema", status=status, seconds=secs, note=short_error(body))
        return
    spec = json.loads(body)
    (p.out / "chatterbox-openapi.json").write_bytes(body)
    comps = spec.get("components", {}).get("schemas", {})

    def fields(op: dict) -> str:
        for ctype, media in op.get("requestBody", {}).get("content", {}).items():
            ref = media.get("schema", {}).get("$ref", "")
            props = comps.get(ref.split("/")[-1], {}).get("properties", {}) or \
                media.get("schema", {}).get("properties", {})
            return f"{ctype}: {', '.join(props) or '?'}"
        return ""

    print(f"Chatterbox endpoints (full spec saved to {p.out / 'chatterbox-openapi.json'}):")
    for path, ops in spec.get("paths", {}).items():
        for method, op in ops.items():
            print(f"  {method.upper():6} {path:32} {fields(op)}")
    p.record(test="schema", status=status, seconds=secs, note=f"{len(spec.get('paths', {}))} paths")


def cmd_script(p: Probe, _args) -> None:
    """Qwen DJ transitions that must reference both the previous and next track."""
    for i in range(len(QUEUE) - 1):
        prev, nxt = QUEUE[i], QUEUE[i + 1]
        prompt = (
            "You are the DJ of an AI radio station. Write what you say between two songs.\n"
            f"Previous song: {json.dumps(prev)}\nNext song: {json.dumps(nxt)}\n"
            "Rules: 30-50 words. Mention both titles. Only use facts given above; do not "
            "invent artists, dates, chart positions, or listener names. Plain spoken English, "
            "no emojis, no stage directions. Output only the words to speak."
        )
        status, body, secs, _ = p.post_json(QWEN_URL, {
            "model": QWEN_MODEL, "max_tokens": 200, "temperature": 0.8,
            "messages": [{"role": "user", "content": prompt}],
            "chat_template_kwargs": {"enable_thinking": False},
        })
        name = f"script {prev['title']} -> {nxt['title']}"
        if status != 200:
            p.record(test=name, status=status, seconds=secs, note=short_error(body))
            continue
        text = json.loads(body)["choices"][0]["message"]["content"].strip()
        both = prev["title"].lower() in text.lower() and nxt["title"].lower() in text.lower()
        p.record(test=name, status=status, seconds=secs, words=len(text.split()),
                 mentions_both=both, text=text,
                 note=f"{len(text.split())} words, mentions both: {both}")


def speak(p: Probe, name: str, text: str, transcribe: bool, extra: dict | None = None) -> None:
    payload = {"model": TTS_MODEL, "input": text, "language_id": "en", **(extra or {})}
    status, body, secs, ctype = p.post_json(f"{TTS_URL}/v1/audio/speech", payload)
    finish_tts(p, name, text, status, body, secs, ctype, transcribe)


def finish_tts(p, name, text, status, body, secs, ctype, transcribe) -> None:
    if status != 200 or not is_audio(body, ctype):
        p.record(test=name, status=status, seconds=secs, note=short_error(body))
        return
    path = save_audio(p, name.replace(" ", "_"), body, ctype)
    dur = audio_seconds(body)
    row = dict(test=name, status=status, seconds=secs, audio_seconds=dur,
               bytes=len(body), words=len(text.split()), file=str(path),
               realtime_factor=round(secs / dur, 2) if dur else None,
               note=f"{dur}s audio, gen/audio = {round(secs / dur, 2) if dur else '?'}")
    if transcribe:
        st, tb, ts, _ = p.post_multipart(STT_URL, {"model": STT_MODEL},
                                         {"file": (path.name, body, ctype or "audio/mpeg")})
        if st == 200:
            heard = json.loads(tb).get("text", "")
            row.update(transcript=heard, transcript_match=similarity(text, heard))
            row["note"] += f", whisper match {row['transcript_match']}"
        else:
            row["note"] += f", whisper failed [{st}]"
    p.record(**row)


def cmd_tts(p: Probe, args) -> None:
    for label, text in SCRIPTS.items():
        speak(p, f"tts default {label}", text, args.transcribe)


def cmd_clone(p: Probe, args) -> None:
    if not args.ref:
        sys.exit("clone needs --ref <your own short MP3/WAV recording>")
    ref = Path(args.ref).expanduser().resolve()
    repo = Path(__file__).resolve().parents[1]
    if repo in ref.parents:
        print(f"WARNING: {ref} is inside the repo — keep voice recordings outside it.")
    blob = ref.read_bytes()
    ctype = "audio/wav" if ref.suffix.lower() == ".wav" else "audio/mpeg"
    text = SCRIPTS["medium"]
    speak(p, "clone base64", text, args.transcribe,
          {"ref_audio": base64.b64encode(blob).decode()})
    status, body, secs, rctype = p.post_multipart(
        f"{TTS_URL}/v1/audio/speech/upload",
        {"model": TTS_MODEL, "input": text, "language_id": "en"},
        {args.upload_field: (ref.name, blob, ctype)})
    finish_tts(p, "clone multipart", text, status, body, secs, rctype, args.transcribe)


def cmd_badfiles(p: Probe, args) -> None:
    """What does the service do with refs the app should reject itself?"""
    cases = {
        "bad empty.mp3": (b"", "audio/mpeg"),
        "bad text-as.mp3": (b"this is not audio at all\n" * 40, "audio/mpeg"),
        "bad text.txt": (b"plain text file\n" * 40, "text/plain"),
        "bad truncated.wav": (b"RIFF\x24\x00\x00\x00WAVEfmt ", "audio/wav"),
        f"bad oversize-{args.big_mb}mb.mp3": (os.urandom(args.big_mb * 1024 * 1024), "audio/mpeg"),
    }
    for name, (blob, ctype) in cases.items():
        filename = name.split(" ", 1)[1]
        status, body, secs, rctype = p.post_multipart(
            f"{TTS_URL}/v1/audio/speech/upload",
            {"model": TTS_MODEL, "input": SCRIPTS["short"], "language_id": "en"},
            {args.upload_field: (filename, blob, ctype)})
        accepted = status == 200 and is_audio(body, rctype)
        p.record(test=name, status=status, seconds=secs, accepted=accepted,
                 note=("ACCEPTED (app must validate this itself)" if accepted
                       else short_error(body)))


def cmd_all(p: Probe, args) -> None:
    cmd_schema(p, args)
    cmd_script(p, args)
    cmd_tts(p, args)
    if args.ref:
        cmd_clone(p, args)
    cmd_badfiles(p, args)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("command", choices=["schema", "script", "tts", "clone", "badfiles", "all"])
    ap.add_argument("--ref", help="your own voice recording (MP3/WAV), kept outside the repo")
    ap.add_argument("--env", default="jukebox/.env", help="dotenv file holding the class key")
    ap.add_argument("--out", default="dj_probe_out", help="output folder (gitignored)")
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--transcribe", action="store_true",
                    help="check each clip with Whisper (9009) against its script")
    ap.add_argument("--upload-field", default="file",
                    help="multipart field name for the reference file (see `schema`)")
    ap.add_argument("--big-mb", type=int, default=25, help="size of the oversize test file")
    args = ap.parse_args()
    probe = Probe(load_key(Path(args.env)), Path(args.out), args.timeout)
    print(f"Results -> {probe.log}")
    globals()[f"cmd_{args.command}"](probe, args)


if __name__ == "__main__":
    main()

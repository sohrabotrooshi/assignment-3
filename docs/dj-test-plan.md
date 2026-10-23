# AI DJ — test plan and README draft

Owner: Junkyu (junqlee22) · Reviewer: Donovan

Scope: core feature 3, "Integrated AI DJ" — song-specific commentary written by
Qwen (port 9001) and spoken by Chatterbox (port 9008) between queued songs,
with the default voice or an uploaded MP3/WAV reference.

Status key: ✅ passed · ❌ failed · ⬜ not run yet. Only mark a row ✅ after
running it; the assignment asks us to separate completed tests from unchecked
claims.

## 1. Requirements we add to the Hermes build prompt

Proposed additions for the DJ part of the starter prompt (the starter's
existing language stays as is):

```
# AI DJ details
- Each DJ segment is written by Qwen on port 9001 from the actual metadata of the
  song that just played and the song that plays next (title, style, mood,
  vocal/instrumental, theme, lyrics excerpt if any). It must mention both titles
  and must not invent artists, dates, chart positions, listener names, or
  facts that are not in that metadata. Keep it 25-60 words of plain spoken text.
- DJ speech uses Chatterbox on port 9008: POST /v1/audio/speech with model
  "chatterbox-v3". Use the built-in default voice unless the user uploaded a
  reference. Custom voice: accept only .mp3/.wav up to 10 MB and 5-30 seconds,
  validate type, size, and that the file actually decodes before sending it, and
  show a clear error for anything else.
- Save uploaded voice references only in a server-side folder listed in
  .gitignore (e.g. uploads/voices/). Never commit them, never include them in
  the submission ZIP, never expose their path or contents to browser code.
- Generate the next DJ segment in the background while the current song plays,
  so there is no long silence between tracks. If DJ generation fails or takes
  longer than about 20 seconds, skip the segment and start the next song; the
  queue must never stall on the DJ. Show DJ status in the UI.
- DJ audio and song audio never overlap. Skipping during DJ speech stops the
  speech and starts the next song.
```

## 2. Service probe (no app needed)

`tools/dj_probe.py` calls the class services directly and logs every request to
`dj_probe_out/results.jsonl` (gitignored). Run from the repo root with the class
key in `jukebox/.env` as `CLASS_API_KEY=...`, or exported in the shell:

```bash
python3 tools/dj_probe.py schema                     # real Chatterbox fields
python3 tools/dj_probe.py all --ref ~/voice-test/me.wav --transcribe
```

Keep the reference recording outside the repo folder. If `schema` shows the
upload field is not called `file`, rerun with `--upload-field <name>`.

| ID | Probe | Measures | Result |
|---|---|---|---|
| P1 | `schema` | Upload field names, limits documented by the server | ⬜ |
| P2 | `script` | Qwen latency; does it mention both titles? | ⬜ |
| P3 | `tts --transcribe` | Default voice latency vs. script length (short/medium/long); Whisper match | ⬜ |
| P4 | `clone --ref` | Cloned-voice latency, base64 vs. multipart; Whisper match | ⬜ |
| P5 | `badfiles` | What the server does with empty, fake, truncated, text, and 25 MB files | ⬜ |

P3/P4 timings are the evidence for the DJ design-judgment item (how long the
DJ takes and whether pre-generating the next segment is necessary).

## 3. App tests (run on the Hermes build)

Fill in **Actual** with what really happened, including timings and the exact
error text shown.

### Commentary quality

| ID | Input | Expected | Actual | Status |
|---|---|---|---|---|
| D1 | Queue: vocal song → instrumental song, default voice | DJ names the song that ended and the next one; facts match their metadata | | ⬜ |
| D2 | Same queue played twice | Wording differs or stays fixed per our design, but is never copy-paste across different songs | | ⬜ |
| D3 | 4+ songs, listen to every DJ segment | No repeated phrases segment to segment; no invented artists, dates, or listener names | | ⬜ |
| D4 | Song with AI lyrics | DJ may reference the theme/lyrics; no quoting of lyrics that are not in the song | | ⬜ |

### Voice

| ID | Input | Expected | Actual | Status |
|---|---|---|---|---|
| V1 | No upload | Built-in Chatterbox default voice is used | | ⬜ |
| V2 | Upload own 10 s WAV | DJ speaks in a voice resembling the reference | | ⬜ |
| V3 | Upload own 10 s MP3 | Same as V2 | | ⬜ |
| V4 | Upload `.txt` renamed to `.mp3` | Rejected with a clear message; default voice still works | | ⬜ |
| V5 | Upload 0-byte file | Rejected with a clear message | | ⬜ |
| V6 | Upload file over the size limit | Rejected before upload completes, clear message | | ⬜ |
| V7 | Upload `.ogg` / `.m4a` | Rejected: only MP3/WAV accepted | | ⬜ |
| V8 | Remove custom voice | Falls back to default voice | | ⬜ |

### Timing and queue

| ID | Input | Expected | Actual | Status |
|---|---|---|---|---|
| T1 | Song ends, next DJ segment | Gap between song end and DJ start (seconds) | | ⬜ |
| T2 | DJ ends, next song | Gap between DJ end and song start (seconds) | | ⬜ |
| T3 | Stop Chatterbox / wrong port in `.env` | Error shown, DJ skipped, next song still plays | | ⬜ |
| T4 | Stop Qwen / wrong key | Error or fallback shown, queue keeps going | | ⬜ |
| T5 | Skip while DJ is talking | Speech stops, next song starts, no overlap | | ⬜ |

### Upload safety

| ID | Check | Expected | Actual | Status |
|---|---|---|---|---|
| S1 | After V2/V3, `git status` | Uploaded file is not listed (folder is gitignored) | | ⬜ |
| S2 | Download ZIP from GitHub, search for audio from uploads | No voice references in the ZIP | | ⬜ |
| S3 | Browser dev tools → Network/Sources | No API key, no server path to uploads | | ⬜ |

## 4. README section draft — "AI DJ"

> Fill the bracketed parts from the tests above; rewrite in our own words.

**How it works.** After each song, the app sends the finished song's and the
next song's metadata to Qwen (port 9001), which writes a short transition.
Chatterbox (port 9008) turns it into speech. [Describe when generation happens —
e.g. in the background during the current song.]

**Using the default voice.** [Steps.]

**Using your own voice.** [Where to upload, accepted formats and limits, what
happens on errors.] Uploaded references are stored only in `[folder]`, which is
gitignored and excluded from the submission ZIP.

**Test results.** [Summarize D/V/T/S tables, including at least one failure
case, and list anything still unresolved.]

**Timing.** [P3/P4 and T1/T2 numbers.]

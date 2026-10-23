# AI Jukebox

A generative music jukebox: original songs composed on the fly, generative
cover art for every track, and AI-spoken DJ commentary between tracks.

**Stack:** pure-Python (numpy) synthesis engine · macOS `say` voices · SVG art ·
single-file HTML player. No API keys required to run; the DJ scripts and lyrics
can optionally be upgraded to the Qwen LLM endpoint with `--llm`.

## Quick start

```bash
# from this folder
.venv/bin/python generate.py demo          # build the two demo setlists
open player.html                            # or: generate.py serve → http://localhost:8777/player.html
```

The player auto-advances: station ID → DJ intro → song → DJ intro → song …,
spin-visualizer, lyrics, downloads, keyboard shortcuts (space, ←/→, ↑/↓).

## The three parts

| Part | How | Customization |
|---|---|---|
| Songs | `engine.py` — seeded procedural composition (harmonic synthesis, melodic motifs, synthesized drums, FFT reverb, sidechain, vinyl noise) | genre, bpm, key-root, scale (major/minor/dorian/phrygian/lydian/mixolydian/pent_minor), mood 0–1, length, seed, optional robotic vocoder vocals (`--vocals`) |
| Cover art | `art.py` — seeded SVG per style family (synthwave grid, lofi room, geometric, pixel, landscape, aurora, rings, glitch) | hue follows genre, brightness follows mood, layout from seed; `--style` overrides, `--png` rasterizes via qlmanage |
| DJ booth | `dj.py` — scripts (template, or LLM with `--llm`) + macOS `say` voices | personas: `nova` (club), `lana` (chill), `rex` (radio), `vox` (robot), `moon` (whisper); auto-matched to genre |

Genres: `lofi`, `synthwave`, `techno`, `chiptune`, `cinematic`, `ambient`.

## Recipes

```bash
# one song with everything tuned
.venv/bin/python generate.py song --genre synthwave --seed 7 --bpm 104 \
    --key-note 57 --scale dorian --mood 0.8 --length long --vocals --llm

# a themed setlist with DJ commentary
.venv/bin/python generate.py setlist --name "Rainy Study Hour" \
    --theme "rain on glass, warm lamps" --genres lofi,ambient --count 6 \
    --seed 20261023 --llm

# one DJ clip / one cover
.venv/bin/python generate.py dj --title "Neon Rain" --genre synthwave \
    --persona nova --llm
.venv/bin/python generate.py art --genre techno --title "Iron Pulse" \
    --seed 99 --png

# rebuild a setlist from scratch
.venv/bin/python generate.py setlist --name "Synthwave Sunday" --genres synthwave,techno --count 5 --force --llm

.venv/bin/python generate.py list       # what's in the library
.venv/bin/python generate.py serve      # http://localhost:8777/player.html
```

Seeds make every run reproducible: same seed + params ⇒ identical song.

## Library layout

```
library/
  index.js                  setlist picker (regenerated each build)
  synthwave-sunday/
    playlist.js             what player.html loads
    setlist.json            same data, human-readable
    song_01/  song.wav song.mp3 cover.svg lyrics.txt info.json [vox.wav]
    dj_00.wav               station ID (+ .txt transcript)
    dj_01.wav …             intros before each track
```

`player.html?set=synthwave-sunday` jumps straight to a setlist.

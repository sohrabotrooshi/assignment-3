"""AI Jukebox — procedural music engine (numpy only).

Composes original songs from a seed: genre, key/scale, tempo, mood, structure,
instrumentation. Renders stereo WAV via additive harmonic synthesis, seeded
melodic motifs, synthesized drums, FFT reverb, sidechain pumping, vinyl noise.
"""
from __future__ import annotations
import json, wave
import numpy as np

SR = 44100

# ---------------------------------------------------------------- theory ----
SCALES = {
    "major":     [0, 2, 4, 5, 7, 9, 11],
    "minor":     [0, 2, 3, 5, 7, 8, 10],
    "dorian":    [0, 2, 3, 5, 7, 9, 10],
    "phrygian":  [0, 1, 3, 5, 7, 8, 10],
    "lydian":    [0, 2, 4, 6, 7, 9, 11],
    "mixolydian":[0, 2, 4, 5, 7, 9, 10],
    "pent_minor":[0, 3, 5, 7, 10],
}

# degree lists -> (root_offset, quality) triads built on the scale.
# qualities: maj, min, dim, sus4(2sus), 7, maj7, min7
CHORD_QUAL = {"major": ["maj7", "min7", "min7", "maj7", "7", "min7", "m7b5"],
              "minor": ["min7", "m7b5", "maj7", "min7", "min7", "maj7", "7"],
              "dorian": ["min7", "min7", "maj7", "7", "min7", "m7b5", "maj7"],
              "phrygian": ["min7", "maj7", "maj7", "min7", "m7b5", "maj7", "min7"],
              "lydian": ["maj7", "7", "min7", "m7b5", "maj7", "min7", "min7"],
              "mixolydian": ["7", "min7", "min7", "maj7", "7", "min7", "m7b5"],
              "pent_minor": ["min7", "min7", "maj7", "min7", "min7", "maj7", "7"]}

# chord quality -> semitone offsets over a triad
CHORD_INTERVALS = {"maj": [0, 4, 7], "min": [0, 3, 7], "dim": [0, 3, 6],
                   "sus4": [0, 5, 7], "maj7": [0, 4, 7, 11], "min7": [0, 3, 7, 10],
                   "7": [0, 4, 7, 10], "m7b5": [0, 3, 6, 10]}

PROGRESSIONS = {
    "lofi":      [[0, 5, 3, 4], [4, 1, 5, 3], [5, 3, 0, 4], [2, 5, 1, 1]],
    "synthwave": [[0, 5, 3, 6], [0, 5, 6, 6], [3, 5, 0, 6], [4, 3, 0, 5]],
    "techno":    [[0, 0, 5, 0], [0, 0, 5, 5], [0, 3, 5, 3]],
    "chiptune":  [[0, 4, 5, 3], [5, 3, 0, 4], [4, 0, 5, 0]],
    "cinematic": [[0, 5, 3, 4], [0, 4, 5, 5], [3, 4, 0, 5]],
    "ambient":   [[0, 3, 5, 0], [0, 5, 3, 3], [5, 4, 0, 0]],
}

# ---------------------------------------------------------------- genres ----
GENRES = {
    "lofi":      dict(bpm=(70, 86), swing=0.18, keys="minor", pads=False, keys_on=True,
                      pluck=False, arp_vel=0.0, acid=False, vinyl=True,
                      drums="boom-bap", bass="sub", sidechain=0.0,
                      lead="keys", mood="warm, dusty, rainy-window"),
    "synthwave": dict(bpm=(100, 112), swing=0.06, keys="minor", pads=True, keys_on=False,
                      pluck=False, arp_vel=1.0, acid=False, vinyl=False,
                      drums="four", bass="octave", sidechain=0.55,
                      lead="lead", mood="neon, night-drive, chrome"),
    "techno":    dict(bpm=(126, 134), swing=0.0, keys="minor", pads=False, keys_on=False,
                      pluck=False, arp_vel=0.6, acid=True, vinyl=False,
                      drums="techno", bass="acid", sidechain=0.7,
                      lead="stab", mood="warehouse, relentless, strobe"),
    "chiptune":  dict(bpm=(138, 162), swing=0.05, keys="major", pads=False, keys_on=True,
                      pluck=False, arp_vel=1.0, acid=False, vinyl=False,
                      drums="chiptune", bass="square", sidechain=0.0,
                      lead="square", mood="arcade, candy, turbo"),
    "cinematic": dict(bpm=(68, 80), swing=0.0, keys="minor", pads=True, keys_on=False,
                      pluck=True, arp_vel=0.2, acid=False, vinyl=False,
                      drums="taiko", bass="sub", sidechain=0.0,
                      lead="string", mood="epic, mountain, storm"),
    "ambient":   dict(bpm=(54, 66), swing=0.0, keys="major", pads=True, keys_on=False,
                      pluck=True, arp_vel=0.25, acid=False, vinyl=False,
                      drums="none", bass="pad", sidechain=0.0,
                      lead="bell", mood="weightless, fog, dusk"),
}

# ------------------------------------------------------------- synthesis ----
def note_freq(midi: float) -> float:
    return 440.0 * 2.0 ** ((midi - 69) / 12.0)


def env_adsr(n: int, sr: int, atk: float, dec: float, sus: float, rel: float,
             shape: str = "lin") -> np.ndarray:
    """Exponential-ish ADSR envelope of length n."""
    a, d, r = max(1, int(atk * sr)), max(1, int(dec * sr)), max(1, int(rel * sr))
    e = np.zeros(n)
    if a + d + r > n:
        scale = n / (a + d + r) if (a + d + r) else 1
        a, d, r = max(1, int(a * scale)), max(1, int(d * scale)), max(1, int(r * scale))
        if a + d + r > n:
            r = max(1, n - a - d)
    le = np.arange(n) / sr
    e[:a] = (np.arange(a) / a) ** 0.7
    sd = min(d, n - a)
    e[a:a + sd] = 1 + (sus - 1) * (np.arange(sd) / sd) ** (1.4 if shape == "lin" else 2.0)
    tail = n - a - sd
    if tail > 0:
        e[a + sd:] = sus * (1 - np.arange(tail) / tail) ** 0.9
    return e


_HARM_CFG = {   # harmonic rolloff exponent / harmonic count per voice
    "pluck":  dict(roll=2.2, h=8), "keys": dict(roll=3.2, h=8),
    "pad":    dict(roll=1.6, h=12), "lead": dict(roll=1.35, h=14),
    "stab":   dict(roll=1.15, h=16), "string": dict(roll=1.7, h=12),
    "bell":   dict(roll=2.6, h=6, inharm=1.09), "square": dict(roll=0.0, h=9, sq=True),
    "sub":    dict(roll=4.0, h=4), "acid": dict(roll=1.1, h=18, acid=True),
    "divide": dict(roll=1.0, h=8),
}


def synth_note(freq: float, dur: float, kind: str, sr: int, rng: np.random.Generator,
               vel: float = 1.0) -> np.ndarray:
    """One synthesized note (mono). freq Hz, dur seconds."""
    if freq <= 20 or dur <= 0.015:
        return np.zeros(max(1, int(dur * sr)))
    cfg = _HARM_CFG.get(kind, dict(roll=2.0, h=10))
    n = max(1, int(dur * sr))
    t = np.arange(n) / sr
    out = np.zeros(n)

    # detuned voice stack
    det = {"pad": 0.0045, "string": 0.0032, "lead": 0.0012, "keys": 0.0010,
           "pluck": 0.0015, "stab": 0.0018, "square": 0.0, "bell": 0.0,
           "sub": 0.0, "acid": 0.0, "divide": 0.0}.get(kind, 0.001)
    voices = 2 if det else 1
    if kind in ("pad", "string"):
        voices = 4

    for v in range(voices):
        f = freq * (1 + det * (v - (voices - 1) / 2) * 2 + rng.uniform(-det, det) * 0.5)
        if kind == "bell":  # inharmonic partials
            f = freq * (1 + 0.0015 * v)
        harm_freqs = np.array([f * k * (1 + cfg.get("inharm", 0) * (k - 1)) if kind == "bell"
                               else f * k for k in range(1, cfg["h"] + 1)])
        roll = cfg["roll"]
        if cfg.get("sq"):  # square-ish: odd partials only
            harm_freqs = harm_freqs[0::2]
            amps = 1.0 / (2 * np.arange(1, len(harm_freqs) + 1) - 1)
        else:
            amps = 1.0 / (np.arange(1, len(harm_freqs) + 1) ** roll)
        if cfg.get("acid"):  # resonant band emphasis near ~0.5-2.5kHz
            fc = 620
            w = 1.0 / (1.0 + ((harm_freqs / fc - 1.0) / 0.9) ** 4)
            amps *= 0.35 + 2.6 * w
        if kind == "bell":
            amps *= np.exp(-np.arange(len(amps)) * 0.28) * 0.55
        if kind == "sub":
            amps[0] *= 1.0
        # random static phases per note per voice -> rich, non-metallic
        ph = rng.uniform(0, 2 * np.pi, len(harm_freqs))
        sig = np.zeros(n)
        for hf, a, p in zip(harm_freqs, amps, ph):
            sig += a * np.sin(2 * np.pi * hf * t + p)
        out += (sig / max(1, len(harm_freqs) ** 0.4)) * np.hypot(1, 1)

    # envelopes
    if kind in ("pad", "string"):
        e = env_adsr(n, sr, 0.9 * min(3.0, dur / 2), 0.25, 0.85, 0.8)
    elif kind in ("pluck", "keys", "bell"):
        e = env_adsr(n, sr, 0.008, 0.30 * min(2.5, dur), 0.25, 0.22, shape="exp")
    elif kind in ("stab", "square"):
        e = env_adsr(n, sr, 0.006, 0.10 * min(1.5, dur), 0.4, 0.10)
    elif kind == "acid":
        e = env_adsr(n, sr, 0.012, 0.16 * min(1.2, dur), 0.6, 0.08)
    elif kind == "sub":
        e = env_adsr(n, sr, 0.02, 0.2, 0.95, 0.15)
    else:
        e = env_adsr(n, sr, 0.02, 0.25, 0.7, 0.3)

    if kind == "lead":  # vibrato on sustained portion
        vib = np.zeros(n)
        start = min(n, int(0.15 * sr))
        vib_t = np.arange(n - start) / sr
        vib[start:] = 1 + 0.006 * np.sin(2 * np.pi * 5.4 * vib_t) * \
            (np.arange(n - start) / max(1, n - start)) ** 1.5
        out *= vib
    out *= e
    return out * vel


# ----------------------------------------------------------------- drums ----
def _noise(n: int, rng: np.random.Generator) -> np.ndarray:
    return rng.standard_normal(n) * 0.5


def kick(sr: int, rng: np.random.Generator, punch: float = 1.0) -> np.ndarray:
    n = int(0.42 * sr)
    t = np.arange(n) / sr
    f = 125 * np.exp(-t * 26) + 48 * np.exp(-t * 9)
    phase = 2 * np.pi * np.cumsum(f) / sr
    body = np.sin(phase)
    click = _noise(int(0.004 * sr), rng) * np.linspace(1, 0, int(0.004 * sr))
    e = np.exp(-t * 5.2)
    out = np.zeros(n)
    out[:len(click)] += click
    out += body * e * punch
    return out


def snare(sr: int, rng: np.random.Generator, bright: float = 1.0, body: float = 1.0) -> np.ndarray:
    n = int(0.24 * sr)
    t = np.arange(n) / sr
    noise = _noise(n, rng)
    # band-pass-ish: difference of lowpassed halves (cheap)
    nf = np.fft.rfft(noise)
    fr = np.fft.rfftfreq(n, 1 / sr)
    nf *= 1 / (1 + (fr / 2500) ** 2) - 0.4 / (1 + (fr / 4000) ** 2)
    noise = np.fft.irfft(nf, n)
    ring = np.sin(2 * np.pi * 196 * t) * np.exp(-t * 16) * body
    e = np.exp(-t * 11)
    return (noise * e * 0.8 * bright + ring * 0.6) * 0.9


def hat(sr: int, rng: np.random.Generator, open_: bool = False, vel: float = 1.0) -> np.ndarray:
    n = max(4, int((0.4 if open_ else 0.05) * sr))
    t = np.arange(n) / sr
    noise = _noise(n, rng)
    nf = np.fft.rfft(noise)
    fr = np.fft.rfftfreq(n, 1 / sr)
    nf *= 1 / (1 + (fr / 9000) ** 1.5)
    noise = np.fft.irfft(nf, n)
    e = np.exp(-t / (0.035 if not open_ else 0.13))
    return noise * e * 0.5 * vel


def clap(sr: int, rng: np.random.Generator) -> np.ndarray:
    out = np.zeros(int(0.3 * sr))
    for rep in range(3):
        n = int((0.05 + 0.03 * rep) * sr)
        s = _noise(n, rng) * np.exp(-np.arange(n) / (sr * 0.04))
        band = np.fft.irfft(np.fft.rfft(s) * 1 / (1 + (np.fft.rfftfreq(n, 1 / sr) / 1800) ** 2), n)
        i0 = int((0.01 + 0.028 * rep) * sr)
        out[i0:i0 + n] += band * (0.8 + 0.2 * rep)
    return out * 0.5


def rim(sr: int, rng: np.random.Generator, f=760.0) -> np.ndarray:
    n = int(0.09 * sr)
    t = np.arange(n) / sr
    click = np.zeros(n)
    ni = min(int(0.012 * sr), n)
    click[:ni] = _noise(ni, rng) * 0.1
    return (np.sin(2 * np.pi * f * t) + 0.5 * np.sin(2 * np.pi * f * 1.5 * t)) * \
        np.exp(-t * 60) * 0.5 + click


def tom(sr: int, f=150.0, vel=1.0) -> np.ndarray:
    n = int(0.32 * sr)
    t = np.arange(n) / sr
    fc = f * np.exp(-t * 6) + f * 0.55
    return np.sin(2 * np.pi * np.cumsum(fc) / sr) * np.exp(-t * 7) * 0.85 * vel


def cymbal_swell(sr: int, rng: np.random.Generator, dur: float = 1.6, bright: float = 1.0) -> np.ndarray:
    n = int(dur * sr)
    noise = _noise(n, rng)
    nf = np.fft.rfft(noise)
    fr = np.fft.rfftfreq(n, 1 / sr)
    nf *= 1 / (1 + (fr / 6000) ** 2)
    noise = np.fft.irfft(nf, n)
    e = (np.arange(n) / n) ** 2.2
    return noise * e * 0.3 * bright


def vinyl_crackle(sr: int, dur: float, rng: np.random.Generator, level: float = 0.05) -> np.ndarray:
    n = int(dur * sr)
    t = np.arange(n) / sr
    wn = np.fft.irfft(np.fft.rfft(_noise(n, rng)) / np.sqrt(1 + (np.fft.rfftfreq(n, 1 / sr) / 3200) ** 2) * 3.2, n)
    wn = wn / (np.max(np.abs(wn)) + 1e-9)
    pops = np.zeros(n)
    for _ in range(int(dur * 1.2)):
        i = rng.integers(0, n)
        pops[i:i + 60] += float(0.22 + rng.random() * 0.3) * np.exp(-np.arange(0, 60) / 8) * \
            (rng.random() - 0.5)
    return (wn * 0.35 + pops * 1.4) * level


# ------------------------------------------------------------- composition --
class Song:
    def __init__(self, seed: int, genre: str, bpm: int, key_note: int, scale: str,
                 mood: float, length: str = "medium", title: str = ""):
        self.seed = seed
        self.rng = np.random.default_rng(seed)
        self.genre = genre
        self.g = GENRES[genre]
        self.bpm = bpm
        self.key_note = key_note
        self.scale = scale
        self.mood = mood          # 0..1 (low = calm / high = intense)
        self.title = title
        self.beat = 60 / bpm
        self.bar = self.beat * 4
        self.events: list[dict] = []   # {t, dur, f, kind, vel, pan}

    # ---- structure ---------------------------------------------------------
    def sections(self, length: str) -> list[tuple[str, int, float]]:
        """(name, bars, energy 0..1)"""
        mult = {"short": 0.6, "medium": 0.85, "long": 1.0}[length]
        base = [("intro", 2, None), ("verse", 8, 0.45), ("pre", 4, 0.65),
                ("chorus", 8, 0.9), ("verse", 8, 0.5), ("chorus", 8, 1.0),
                ("bridge", 6, 0.4), ("chorus", 8, 1.0), ("outro", 3, None)]
        if length == "short":
            base = [("intro", 2, None), ("verse", 6, 0.5), ("chorus", 7, 1.0),
                    ("verse", 6, 0.55), ("chorus", 7, 1.0), ("outro", 2, None)]
        out = []
        for name, bars, energy in base:
            b = max(2, int(bars * mult))
            if name in ("intro", "outro"):
                out.append((name, b, 0.12))
            else:
                out.append((name, b, energy))
        return out

    # ---- chords ------------------------------------------------------------
    def chords_for(self, section: str, bars: int, prog_idx: int) -> list[tuple[int, str]]:
        rng = self.rng
        scale_steps = SCALES[self.scale]
        table = CHORD_QUAL[self.scale]
        progs = PROGRESSIONS[self.genre]
        degs = progs[prog_idx % len(progs)]
        out = []
        for i in range(bars):
            d = degs[i % len(degs)]
            root_off = scale_steps[d % len(scale_steps)] + 12 * (d // len(scale_steps))
            root = self.key_note + root_off
            qual = table[d % len(scale_steps)]
            out.append((root, qual))
        return out

    # ---- melody ------------------------------------------------------------
    def melody(self, chords: list[tuple[int, str]], section: str, energy: float,
               range_hi: int, motif: list[float] | None) -> tuple[list[float], list[float]]:
        """returns (note_midis, durations_sec) aligned roughly per bar; also motif."""
        rng = self.rng
        scale_steps = SCALES[self.scale]
        bar_d = len(chords)
        notes, durs = [], []
        if section == "bridge":
            rng = np.random.default_rng(self.seed + 77)   # deterministic contrast
        # motif: 6-10 notes in scale range
        if motif is None:
            lo, hi = self.key_note + 7, self.key_note + 19
            mot = [self._scale_note(rng, scale_steps, rng.integers(lo, hi))
                   for _ in range(int(rng.integers(6, 10)))]
        else:
            mot = list(motif)
            if self.rng.random() < 0.5:
                mot = [m + 12 for m in mot]        # lift an octave for variation
            if self.rng.random() < 0.4:
                mot = list(reversed(mot))
        for i, (root, qual) in enumerate(chords):
            chord_tones = [root + s for s in CHORD_INTERVALS[qual][:3]]
            beat_start = i * 4
            slots_per_bar = 8 if energy < 0.7 else 12 if energy < 0.93 else 16
            phrase_start = (i % 2 == 0)
            for s in range(slots_per_bar):
                if rng.random() > (0.42 + 0.35 * energy):
                    continue
                if phrase_start and s == 0:
                    f = mot[(i // 1) % len(mot)]
                else:
                    if rng.random() < 0.55 and s % 2 == 0:
                        f = chord_tones[rng.integers(0, len(chord_tones))] + \
                            (12 if rng.random() < 0.25 * energy else 0) + 12
                    else:
                        f = self._scale_note(rng, scale_steps, self.key_note + 12, self.key_note + 24)
                beat = beat_start + s * (4 / slots_per_bar)
                dur = rng.choice([1.0, 1.0, 1.5, 0.5], p=[0.35, 0.25, 0.2, 0.2]) * self.beat
                if sector := self._3slot(rng, energy, s, slots_per_bar):
                    dur = 0.5 * self.beat
                if f > self.key_note + range_hi + 12 and rng.random() < 0.8:
                    f -= 12
                if f is not None:
                    notes.append(f)
                    durs.append(dur)
                    ev = len(notes) - 1
        return notes, durs

    @staticmethod
    def _3slot(rng, energy, s, slots):
        return rng.random() < 0.18 * energy and slots >= 8 and s % 2 == 1

    def _scale_note(self, rng, scale_steps, lo, hi=None):
        hi = hi if hi is not None else lo + 12
        if hi <= lo:
            hi = lo + 12
        c = rng.integers(0, 64)
        iv = c % len(scale_steps)
        octv = c // len(scale_steps)
        return lo + octv * 12 + scale_steps[iv]

    # ---- arrangement -------------------------------------------------------
    def arrange(self, length: str = "medium"):
        """Fill self.events with all note/drum events; returns total duration."""
        rng, g, beat = self.rng, self.g, self.beat
        secs = self.sections(length)
        total_bars = sum(b for _, b, _ in secs)
        end = total_bars * self.bar

        # instrumentation gates by genre/config
        use_pad = g.get("pads", False)
        use_keys = g.get("keys_on", False)
        use_pluck = g.get("pluck", False)
        use_arp = g.get("arp_vel", 0) > 0
        use_lead = g.get("lead") not in ("keys", "stab", "square") or g["lead"] == "square"
        lead_kind = g["lead"]
        arp_vel = g.get("arp_vel", 0)
        use_acbass = g["bass"] == "acid"
        use_octbass = g["bass"] == "octave"
        use_sub = g["bass"] == "sub"
        drums_style = g["drums"]
        prog_idx = 0
        motif = None
        layer_ramp = 0.0
        grid = {}
        abs_bar = 0

        for name, bars, energy in secs:
            prog_idx = prog_idx + 1 if name == "chorus" and energy == 1.0 else prog_idx
            chords = self.chords_for(name, bars, prog_idx)
            t0 = abs_bar * self.bar
            # ---- pads / keys beds ----
            if (use_pad or use_keys) and energy > 0:
                for bi, (root, qual) in enumerate(chords):
                    if name in ("intro", "outro") and use_keys and not use_pad:
                        continue
                    dur = self.bar * 1.9
                    for iv in CHORD_INTERVALS[qual]:
                        f = note_freq(root + iv)
                        vel = 0.5 + 0.22 * energy
                        if name == "outro":
                            vel *= 0.6
                        self.events.append(dict(t=t0 + bi * self.bar, dur=dur, f=f,
                                                kind="pad" if use_pad else "keys" if use_keys else "pad",
                                                vel=vel, pan=rng.uniform(-0.35, 0.35)))
            # ---- pluck counter-melody (cinematic/ambient) ----
            if use_pluck and energy > 0.2 and name != "intro":
                for bi, (root, qual) in enumerate(chords):
                    if rng.random() < 0.72:
                        iv = CHORD_INTERVALS[qual][rng.integers(len(CHORD_INTERVALS[qual]))]
                        f = note_freq(root + iv + 12)
                        self.events.append(dict(t=t0 + bi * self.bar + 0.5 * beat,
                                                dur=beat * rng.uniform(0.8, 1.8), f=f,
                                                kind="pluck", vel=0.4, pan=rng.uniform(-0.4, 0.4)))
            # ---- arps ----
            if use_arp and energy >= 0.35:
                pat = rng.choice([[0, 2, 1, 2], [0, 1, 2, 3], [0, 0, 2, 1], [2, 1, 2, 0]])
                s16 = beat / 4
                for bi, (root, qual) in enumerate(chords):
                    tones = [root + s for s in CHORD_INTERVALS[qual][:4]]
                    for i in range(16):
                        iv = tones[pat[i % 4]]
                        f = note_freq(iv + 12)
                        ev_t = t0 + bi * self.bar + i * s16
                        if rng.random() < (arp_vel * (0.5 + 0.5 * energy)):
                            self.events.append(dict(t=ev_t, dur=s16 * 0.92, f=f, kind="divide",
                                                    vel=0.26 * arp_vel, pan=rng.uniform(-0.5, 0.5)))
            # ---- melody ----
            if name not in ("intro", "outro"):
                hi = 12 if name == "chorus" else 7
                if name == "bridge":
                    hi = 10
                m_notes, m_durs = self.melody(chords, name, energy, hi, motif)
                if motif is None:
                    motif = m_notes[:8] or None
                t = t0
                for f, d in zip(m_notes, m_durs):
                    self.events.append(dict(t=t, dur=d, f=note_freq(f), kind=lead_kind,
                                            vel=0.44 + 0.2 * energy, pan=rng.uniform(-0.2, 0.2)))
                    t += d
                if name == "chorus":  # occasional harmony third
                    pass
            # ---- bass ----
            if name != "intro":
                bass_kind = "acid" if use_acbass else "square" if g["bass"] == "square" else \
                            "octave" if use_octbass else "sub"
                for bi, (root, qual) in enumerate(chords):
                    root_f = note_freq(root - 12)
                    if use_acbass:
                        patt = [0, 0, 12, 0, 3 if rng.random() < 0.4 else 0, 0, 10, 0]
                        for i, iv in enumerate(patt):
                            f = note_freq(root - 24 + iv)
                            self.events.append(dict(t=t0 + bi * self.bar + i * (beat / 4) * (0.5 if i % 2 == 0 else 1),
                                                    dur=beat * 0.72, f=f, kind=bass_kind,
                                                    vel=0.5, pan=0.0))
                    elif use_octbass:
                        self.events.append(dict(t=t0 + bi * self.bar, dur=self.bar * 0.95,
                                                f=root_f, kind="sub", vel=0.52, pan=0.0))
                        self.events.append(dict(t=t0 + bi * self.bar, dur=self.bar / 2,
                                                f=root_f * 2, kind="sub", vel=0.34, pan=0.0))
                    else:
                        n_steps = 4 if (energy > 0.75 or g["bass"] == "sub") else 2
                        for i in range(n_steps):
                            self.events.append(dict(t=t0 + bi * self.bar + i * (self.bar / n_steps),
                                                    dur=self.bar / n_steps * 0.9, f=root_f,
                                                    kind="sub", vel=0.5, pan=0.0))
            # ---- drums ----
            if drums_style != "none" and (name != "intro"):
                self._drums(t0, bars, energy, name, end)
            abs_bar += bars

        # FX: cymbal swells into choruses
        for name, bars, energy in secs:
            pass
        # swells at section opens >0.8 energy
        abs_bar = 0
        for i, (name, bars, energy) in enumerate(secs):
            if energy > 0.85 and i > 0:
                self.events.append(dict(t=abs_bar * self.bar - 0.9, dur=1.6, f=0, kind="swell",
                                        vel=0.5 + 0.3 * energy, pan=rng.uniform(-0.3, 0.3)))
            abs_bar += bars
        return end

    def _drums(self, t0: float, bars: int, energy: float, section: str, song_end: float):
        rng, beat = self.rng, self.beat
        style = self.g["drums"]
        swing = self.g["swing"]
        add = self.events.append

        def ev(off, kind, vel=1.0, pan=None):
            pan = pan if pan is not None else rng.uniform(-0.15, 0.15)
            if style == "boom-bap" and kind == "snare":
                vel *= (0.7 + 0.3 * rng.random())
            add(dict(t=t0 + off * beat, dur=0, f=0, kind=kind, vel=vel, pan=pan))

        for b in range(bars):
            bi = t0 + b * self.bar
            is_fill = (b == bars - 1) and energy >= 0.5 and section != "intro"
            if style == "four":
                ev(bi, "kick", 0.95)
                ev(bi + 2 * beat, "kick", 0.8)
                ev(bi + beat, "snare", 0.75)
                ev(bi + 3 * beat, "snare", 0.75)
                for i in range(4):
                    ev(bi + beat / 2 + i * beat, "hat", 0.5 + 0.3 * energy)
                    ev(bi + i * beat, "hat", 0.42) if i < 4 else None
                ev(bi + beat * 1.5 + swing * beat, "open_hat", 0.3)
            elif style == "boom-bap":
                ev(bi, "kick", 0.9)
                if rng.random() < 0.5 + 0.3 * energy:
                    ev(bi + beat * 2.5 + swing * beat, "kick", 0.6)
                ev(bi + beat, "snare", 0.8)
                ev(bi + beat * 3, "snare", 0.8)
                for i in range(8):
                    off = beat * i * 0.5 + (swing * beat if i % 2 else 0)
                    vel = 0.3 + 0.2 * energy
                    if rng.random() < 0.65:
                        ev(bi + off, "hat", vel, 0.3 if i % 4 == 0 else -0.25)
                if rng.random() < 0.4 and energy > 0.6:
                    ev(bi + beat * 3.75, "rim", 0.5)
            elif style == "techno":
                for i in range(4):
                    ev(bi + i * beat, "kick", 0.98)
                ev(bi + beat, "clap", 0.75)
                ev(bi + 3 * beat, "clap", 0.75)
                for i in range(16):
                    ev(bi + i * beat / 4, "hat", 0.5 if i % 2 else 0.9)
                    ev(bi + i * beat / 4 + beat / 8, "hat", 0.25) if i % 2 == 0 else None
                if rng.random() < 0.5:
                    ev(bi + beat * 3.5, "open_hat", 0.35)
            elif style == "chiptune":
                ev(bi, "kick", 0.85)
                ev(bi + beat * 2, "kick", 0.6)
                if energy > 0.5:
                    ev(bi + beat, "snare", 0.6)
                    ev(bi + beat * 3, "snare", 0.6)
                for i in range(8):
                    ev(bi + i * beat / 2, "hat", 0.3)
            elif style == "taiko":
                ev(bi, "tom", 1.0, 0.0)
                ev(bi + beat * 2, "tom", 0.75, 0.0)
                if energy > 0.7:
                    ev(bi + beat, "snare", 0.45)
                    ev(bi + beat * 3, "snare", 0.45)
                if rng.random() < 0.35:
                    ev(bi + beat * 3.5, "swell_short", 0.4)
            if is_fill:
                for i in range(8):
                    ev(bi + i * beat / 2, "snare", 0.28 + 0.09 * i)
                ev(bi + beat * 3.5 + beat / 4, "open_hat", 0.5)


# ----------------------------------------------------------------- render ----
def fft_conv(x: np.ndarray, h: np.ndarray, chunk: int = 1 << 20) -> np.ndarray:
    """Overlap-add convolution (float32) — O(n log n), bounded memory."""
    x = x.astype(np.float32)
    h = h.astype(np.float32)
    n_out = len(x) + len(h) - 1
    out = np.zeros(n_out, dtype=np.float32)
    nh = len(h)
    nfft = 1 << (int(np.ceil(np.log2(chunk + nh - 1))))
    H = np.fft.rfft(np.pad(h, (0, nfft - nh)))
    for start in range(0, len(x), chunk):
        seg = x[start:start + chunk]
        ns = len(seg)
        X = np.fft.rfft(np.pad(seg, (0, nfft - ns)))
        y = np.fft.irfft(X * H)[:ns + nh - 1]
        out[start:start + ns + nh - 1] += y[:min(ns + nh - 1, len(out) - start)]
    return out[:n_out]


def reverb_ir(sr: int, seed: int, decay: float = 2.1, damp: float = 3800.0,
              size: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Two decorrelated decaying-noise IRs (stereo width)."""
    n = int(decay * sr)
    irl, irr = [], []
    for ch in range(2):
        rng = np.random.default_rng(seed + ch * 99991)
        # multi-tap early reflections + dense tail
        ir = np.zeros(n)
        for i in range(3):
            tap = int(rng.uniform(0.005, 0.05) * sr)
            ir[tap:tap + 2000] += rng.standard_normal(2000) * 0.5
        tail = rng.standard_normal(n) * np.exp(-np.arange(n) / (sr * (decay * 0.42 * size)))
        ir += tail * 0.6
        nf = np.fft.rfft(ir)
        fr = np.fft.rfftfreq(n, 1 / sr)
        nf *= 1 / (1 + (fr / damp) ** 1.6)
        irl.append(np.fft.irfft(nf, n) * 0.11)
        irr.append(np.fft.irfft(nf, n) * 0.11)
    return np.asarray(irl, dtype=np.float32), np.asarray(irr, dtype=np.float32)


def sidechain(track: np.ndarray, sr: int, bpm: float, depth: float) -> np.ndarray:
    """Pumping gain dip per beat (synthwave/techno)."""
    n = len(track)
    t = np.arange(n) / sr
    beat = 60 / bpm
    # dip right after each beat kick, recover by ~85% of beat
    ph = (t % beat) / beat
    env = 1 - depth * 0.8 * np.exp(-ph * 7) * (ph < 0.7)
    return track * env


def render(song: Song, length: str = "medium") -> tuple[np.ndarray, np.ndarray, float]:
    """Render song -> (L, R) float64 arrays [-1,1], duration sec."""
    rng = song.rng
    end = song.arrange(length)
    n = int(end * SR) + SR      # pad a second
    g = song.g
    verse_layers = {"pad": 0.0, "pluck": 0.0, "arp": 0.0, "lead": 0.0,
                    "keys": 0.0, "bass": 0.0, "drums": 0.0, "swell": 0.0}
    # split events by stem
    stems: dict[str, list[dict]] = {}
    for e in song.events:
        stems.setdefault(e["kind"], []).append(e)
    buf: dict[str, np.ndarray] = {}
    def get_stem(kind: str) -> np.ndarray:
        if kind in buf:
            return buf[kind]
        a = np.zeros(n)
        buf[kind] = a
        return a

    drums_ev = {}
    for kind, evs in stems.items():
        if kind in ("kick", "snare", "hat", "open_hat", "clap", "rim", "tom", "swell"):
            if kind == "swell":
                # swell events: (t, dur=1.6) from arrange
                a = get_stem("swell")
                for e in evs:
                    if e["t"] < 0:
                        continue
                    s = cymbal_swell(SR, rng, dur=e.get("dur", 1.6))
                    i0 = int(e["t"] * SR)
                    a[i0:i0 + len(s)] += s * e["vel"]
            else:
                drums_ev[kind] = evs
    for kind, evs in drums_ev.items():
        a = get_stem(kind)
        for e in evs:
            s = {"kick": kick, "snare": snare, "rim": rim}.get(kind)
            if s is None:
                s = (lambda sr, rng, open_=False, vel=1.0, v=kind: hat(sr, rng, v == "open_hat", 1.0))
            i0 = int(e["t"] * SR)
            if i0 < 0 or i0 >= n:
                continue
            if kind == "tom":
                wav = tom(SR, e.get("f", 150), e["vel"])
            elif kind == "clap":
                wav = clap(SR, rng)
            elif kind in ("hat", "open_hat"):
                wav = hat(SR, rng, kind == "open_hat", e["vel"])
            else:
                wav = s(SR, rng) * e["vel"]
            seg_len = min(len(wav), n - i0)
            a[i0:i0 + seg_len] += wav[:seg_len]

    # notes
    for kind in ("pad", "keys", "pluck", "lead", "stab", "string", "bell",
                 "square", "sub", "acid", "divide"):
        if kind not in stems:
            continue
        a = get_stem(kind)
        for e in stems[kind]:
            i0 = int(e["t"] * SR)
            if i0 >= n:
                continue
            wav = synth_note(e["f"], e["dur"], kind, SR, rng, e["vel"])
            seg_len = min(len(wav), n - i0)
            a[i0:i0 + seg_len] += wav[:seg_len]

    # ---- mix buses ---------------------------------------------------------
    wet_bus = np.zeros(n)
    dry = {"pad": 0.9, "keys": 0.85, "pluck": 0.55, "lead": 0.62, "stab": 0.5,
           "string": 0.8, "bell": 0.5, "square": 0.45, "sub": 0.0, "acid": 0.08,
           "divide": 0.4, "snare": 0.5, "kick": 0.0, "hat": 0.06, "open_hat": 0.12,
           "clap": 0.55, "rim": 0.15, "tom": 0.25, "swell": 0.7}
    gains = {"pad": 0.85, "keys": 0.7, "pluck": 0.4, "lead": 0.5, "stab": 0.38,
             "string": 0.8, "bell": 0.4, "square": 0.38, "sub": 0.6, "acid": 0.4,
             "divide": 0.32, "kick": 0.98, "snare": 0.6, "hat": 0.3, "open_hat": 0.25,
             "clap": 0.55, "rim": 0.32, "tom": 0.48, "swell": 0.4}
    L = np.zeros(n)
    R = np.zeros(n)
    for kind, a in buf.items():
        if kind == "swell":
            wet_bus += a * dry["swell"] * gains["swell"]
            continue
        gm = gains.get(kind, 0.5)
        wet_bus += a * dry.get(kind, 0.3) * gm
        if kind not in stems:
            continue
        for e in stems[kind]:
            i0 = int(e["t"] * SR)
            if i0 >= n:
                continue
            seg = int(e["dur"] * SR) + int(0.3 * SR) if e["dur"] > 0 else int(0.6 * SR)
            seg = max(0, min(seg, n - i0))
            if seg <= 0:
                continue
            p = float(np.clip(e["pan"], -0.6, 0.6))
            gL = np.cos((p + 1) * np.pi / 4)
            gR = np.sin((p + 1) * np.pi / 4)
            L[i0:i0 + seg] += a[i0:i0 + seg] * gm * gL
            R[i0:i0 + seg] += a[i0:i0 + seg] * gm * gR

    # bass sidechain / pump on pads etc.
    if g.get("sidechain", 0) > 0:
        for kind in ("pad", "divide", "acid", "sub"):
            if kind in buf:
                buf[kind] = sidechain(buf[kind], SR, song.bpm, g["sidechain"])
        wet_bus = sidechain(wet_bus, SR, song.bpm, g["sidechain"] * 0.6)

    # vinyl
    if g.get("vinyl", False):
        cr = vinyl_crackle(SR, end, rng, 0.5)
        crn = min(len(cr), n)
        L[:crn] += cr[:crn] * 0.45
        R[:crn] += cr[:crn] * 0.45

    # reverb
    irl, irr = reverb_ir(SR, song.seed)
    wet_l = fft_conv(wet_bus, irl[0], 1 << 20)
    wet_r = fft_conv(wet_bus, irr[0], 1 << 20)
    n2 = min(len(L), len(wet_l))
    L = L[:n2] + wet_l[:n2] * 1.1
    R = R[:n2] + wet_r[:n2] * 1.1

    # master: soft clip + loudness-normalize
    span = float(np.max(np.abs(L)) + np.max(np.abs(R))) / 2 + 1e-9
    L = np.tanh(L / span * 1.55) / 1.0
    R = np.tanh(R / span * 1.55) / 1.0
    pk = max(float(np.max(np.abs(L))), float(np.max(np.abs(R)))) + 1e-12
    L = L / pk * 0.89
    R = R / pk * 0.89

    # trim silence tail
    end_n = n
    for ch in (L, R):
        idx = np.nonzero(np.abs(ch) > 1e-4)[0]
        if len(idx):
            end_n = min(end_n, int(idx[-1]) + int(0.5 * SR))
    return L[:end_n], R[:end_n], end_n / SR


def write_wav(path: str, L: np.ndarray, R: np.ndarray, sr: int = SR) -> float:
    inter = np.empty((len(L) + len(R)) // 2 * 2, dtype=np.float32)
    n = min(len(L), len(R))
    inter = np.empty(n * 2, dtype=np.float32)
    inter[0::2] = L[:n]
    inter[1::2] = R[:n]
    pcm = np.clip(inter, -1, 1)
    pcm16 = (pcm * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm16.tobytes())
    return n / sr


def song_meta(song: Song, length: str) -> dict:
    return dict(seed=song.seed, genre=song.genre, bpm=song.bpm,
                key_note=song.key_note, scale=song.scale, mood=round(song.mood, 2),
                length=length, title=song.title,
                instruments=[k for k in ("pad", "keys", "pluck", "arp", "lead", "bass", "drums")
                             if k in song.events or k in (
                                 "arp" if song.g.get("arp_vel", 0) > 0 else [],
                                 "pad" if song.g.get("pads") else [],
                                 "keys" if song.g.get("keys_on") else [])])

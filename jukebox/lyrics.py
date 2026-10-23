"""AI Jukebox — lyrics & song naming. Seeded, deterministic (no network).

Turns a song's (seed, genre, theme) into a title, artist alias, and lyrics
with rhyming couplets and a hook. Supports an optional LLM upgrade in
generate.py (--llm) that replaces the templated lines with model-written ones.
"""
from __future__ import annotations
import re

# ------------------------------------------------------------- title atoms ---
TITLE_ATOMS = {
    "lofi":      (["Midnight", "Porch Light", "Coffee", "Window Seat", "Velvet", "Paper", "Slow", "Fading", "Tired", "Sunday"],
                  ["Rain", "Fog", "Embers", "Memos", "Letters", "Static", "Blue", "Hours", "Dreams", "Streets"]),
    "synthwave": (["Neon", "Chrome", "Electric", "Midnight", "Laser", "Vapor", "Night", "Ultraviolet", "Distant", "Turbo"],
                  ["Skyline", "Drive", "Horizon", "Signals", "Paradise", "Echo", "Memory", "Highway", "Sunset", "Machine"]),
    "techno":    (["Raw", "Concrete", "Strobe", "Iron", "Signal", "Underground", "Static", "Steel", "Zero", "Red"],
                  ["Pulse", "Generator", "Warehouse", "Circuit", "Loop", "Transmission", "Binary", "Oxide", "Grid", "Voltage"]),
    "chiptune":  (["Pixel", "Candy", "Turbo", "Princess", "Super", "Retro", "Blaster", "Magic", "Tiny", "Golden"],
                  ["Quest", "Arcade", "Party", "Laser", "Potion", "Turtle", "Galaxy", "Bonus", "Hero", "Zebra"]),
    "cinematic": (["Iron", "Last", "Distant", "Frozen", "Golden", "Silent", "Broken", "Endless", "Northern", "Ash"],
                  ["Summit", "Tide", "Frontier", "Forest", "Tempest", "Kingdom", "Horizon", "Voyage", "Serpent", "Throne"]),
    "ambient":   (["Weightless", "Thin", "Pale", "Still", "Drowsy", "Far", "Soft", "Lunar", "Opal", "Infinite"],
                  ["Tides", "Haze", "Glaciers", "Aurora", "Silence", "Vapor", "Meadows", "Orbit", "Sleep", "Mirage"]),
}

RHYME_PAIRS = [("sigh", "sky"), ("rain", "again"), ("night", "light"), ("dream", "stream"),
               ("glow", "below"), ("time", "rhyme"), ("fire", "higher"), ("deep", "sleep"),
               ("gold", "cold"), ("way", "day"), ("name", "flame"), ("wind", "begin"),
               ("moon", "soon"), ("shade", "parade"), ("roar", "more"), ("stone", "alone"),
               ("bright", "tonight"), ("sea", "free"), ("strong", "song"), ("blue", "through")]

THEME_BANKS = {
    "lofi":      dict(adj=["dusty", "amber", "rainy", "soft", "quiet", "faded", "warm", "sleepy"],
                      noun=["coffee", "rain", "windows", "letters", "streetlights", "records", "telephones", "curtains"],
                      verb=["burn", "linger", "wander", "flicker", "drift", "hum", "doze", "fold"]),
    "synthwave": dict(adj=["neon", "chrome", "electric", "violet", "hollow", "digital", "hazy", "silver"],
                      noun=["skyline", "freeways", "signals", "headlights", "chrome hearts", "tower blocks", "windshields", "arcades"],
                      verb=["accelerate", "glitch", "shine", "chase", "reflect", "burn", "ignite", "fade"]),
    "techno":    dict(adj=["concrete", "raw", "ruthless", "metallic", "black", "endless", "pressed", "brutal"],
                      noun=["circuits", "pistons", "speakers", "warehouse", "voltages", "crowds", "sirens", "calories"],
                      verb=["pound", "revolt", "converge", "flash", "compress", "repeat", "scream", "reload"]),
    "chiptune":  dict(adj=["tiny", "super", "golden", "glowing", "speedy", "magic", "sparkly", "brave"],
                      noun=["turtles", "lasers", "pixel clouds", "bonus rooms", "fairy dust", "power-ups", "rainbows", "rocket boots"],
                      verb=["bounce", "sparkle", "jump", "dash", "spin", "power up", "zoom", "respawn"]),
    "cinematic": dict(adj=["iron", "frozen", "ancient", "breaking", "northern", "golden", "silent", "hollow"],
                      noun=["mountains", "tides", "fires", "frontiers", "thrones", "armies", "forests", "glaciers"],
                      verb=["rise", "endure", "thunder", "collapse", "wander", "ignite", "surrender", "gather"]),
    "ambient":   dict(adj=["weightless", "pale", "thin", "still", "far", "soft", "opal", "drowsy"],
                      noun=["tides", "glaciers", "meadows", "vapor", "satellites", "glass waves", "auroras", "silence"],
                      verb=["drift", "breathe", "suspend", "settle", "murmur", "unfold", "float", "echo"]),
}

ARTIST_ALIASES = {
    "lofi":      ["Window Static", "The Sleepy Traffic", "Analog Memory", "Porchlight Trio"],
    "synthwave": ["Night City Choir", "Chrome Hearts Drive", "Laser Canyon", "The Ultraviolets"],
    "techno":    ["Piston Assembly", "Mono Block 9", "Redline Circuit", "Wire Motherboard"],
    "chiptune":  ["Turbo Princess", "The 8-Bit Buffs", "Pixel Patrol", "Super Bonus Club"],
    "cinematic": ["Iron Frontier", "The Northern Choir", "Ash & Amber", "Serpent Throne"],
    "ambient":   ["Glass Tides", "Opal Orbit", "The Slow Bureau", "Hollow Fields"],
}

MOOD_LABELS = ["hazebox", "slowcore", "daydream", "desklight", "tired orbit", "soft static",
               "blue hour", "low voltage", "rain radar", "quiet curve"]


def title_for(seed: int, genre: str, rng=None) -> str:
    import numpy as np
    r = rng or np.random.default_rng(seed)
    adj, noun = TITLE_ATOMS[genre]
    patterns = [lambda a, n: f"{a} {n}", lambda a, n: f"{a} {n}",
                lambda a, n: f"{a} on {n}", lambda a, n: f"{n} of {a}",
                lambda a, n: f"The {a} {n}"]
    return re.sub(r"\s+", " ", patterns[int(r.integers(0, len(patterns)))](adj[int(r.integers(len(adj)))],
                                                                          noun[int(r.integers(len(noun)))]).strip())


def artist_for(genre: str, rng) -> str:
    return ARTIST_ALIASES[genre][int(rng.integers(0, len(ARTIST_ALIASES[genre])))]


def _fit(s: str, target=9, max_dev=2):
    return len(s.split()) * 1.4 <= target + 2  # rough syllable proxy


def lyrics_for(seed: int, genre: str, title: str, rng=None) -> list[str]:
    """Structured lyrics: [VERSE] x2, [CHORUS], [VERSE], [CHORUS], [BRIDGE], [CHORUS]"""
    import numpy as np
    r = rng or np.random.default_rng(seed)
    bank = THEME_BANKS[genre]
    pairA, pairB = RHYME_PAIRS[int(r.integers(len(RHYME_PAIRS)))], RHYME_PAIRS[int(r.integers(len(RHYME_PAIRS)))]
    adj = lambda: bank["adj"][int(r.integers(len(bank["adj"])))]
    noun = lambda: bank["noun"][int(r.integers(len(bank["noun"])))]
    verb = lambda: bank["verb"][int(r.integers(len(bank["verb"])))]
    w = lambda ws: ws[int(r.integers(len(ws)))]

    def couplet(a, b, hook_lead=None):
        l1 = f"we {verb()} through the {adj()} {noun()}, and {a}"
        l2 = f"the {adj()} {noun()} {verb()}s where the {b} {verb()}s"
        if hook_lead:
            return [f"{hook_lead}, {a}", f"and {b} {verb()}s"]
        return [l1, l2]

    verse1 = couplet(pairA[0], pairA[1])
    verse2 = couplet(pairB[0], pairB[1])
    chorus = [f"{title.lower()} — the {adj()} {noun()}, the {pairA[1]}",
              f"{title.lower()}, {w(pairB)} and we {verb()} {pairA[1]}",
              f"hold the {adj()} {noun()}, don't let the {pairB[0]} pass",
              f"{title.lower()} — {pairA[1]}"]
    verse3 = couplet(pairB[0], pairA[1], hook_lead=None)
    bridge = [f"every {noun()} {verb()}s in {w(pairA)}",
              f"but the {noun()} keeps {verb()}ing {w(pairB)}"]
    outro = [f"{title.lower()}... {pairA[1]}"]

    return ["[Verse 1]", *verse1, "", "[Chorus]", *chorus, "", "[Verse 2]", *verse3, "",
            "[Chorus]", *chorus, "", "[Bridge]", *bridge, "", "[Chorus]", *chorus, "",
            "[Outro]", *outro]

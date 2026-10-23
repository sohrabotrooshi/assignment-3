"""AI Jukebox — generative cover art (SVG, seeded).

Per-genre art styles, seeded layout, hue driven by genre, brightness/saturation
by mood, title/artist/footer typography. Pure string building — no deps.
Optionally rendered to PNG via macOS `qlmanage` (--png).
"""
from __future__ import annotations

GENRE_HUES = {"lofi": 220, "synthwave": 290, "techno": 5, "chiptune": 140,
              "cinematic": 205, "ambient": 260}

STYLES = ["synthwave", "lofi", "geometric", "pixel", "landscape", "aurora", "rings", "glitch"]


def palette(seed: int, genre: str, mood: float) -> dict:
    """hue base by genre, jittered by seed; mood 0..1 -> brightness & warmth."""
    import numpy as np
    r = np.random.default_rng(seed ^ 0x5f5f)
    base = GENRE_HUES.get(genre, 220) + r.uniform(-14, 14)
    if mood < 0.45:      # calm -> deeper, cooler
        sat = 0.32 + r.uniform(-0.08, 0.10)
        bri = 0.13 + r.uniform(-0.03, 0.05)
        accent_d = 46 + r.uniform(-10, 30)
    elif mood < 0.75:    # mid
        sat = 0.55 + r.uniform(-0.1, 0.1)
        bri = 0.2 + r.uniform(-0.04, 0.08)
        accent_d = 18 + r.uniform(-8, 14)
    else:                # intense -> hot, saturated
        sat = 0.8 + r.uniform(-0.08, 0.12)
        bri = 0.3 + r.uniform(-0.05, 0.1)
        accent_d = -14 + r.uniform(-12, 10)
    base %= 360
    def h(x): return (base + x) % 360
    def hs(hue, s, l): return f"hsl({hue:.0f} {s:.2f * 100:.0f}% {l * 100:.0f}%)"
    bg1, bg2 = h(0), h(accent_d)
    return dict(r=r, hue0=base, hue1=h(accent_d), hue2=h(-accent_d * 0.6),
                sat=sat, bri=bri, fg=f"hsl({h(0):.0f} {sat * 100:.0f}% {min(0.92, bri + 0.62) * 100:.0f}%)")


def _box(t, lo, hi):
    return lo if t < lo else (hi if t > hi else t)


def cover_svg(seed: int, genre: str, title: str, artist: str, mood: float, bpm: int,
              length_s: float, scale: str = "", style: str | None = None) -> str:
    """Return full SVG markup (1024x1024). Style family per genre unless forced."""
    import numpy as np
    r = np.random.default_rng(seed)
    S = 1024
    style = style or {"lofi": "lofi", "synthwave": "synthwave", "techno": "geometric",
                      "chiptune": "pixel", "cinematic": "landscape",
                      "ambient": "aurora"}.get(genre, "rings")
    p = palette(seed, genre, mood)
    W, H = S, S
    esc_title = _esc(title)
    esc_artist = _esc(artist)
    footer = f"AI JUKEBOX  \u00b7  {genre.upper()}  \u00b7  {bpm} BPM  \u00b7 {scale or 'generated'}"
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">']

    def grad(id_, c0, c1, ang=0):
        return (f'<linearGradient id="{id_}" x1="0" y1="0" x2="1" y2="1" '
                f'gradientTransform="rotate({ang} .5 .5)"><stop offset="0" stop-color="{c0}"/>'
                f'<stop offset="1" stop-color="{c1}"/></linearGradient>')

    def hsl(h, s=None, l=None):
        s = p["sat"] if s is None else s
        l = p["bri"] if l is None else l
        return f"hsl({h % 360:.0f} {s * 100:.0f}% {l * 100:.0f}%)"

    c_bg1, c_bg2 = hsl(p["hue0"]), hsl(p["hue1"])
    c_acc, c_acc2 = hsl(p["hue2"], p["sat"] * 1.15, min(0.92, p["bri"] + 0.5)), hsl(p["hue1"] + 30, 0.75, 0.7)
    parts.append(grad("bg", c_bg1, c_bg2, int(r.integers(0, 360))))
    parts.append(f'<rect width="{W}" height="{H}" fill="url(#bg)"/>')

    if style == "synthwave":
        # sun + scanline sky + wireframe grid + stars + subtle horizon line
        sun = (r.uniform(0.3, 0.68) * W, r.uniform(0.3, 0.6) * H, r.uniform(0.12, 0.24) * W)
        parts.append(grad("sun", f"hsl({(p['hue2']+4)%360:.0f} 95% 72%)", f"hsl({(p['hue0'])%360:.0f} 90% 40%)"))
        parts.append(f'<circle cx="{sun[0]:.0f}" cy="{sun[1]:.0f}" r="{sun[2]:.0f}" fill="url(#sun)"/>')
        for i in range(int(r.uniform(45, 80))):  # stars
            x, y, rr = r.uniform(0, W), r.uniform(0, H * 0.75), r.uniform(1, 2.6)
            parts.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{rr:.1f}" fill="#ffffff" opacity="{r.uniform(0.3, 0.95):.2f}"/>')
        horizon = H * r.uniform(0.72, 0.84)
        parts.append(f'<rect x="0" y="{horizon:.0f}" width="{W}" height="{H - horizon:.0f}" fill="hsl({p["hue1"]:.0f} 45% 8%)" opacity="0.9"/>')
        # grid
        step = 34
        depth_lines = 16
        gh = (H - horizon) / depth_lines
        for k in range(depth_lines + 1):
            y = horizon + gh * k
            fade = 1 - k / depth_lines
            parts.append(f'<path d="M0 {y:.0f} L{W} {y:.0f}" stroke="{c_acc}" stroke-width="{2.2 * fade + 0.4:.1f}" opacity="{0.15 + 0.75 * fade:.2f}"/>')
            koff = (horizon * 0.9) / max(1, k + 1)
            for x in range(int(-W), int(W * 2), step):
                parts.append(f'<line x1="{x + koff:.0f}" y1="{horizon:.0f}" x2="{x + koff * 0.12:.0f}" y2="{horizon + gh:.0f}" stroke="{c_acc}" stroke-width="1" opacity="{0.12 + 0.5 * fade:.2f}"/>')
        # scanlines
        parts.append(f'<g opacity="0.12">' + "".join(
            f'<rect x="0" y="{y}" width="{W}" height="2" fill="#000"/>' for y in range(0, int(horizon), 5)) + '</g>')
    elif style == "lofi":
        # room scene: window + moon + plant silhouettes + floor + scattered records
        win = (W * 0.2, H * 0.2, W * 0.6, H * 0.5)
        parts.append(f'<rect x="{win[0]:.0f}" y="{win[1]:.0f}" width="{win[2]:.0f}" height="{win[3]:.0f}" rx="14" fill="#0a0d14" stroke="hsl({p["hue1"]:.0f} 30% 30%)" stroke-width="10"/>')
        mx, my, mr = win[0] + win[2] * r.uniform(0.25, 0.75), win[1] + win[3] * r.uniform(0.2, 0.55), win[2] * r.uniform(0.08, 0.16)
        parts.append(f'<circle cx="{mx:.0f}" cy="{my:.0f}" r="{mr:.0f}" fill="{c_acc}"/>')
        for i in range(3):  # stars in window
            x, y, rr = r.uniform(win[0], win[0] + win[2]), r.uniform(win[1], win[1] + win[3] * 0.6), r.uniform(1.4, 3)
            parts.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{rr:.1f}" fill="#fff" opacity="{r.uniform(0.3, 0.9):.1f}"/>')
        # horizon glow in window
        parts.append(f'<rect x="{win[0]:.0f}" y="{win[1] + win[3] * 0.8:.0f}" width="{win[2]:.0f}" height="{win[3] * 0.2:.0f}" fill="{c_bg1}" opacity="0.85"/>')
        # plants (triangles on stems) + lamp + records leaning on wall
        rng_u = r.uniform
        for px, ph, col in ((W * 0.2, H * 0.4, c_acc), (W * 0.1, H * 0.36, c_acc2)):
            parts.append(f'<path d="M{px:.0f} {H} L{px:.0f} {H - ph:.0f}" stroke="{col}" stroke-width="7"/>')
            for i in range(3):
                oy = H - ph + i * ph * 0.18
                parts.append(f'<ellipse cx="{px + (i - 1) * 30:.0f}" cy="{oy:.0f}" rx="{55 - i * 12:.0f}" ry="{13 - i * 2:.0f}" fill="{col}" opacity="0.9"/>')
        # leaning records
        for k, off in enumerate((W * 0.55, W * 0.68, W * 0.81)):
            ry = H * (0.98 - k * 0.03)
            parts.append(f'<ellipse cx="{off:.0f}" cy="{ry:.0f}" rx="{H * 0.09:.0f}" ry="{H * 0.13:.0f}" fill="#05060a" stroke="hsl({p["hue1"]:.0f} 50% 45%)" stroke-width="3"/>')
            parts.append(f'<circle cx="{off:.0f}" cy="{ry:.0f}" r="{H * 0.035:.0f}" fill="none" stroke="{c_acc}" stroke-width="2"/>')
        # floor line
        fy = H * 0.86
        parts.append(f'<rect x="0" y="{fy:.0f}" width="{W}" height="{H - fy:.0f}" fill="#05060a" opacity="0.55"/>')
        # scatter dust dots
        for _ in range(90):
            parts.append(f'<circle cx="{r.uniform(0, W):.0f}" cy="{r.uniform(0, fy):.0f}" r="{r.uniform(0.4, 1.2):.1f}" fill="#fff" opacity="{r.uniform(0.05, 0.3):.2f}"/>')
    elif style == "geometric":
        # black slab + clipped neon bars + glitch slices
        parts.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="#05050a"/>')
        parts.append(f'<rect x="{W * 0.06:.0f}" y="{H * 0.06:.0f}" width="{W * 0.88:.0f}" height="{H * 0.88:.0f}" fill="{hsl(p["hue0"], 0.5, 0.12)}"/>')
        n = int(r.integers(8, 16))
        for i in range(n):
            bw = r.uniform(0.02, 0.13) * W
            bx = r.uniform(0.1, 0.9) * W
            by = r.uniform(0.08, 0.92) * H
            col = hsl(p["hue2"], 0.9, 0.45 + r.uniform(-0.2, 0.3)) if i % 3 else c_acc2
            parts.append(f'<rect x="{bx:.0f}" y="{by:.0f}" width="{bw:.0f}" height="{H * r.uniform(0.05, 0.4):.0f}" fill="{col}" opacity="{r.uniform(0.55, 1):.2f}"/>')
        for i in range(6):  # glitch slices
            sl = r.uniform(0.08, 0.16) * H
            sy = r.uniform(0.3, 0.9) * H
            dx = (r.random() - 0.5) * 0.25 * W
            parts.append(f'<rect x="0" y="{sy:.0f}" width="{W}" height="{sl:.0f}" fill="{hsl(p["hue1"], 0.8, 0.16)}" transform="translate({dx:.0f} 0)"/>')
        # rising bars at bottom
        for i, bx in enumerate(np.linspace(60, W - 60, 22)):
            bh = r.uniform(0.08, 0.38) * H
            parts.append(f'<rect x="{bx:.0f}" y="{H - bh:.0f}" width="13" height="{bh:.0f}" fill="{c_acc if i % 2 else c_acc2}" opacity="0.85"/>')
    elif style == "pixel":
        parts.append(f'<rect width="{W}" height="{H}" fill="#05060b"/>')
        # mosaic of big translucent squares in hue ramp
        n = 8
        for yy in range(n):
            for xx in range(n):
                hue = (p["hue0"] + (xx * 17 + yy * 9 + r.integers(-8, 8))) % 360
                parts.append(f'<rect x="{xx * W / n:.0f}" y="{yy * H / n:.0f}" width="{W / n + 1:.0f}" height="{H / n + 1:.0f}" fill="hsl({hue:.0f} {p["sat"] * 0.8 * 100:.0f}% {p["bri"] * 100 + 8:.0f}%)" opacity="{0.35 + (xx % 2) * 0.2:.2f}"/>')
        # centered heart/star made of pixels
        cx, cy = W * 0.5, H * 0.42
        px = 26
        motif = r.choice(["heart", "star"])
        cells = _motif_cells(motif, px, W * 0.34, H * 0.3)
        for (mx, my) in cells:
            parts.append(f'<rect x="{cx + mx - px/2:.0f}" y="{cy + my - px/2:.0f}" width="{px}" height="{px}" fill="{c_acc}"/>')
    elif style == "landscape":
        parts.append(f'<rect width="{W}" height="{H}" fill="url(#bg)"/>')
        layers = [(0.72, 0.55), (0.82, 0.72), (0.93, 0.88)]
        for li, (base, alpha) in enumerate(layers):
            yb = H * base
            pts = [f"M0 {yb + H * 0.1:.0f}"]
            x = 0
            while x < W:
                pts.append(f"L{x:.0f} {yb + np.sin(x / 140 + li * 4 + seed) * r.uniform(10, 40):.0f}")
                x += W / 24 + r.uniform(-8, 8)
            pts.append(f"L{W} {yb + H * 0.1:.0f} Z")
            lcol = hsl(p["hue1"] + li * 14, p["sat"] * (0.7 - li * 0.12), 0.14 + li * 0.06)
            parts.append(f'<path d="{" ".join(pts)}" fill="{lcol}" opacity="{alpha}"/>')
        # aurora bands
        for i in range(3):
            ay = H * r.uniform(0.2, 0.6)
            aw = W * r.uniform(0.7, 1.1)
            parts.append(f'<ellipse cx="{W * 0.5:.0f}" cy="{ay:.0f}" rx="{aw:.0f}" ry="{H * r.uniform(0.04, 0.1):.0f}" fill="{c_acc}" opacity="{r.uniform(0.10, 0.3):.2f}" transform="rotate({r.uniform(-20, 20):.0f} {W * 0.5:.0f} {ay:.0f})"/>')
    elif style == "aurora":
        parts.append(f'<rect width="{W}" height="{H}" fill="#040508"/>')
        n = int(r.integers(5, 9))
        for i in range(n):
            bx, by, bw, bh = r.uniform(0, W), r.uniform(0, H), W * r.uniform(0.8, 1.6), H * r.uniform(0.4, 0.9)
            col = hsl(p["hue0"] + i * 18, p["sat"] * (0.7 + i % 3 * 0.15), 0.2 + i * 0.05)
            parts.append(f'<ellipse cx="{bx:.0f}" cy="{by:.0f}" rx="{bw:.0f}" ry="{bh:.0f}" fill="{col}" opacity="0.22" transform="rotate({r.uniform(-30, 30):.0f} {bx:.0f} {by:.0f})"/>')
        for _ in range(160):
            parts.append(f'<circle cx="{r.uniform(0, W):.0f}" cy="{r.uniform(0, H):.0f}" r="{r.uniform(0.3, 1.3):.1f}" fill="#fff" opacity="{r.uniform(0.04, 0.22):.2f}"/>')
    elif style == "rings":
        parts.append(f'<rect width="{W}" height="{H}" fill="{hsl(p["hue0"], 0.6, 0.08)}"/>')
        cx, cy = W * r.uniform(0.3, 0.7), H * r.uniform(0.3, 0.7)
        for i, rad in enumerate(np.linspace(W * 0.25, W * 0.9, 14)):
            parts.append(f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{rad:.0f}" fill="none" stroke="{hsl(p["hue1"] + i * 9, p["sat"], 0.25 + i * 0.035):.0f}" stroke-width="{r.uniform(1, 9):.0f}" opacity="{0.5 if i % 2 == 0 else 0.85:.2f}"/>')
        for _ in range(140):
            parts.append(f'<circle cx="{r.uniform(0, W):.0f}" cy="{r.uniform(0, H):.0f}" r="{r.uniform(0.4, 1.6):.1f}" fill="{c_acc}" opacity="{r.uniform(0.1, 0.6):.2f}"/>')
    elif style == "glitch":
        parts.append(f'<rect width="{W}" height="{H}" fill="#030308"/>')
        for i in range(28):
            x, y = r.uniform(0, W) * 0.7, r.uniform(0, H)
            w, h = W * r.uniform(0.08, 0.9), r.uniform(8, 46)
            col = hsl(p["hue0"] + r.integers(-20, 20), 0.95, r.uniform(0.3, 0.75))
            parts.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" fill="{col}" opacity="{r.uniform(0.4, 0.9):.2f}"/>')

    # vignette
    parts.append(f'<radialGradient id="vig" cx="0.5" cy="0.45" r="0.75">'
                 f'<stop offset="0.62" stop-color="transparent"/>'
                 f'<stop offset="1" stop-color="rgba(0,0,0,0.55)"/></radialGradient>')
    parts.append(f'<rect width="{W}" height="{H}" fill="url(#vig)"/>')

    # typography
    fs = _box(len(esc_title) * 0.62, 44, 92)
    if len(esc_title) > 22:
        fs *= 0.72
    parts.append(f'<text x="60" y="{H - 205}" font-family="system-ui, -apple-system, sans-serif" '
                 f'font-size="{fs:.0f}" font-weight="800" fill="{p["fg"]}" '
                 f'letter-spacing="1.5">{esc_title}</text>')
    parts.append(f'<text x="62" y="{H - 145}" font-family="system-ui, -apple-system, sans-serif" '
                 f'font-size="30" font-weight="500" fill="{p["fg"]}" opacity="0.86">{esc_artist}</text>')
    ln = int(H * 0.055)
    parts.append(f'<line x1="60" y1="{H - 120}" x2="{W - 60}" y2="{H - 120}" stroke="{p["fg"]}" opacity="0.25"/>')
    parts.append(f'<text x="60" y="{H - 72}" font-family="ui-monospace, monospace" font-size="25" '
                 f'fill="{p["fg"]}" opacity="0.72" letter-spacing="3">{_esc(footer)}</text>')
    parts.append("</svg>")
    return "".join(parts)


_MOTIFS = {
    "heart": [(0, 0), (1, 0), (2, 1), (3, 0), (4, 0), (1, 1), (3, 1), (0, 2), (2, 2),
              (4, 2), (1, 3), (3, 3), (2, 4)],
    "star":  [(1, 0), (2, 0), (3, 0), (0, 1), (1, 1), (2, 1), (3, 1), (4, 1), (1, 2),
              (2, 2), (3, 2), (0, 3), (1, 3), (2, 3), (3, 3), (4, 3), (2, 4)],
}


def _motif_cells(kind, px, w, h):
    cells = _MOTIFS[kind]
    scale = max(2, int(w / px / 5))
    out = []
    for (a, b) in cells:
        cx = (a - 2) * px * scale
        cy = (b - 2) * px * scale
        for s in range(scale):
            for t in range(scale):
                out.append((cx + s * px, cy + t * px))
    return out


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def write_cover(path: str, seed: int, genre: str, title: str, artist: str,
                mood: float, bpm: int, length_s: float, scale: str = "",
                style: str | None = None) -> str:
    svg = cover_svg(seed, genre, title, artist, mood, bpm, length_s, scale, style)
    with open(path, "w") as f:
        f.write(svg)
    return path


def svg_to_png(svg_path: str, out_png: str, size: int = 1024) -> bool:
    """Use macOS QuickLook to rasterize (no deps)."""
    import subprocess, os
    try:
        subprocess.run(["qlmanage", "-t", "-s", str(size), "-o", os.path.dirname(out_png),
                        svg_path], capture_output=True, timeout=30)
        cand = svg_path + ".png"
        if os.path.exists(cand):
            os.replace(cand, out_png)
            return True
    except Exception:  # noqa: BLE001
        pass
    return False

# Verify the jukebox build

Run the integrity gate and report the result table:

```
python3 jukebox/verify.py
```

It checks every setlist in `library/`: playlist.js parses and matches
setlist.json, every audio/cover/lyrics/dj file exists, WAVs decode as valid
stereo audio with sane duration and non-silent RMS, covers are well-formed SVG,
DJ clips are within a speakable length. Exit code 0 = all green.

If anything fails, fix it before proposing a merge — never skip the gate.

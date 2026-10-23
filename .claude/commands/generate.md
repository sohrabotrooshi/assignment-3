# Generate a setlist, song, or art

Call the jukebox generator exactly as documented in `jukebox/README.md`.
Use `jukebox/.venv/bin/python` when the import needs numpy.

Arguments passed to the command flow into the CLI:

- `/generate setlist --name "My Mix" --genres lofi,techno --count 6 --seed 42`
- `/generate song --genre synthwave --seed 7 --bpm 104 --mood 0.8 --length long`
- `/generate demo --force` — rebuild both demo setlists

Defaults when no arguments: `config setlist --name "Team Mix" --count 5`.

After generating, run `python3 jukebox/verify.py` and report the summary.

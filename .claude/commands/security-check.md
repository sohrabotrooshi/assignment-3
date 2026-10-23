# Security check before pushing

Scan the repo for leaked credentials and forbidden assets, then report:

1. Tracked files that look like secrets:
   ```
   git ls-files | grep -E '(^|/)\.env$|secrets?\.|credential|\.pem$|id_rsa'
   ```
2. Secret material anywhere in the tracked tree:
   ```
   git grep -nE 'Bearer [A-Za-z0-9._-]{16,}|api[_-]?key[^=]{0,20}[=:]\s*["'"'"'][A-Za-z0-9]{12,}|password\s*[=:]'
   ```
3. Forbidden assets tracked (audio/samples/recordings):
   ```
   git ls-files | grep -iE '\.(wav|mp3|aiff|m4a|flac|ogg|png|jpg)$'
   ```
   (`jukebox/screenshot.png` is the only allowed image — UI preview.)
4. Staged-but-should-not-be:
   ```
   git diff --cached --name-only | grep -E '(^|/)\.env$|library/'
   ```

Remediate any hit by untracking/removing the file, then re-run. The guard hook
also blocks secret-looking staged changes automatically.

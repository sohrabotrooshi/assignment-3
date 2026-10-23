#!/bin/bash
# Claude Code PreToolUse guard for the assignment-3 repo.
# Blocks: destructive commands, commits/pushes that would leak secrets,
# and force-pushes / direct pushes to main. Exit 2 = tool call blocked.
INPUT="${CLAUDE_TOOL_INPUT:-}"
CMD=$(printf '%s' "$INPUT" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    ti = d.get('tool_input', d) if isinstance(d, dict) else {}
    print(ti.get('command') or ti.get('prompt') or '')
except Exception:
    sys.exit(0)
" 2>/dev/null)
[ -z "$CMD" ] && exit 0

# 1) destructive / dangerous
if printf '%s' "$CMD" | grep -qE '\brm -rf\b|:\(\)|mkfs|> /dev/sd|dd if=.*of=/dev/|curl .*\|.*sh'; then
  echo "guard: destructive command blocked (rm -rf / pipe-to-shell etc.)"
  exit 2
fi

# 2) force pushes (any branch) stay blocked; direct pushes incl. main are fine
if printf '%s' "$CMD" | grep -qE 'git push -f|git push --force( |$)|git push.*--force-with-lease'; then
  echo "guard: force-push is blocked — use a normal push or revert instead."
  exit 2
fi

# 3) staging secret-bearing files or committing secret-looking lines
if printf '%s' "$CMD" | grep -qE '\bgit (add|commit|push)\b'; then
  # staged path check
  if git diff --cached --name-only 2>/dev/null | grep -qE '(^|/)\.env$|\.env\.local$|secrets?\.(json|yaml|yml|py)$'; then
    echo "guard: refused — .env / secrets file would be committed."
    exit 2
  fi
  # staged content check (python — placeholder lines exempt)
  python3 - "$1" <<'PY'
import re, subprocess, sys
staged = subprocess.run(["git", "diff", "--cached"], capture_output=True, text=True).stdout
lines = [l[1:].strip() for l in staged.splitlines()
         if l.startswith("+") and not l.startswith("+++")]
lines = [l for l in lines
         if not re.search(r"your-|example|placeholder|EXAMPLE|YOUR_", l)]
pat = re.compile(
    r"(?:api[_-]?key|token)[^\w]*[:=][^\w]*[\"']?[A-Za-z0-9]{12,}"
    r"|(?:password|secret)[^\w]*[:=][^\w]*[\"']?[A-Za-z0-9]{8,}"
    r"|bearer[^\w]+[A-Za-z0-9._-]{16,}", re.I)
if any(pat.search(l) for l in lines):
    print("guard: possible credential detected in staged changes — check before committing.")
    sys.exit(2)
PY
  [ $? -eq 2 ] && exit 2
fi
exit 0

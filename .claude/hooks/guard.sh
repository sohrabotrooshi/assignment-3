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

# 2) git main / force pushes
if printf '%s' "$CMD" | grep -qE 'git (push|merge|rebase).*main|git push -f|git push --force'; then
  echo "guard: pushing/force-pushing to main is blocked — use a branch + PR (team rule)."
  exit 2
fi

# 3) staging secret-bearing files or committing secret-looking lines
if printf '%s' "$CMD" | grep -qE '\bgit (add|commit|push)\b'; then
  # staged path check
  if git diff --cached --name-only 2>/dev/null | grep -qE '(^|/)\.env$|\.env\.local$|secrets?\.(json|yaml|yml|py)$'; then
    echo "guard: refused — .env / secrets file would be committed."
    exit 2
  fi
  # staged content check (generous patterns; .env.example placeholders are fine)
  if git diff --cached 2>/dev/null | grep -E '^\+' | grep -qvE '^\+.*(your-|example|placeholder|EXAMPLE|YOUR_)' | \
     grep -qiE 'api[_-]?key[\"'']?[:=][\"'']?[A-Za-z0-9]{12,}|bearer [A-Za-z0-9._-]{16,}|password[\"'']?[:=][\"'']?[A-Za-z0-9]{8,}|secret[\"'']?[:=][\"'']?[A-Za-z0-9]{8,}|token[\"'']?[:=][\"'']?[A-Za-z0-9]{12,}'; then
    echo "guard: possible credential detected in staged changes — check before committing."
    exit 2
  fi
fi
exit 0

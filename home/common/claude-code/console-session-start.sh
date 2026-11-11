#!/bin/sh
# The console's SessionStart hook (issue 857, ADR-console-003). SessionStart takes
# no HTTP hook, so this command posts the hook input from stdin to the console.
# The build swaps in dash and a store curl. -q (first) skips any curlrc and
# --noproxy keeps a proxy off loopback; the answer and any error are discarded,
# because SessionStart stdout would enter the session's context, and the exit
# status is always 0: a stopped console costs the session nothing.
@curl@ -q -s -o /dev/null --noproxy '*' --max-time 1 \
  -H 'Content-Type: application/json' --data-binary @- \
  "http://127.0.0.1:${1:-27184}/api/hooks" 2>/dev/null
exit 0

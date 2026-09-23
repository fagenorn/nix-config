# Import every new JPEG under ~/Pictures/exports into Photos (iCloud Photos) and move it to the
# .imported/ archive so it is never imported twice. Triggered by launchd whenever the folder
# changes (WatchPaths) and hourly as a safety net; safe to run by hand.
EXPORTS="$HOME/Pictures/exports"
DONE="$EXPORTS/.imported"
LOG="$HOME/Library/Logs/photos-import-exports.log"
mkdir -p "$EXPORTS" "$DONE"
log() { printf '%s %s\n' "$(date '+%F %T')" "$*" >>"$LOG"; }

# only files that have not been written to for 30s (darktable writes exports in place)
mapfile -t files < <(find "$EXPORTS" -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.heic' -o -iname '*.png' \) \
  -not -path "$DONE/*" -mmin +0.5 | sort)
[ "${#files[@]}" -gt 0 ] || exit 0

list=""
for f in "${files[@]}"; do list="$list, POSIX file \"$f\""; done
list="${list#, }"
if osascript -e "tell application \"Photos\" to import {$list} with skip check duplicates" >>"$LOG" 2>&1; then
  for f in "${files[@]}"; do
    rel="${f#"$EXPORTS"/}"
    mkdir -p "$DONE/$(dirname "$rel")"
    mv -n "$f" "$DONE/$rel"
  done
  log "imported ${#files[@]} file(s) into Photos"
else
  log "Photos import FAILED for ${#files[@]} file(s); left in place for retry"
  exit 1
fi

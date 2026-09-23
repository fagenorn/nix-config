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

# paths go in as arguments, never spliced into the script text: a quote or backslash in a file
# name would otherwise break (or rewrite) the AppleScript and block every queued file
if osascript - "${files[@]}" >>"$LOG" 2>&1 <<'OSA'; then
on run argv
	set theFiles to {}
	repeat with p in argv
		set end of theFiles to POSIX file (contents of p)
	end repeat
	tell application "Photos" to import theFiles with skip check duplicates
end run
OSA
  for f in "${files[@]}"; do
    rel="${f#"$EXPORTS"/}"
    dest="$DONE/$rel"
    # a re-export under an already-archived name must still leave the folder, or every later
    # run would import it again: archive it beside the earlier copy with a timestamp
    [ ! -e "$dest" ] || dest="$DONE/${rel%.*}.$(date '+%Y%m%d-%H%M%S').${rel##*.}"
    mkdir -p "$(dirname "$dest")"
    mv -n "$f" "$dest" || true
    [ ! -e "$f" ] || log "could not archive $f to $dest; it will be imported again"
  done
  log "imported ${#files[@]} file(s) into Photos"
else
  log "Photos import FAILED for ${#files[@]} file(s); left in place for retry"
  exit 1
fi

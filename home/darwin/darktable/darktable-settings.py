#!/usr/bin/env python3
"""Apply the Lightroom-style darktable configuration idempotently.

Run from home-manager activation (home/darwin/darktable/default.nix). darktable rewrites
darktablerc and shortcutsrc on exit, so this is a merge, not a replacement: only the keys listed
here are (re)set, everything else darktable saved is preserved. Skipped when darktable is running
(it would overwrite the change on exit anyway). Safe to run repeatedly.
"""
import os, subprocess, sys, shutil, time

CFG = os.path.expanduser("~/.config/darktable")
RC = os.path.join(CFG, "darktablerc")
SC = os.path.join(CFG, "shortcutsrc")

if subprocess.run(["/usr/bin/pgrep", "-x", "darktable"], capture_output=True).returncode == 0:
    print("darktable is running; settings will be applied at the next activation", file=sys.stderr)
    sys.exit(0)
if not os.path.exists(RC):
    print("no darktablerc yet (darktable never started); nothing to do", file=sys.stderr)
    sys.exit(0)

RC_SET = {
    # --- import: recurse, no auto star rating, copyright applied, camera filenames kept ---
    "ui_last/import_recursive": "true",
    "ui_last/import_initial_rating": "0",
    "ui_last/import_apply_metadata": "true",
    "ui_last/import_last_rights": "Anis",
    "ui_last/import_ignore_nonraws": "false",
    # "copy & import" destination mirrors the migrated Lightroom album tree: Travel/<year>/<trip>
    # (the job code asked for at import is the trip name). photo-import uses the same layout.
    "session/base_directory_pattern": "$(PICTURES_FOLDER)/darktable",
    "session/sub_directory_pattern": "Travel/$(YEAR)/$(JOBCODE)",
    "session/use_filename": "true",
    # like Lightroom's "automatically write changes into XMP": edits live next to the raw
    "write_sidecar_files": "on import",
    # thumbnails from embedded JPEG previews until edited (fast grid)
    "plugins/lighttable/thumbnail_raw_min_level": "never",
    "plugins/lighttable/thumbnail_hq_min_level": "720p",
    "ui_last/theme": "darktable-elegant-grey",
    # display-referred (legacy) base = basecurve. This is the pipeline darktable's Lightroom
    # sidecar importer targets and the model Lightroom itself uses; a scene-referred base
    # (sigmoid) instead stacks on top of Adobe's imported tonecurve and double-tone-maps
    # (crushed/"deep fried" images, artifacts when toggling modules). Both migrated images
    # (basecurve + Adobe modules) and new images (basecurve + the LR - Kodak film style)
    # then have exactly one tone mapping.
    "plugins/darkroom/workflow": "display-referred (legacy)",
    "plugins/lighttable/layout": "1",
    # collapse groups: each migrated raw is grouped under its Lightroom-rendered JPEG (the group
    # leader), so the library shows one thumbnail per photo; the raw is one click on the "G"
    # overlay away. Also collapses camera RAW+JPEG pairs, which darktable groups on import.
    "ui_last/grouping": "true",
    "lighttable/ui/scrollbars": "true",
    # --- export: full-size JPEG q92 into ~/Pictures/exports/<trip>/; a launchd watcher imports
    # everything that lands there into Photos (iCloud) ---
    "plugins/lighttable/export/storage_name": "disk",
    "plugins/lighttable/export/format_name": "jpeg",
    "plugins/imageio/format/jpeg/quality": "92",
    "plugins/imageio/storage/disk/file_directory": "$(PICTURES_FOLDER)/exports/$(ROLL_NAME)/$(FILE_NAME)",
    "plugins/imageio/storage/disk/overwrite": "0",
    "plugins/lighttable/export/dimensions_type": "0",
    "plugins/lighttable/export/width": "0",
    "plugins/lighttable/export/height": "0",
}

# Lightroom muscle memory. Displaced darktable defaults keep working behind a modifier.
SC_MOVE = {
    "g=views/darkroom/guide lines/toggle": "g;shift=views/darkroom/guide lines/toggle",
    "e=iop/exposure/exposure": "e;shift=iop/exposure/exposure",
    "p=global/switch views/print": "p;shift=global/switch views/print",
    "x=views/lighttable/toggle culling mode;toggle": "x;option=views/lighttable/toggle culling mode;toggle",
}
SC_ADD = [
    "g=global/switch views/lighttable",          # G  grid / library
    "e=global/switch views/darkroom",            # E  loupe -> darkroom (D also works)
    "x=views/thumbtable/rating;reject",          # X  reject (R also works)
    "p=views/thumbtable/color label;green",      # P  pick -> green label (filter on green = album picks)
    "6=views/thumbtable/color label;red",        # 6-9 colour labels
    "7=views/thumbtable/color label;yellow",
    "8=views/thumbtable/color label;green",
    "9=views/thumbtable/color label;blue",
    "e;shift;cmd=lib/export/start export",       # cmd+shift+E export (cmd+E also works)
]

stamp = time.strftime("%Y%m%d-%H%M%S")
changed = False

lines = open(RC).read().splitlines()
seen, out = set(), []
for ln in lines:
    k = ln.split("=", 1)[0]
    if k in RC_SET:
        seen.add(k)
        new = f"{k}={RC_SET[k]}"
        changed |= new != ln
        out.append(new)
    else:
        out.append(ln)
for k, v in RC_SET.items():
    if k not in seen:
        out.append(f"{k}={v}")
        changed = True
if changed:
    shutil.copy2(RC, RC + ".bak-" + stamp)
    open(RC, "w").write("\n".join(out) + "\n")

if os.path.exists(SC):
    sc = open(SC).read().splitlines()
    orig = list(sc)
    sc = [SC_MOVE.get(ln, ln) for ln in sc]
    for add in SC_ADD:
        key = add.split("=", 1)[0]
        sc = [ln for ln in sc if not (ln.split("=", 1)[0] == key and ln != add)]
        if add not in sc:
            sc.append(add)
    if sc != orig:
        shutil.copy2(SC, SC + ".bak-" + stamp)
        open(SC, "w").write("\n".join(sc) + "\n")
        changed = True

# --- luarc: apply the house style to every newly imported raw (Lightroom "apply preset on
# import"). The styles module import is a one-off GUI/DB step; this only wires the event.
# Kept as a marked block so the lua script manager can add its own lines to luarc.
LUARC = os.path.join(CFG, "luarc")
LUA_BLOCK = """-- BEGIN nix-managed: default look on import
local dt = require "darktable"
local wanted = "LR - Kodak (film)"
local selected = nil
for _, style in ipairs(dt.styles) do
  if style.name == wanted then selected = style; break end
end
if selected then
  dt.register_event("nix_default_style", "post-import-image", function(_, image)
    if image.is_raw then image:apply_style(selected) end
  end)
else
  dt.print_error("default import style not found: " .. wanted .. " (import it in lighttable > styles)")
end
-- END nix-managed
"""
lua = open(LUARC).read() if os.path.exists(LUARC) else ""
import re as _re
new = _re.sub(r"-- BEGIN nix-managed: default look on import.*?-- END nix-managed\n", LUA_BLOCK, lua, flags=_re.S) \
    if "-- BEGIN nix-managed: default look on import" in lua else (lua.rstrip("\n") + ("\n" if lua else "") + LUA_BLOCK)
if new != lua:
    open(LUARC, "w").write(new)
    changed = True

# --- styles: the Lightroom-preset ports (styles/*.dtstyle, built and tuned against Lightroom's
# own renders; see styles/NOTES.md). Imported into data.db only when a style of that name is
# absent, so edits made to a style inside darktable are never clobbered. Delete a style in
# darktable to have the shipped version re-imported at the next activation.
import sqlite3, glob
STYLES_DIR = os.environ.get("DARKTABLE_STYLES_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "styles"))
DATA_DB = os.path.join(CFG, "data.db")
if os.path.exists(DATA_DB) and os.path.isdir(STYLES_DIR):
    import xml.etree.ElementTree as ET
    con = sqlite3.connect(DATA_DB)
    have = {r[0] for r in con.execute("select name from styles")}
    con.close()
    missing = [f for f in sorted(glob.glob(os.path.join(STYLES_DIR, "*.dtstyle")))
               if ET.parse(f).getroot().findtext("info/name") not in have]
    if missing:
        importer = os.environ.get("DARKTABLE_STYLE_IMPORTER",
                                  os.path.join(os.path.dirname(os.path.abspath(__file__)), "import-dtstyles.py"))
        subprocess.run([sys.executable, importer, DATA_DB, *missing], check=True)
        changed = True

print("darktable settings " + ("updated" if changed else "already current"), file=sys.stderr)

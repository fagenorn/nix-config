#!/usr/bin/env python3
"""photo-import: copy a card into the darktable library, split by trip, geotag, open darktable.

    photo-import /Volumes/RICOH "2026-03-01..2026-03-06=Bali" "2026-03-07..2026-03-10=Lombok" \
        [--timeline ~/Downloads/Timeline.json] [--tz +01:00] [--root ~/Pictures/darktable/Travel] \
        [--dry-run] [--no-open] [--allow-unassigned]

Each range is inclusive (dates in the camera's local time, from EXIF DateTimeOriginal, else CreateDate). Files land in
<root>/<year>/<trip>/<original filename>; an existing file with the same size is skipped, a different
one is never overwritten (reported instead). Images outside every range are listed and abort the run
unless --allow-unassigned is given. With --timeline, a Google Maps Timeline export (the on-device
"Timeline.json" format or Takeout's "Records.json") is converted to GPX before anything is copied, and
exiftool geotags the copied files that have no GPS yet (including ones an earlier run copied but never
tagged), assuming the camera clock is at --tz (default +01:00), with the
same 30-minute interpolation window as the old Lightroom workflow. Finally darktable opens the new
folders (its import is recursive and applies your default style).
"""
import argparse, datetime as dt, json, os, re, shutil, subprocess, sys, tempfile

RAW_EXT = {".arw", ".dng", ".raf", ".nef", ".cr2", ".cr3", ".orf", ".rw2", ".jpg", ".jpeg", ".heic", ".png", ".mp4", ".mov"}


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def scan(source):
    """Return [(path, capture datetime or None, has_gps)] for every image under source."""
    files = []
    for root, _, names in os.walk(source):
        for n in names:
            if n.startswith(".") or os.path.splitext(n)[1].lower() not in RAW_EXT:
                continue
            files.append(os.path.join(root, n))
    if not files:
        return []
    out = run(["exiftool", "-json", "-fast2", "-DateTimeOriginal", "-CreateDate", "-GPSLatitude", "-@", "-"],
              input="\n".join(files)).stdout
    res = []
    for rec in json.loads(out):
        raw = rec.get("DateTimeOriginal") or rec.get("CreateDate")
        when = None
        if raw:
            m = re.match(r"(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2}):(\d{2})", raw)
            if m:
                when = dt.datetime(*map(int, m.groups()))
        res.append((rec["SourceFile"], when, "GPSLatitude" in rec))
    return res


def parse_range(spec):
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})=(.+)", spec.strip())
    if not m:
        sys.exit(f"bad range {spec!r}; expected YYYY-MM-DD..YYYY-MM-DD=Trip name")
    a, b, name = dt.date.fromisoformat(m.group(1)), dt.date.fromisoformat(m.group(2)), m.group(3).strip()
    if b < a:
        sys.exit(f"range {spec!r} ends before it starts")
    return a, b, re.sub(r'[\\/:*?"<>|]', "-", name)


def timeline_to_gpx(path, out):
    """Google Maps Timeline JSON (device export or Takeout Records.json) -> minimal GPX track."""
    data = json.load(open(path))
    pts = []

    def iso(s):
        s = s.replace("Z", "+00:00")
        t = dt.datetime.fromisoformat(s)
        return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)

    def geo(s):
        m = re.search(r"(-?\d+\.\d+)°?\s*,\s*(-?\d+\.\d+)", s or "")
        return (float(m.group(1)), float(m.group(2))) if m else None

    segments = data.get("semanticSegments") if isinstance(data, dict) else data
    if isinstance(data, dict) and "locations" in data:  # Takeout Records.json
        for l in data["locations"]:
            if "latitudeE7" in l and "timestamp" in l:
                pts.append((l["latitudeE7"] / 1e7, l["longitudeE7"] / 1e7, iso(l["timestamp"])))
    elif segments:
        for t in segments:
            if "timelinePath" in t:
                start = iso(t["startTime"])
                for p in t["timelinePath"]:
                    g = geo(p.get("point"))
                    if g:
                        off = p.get("durationMinutesOffsetFromStartTime", 0)
                        when = iso(p["time"]) if p.get("time") else start + dt.timedelta(minutes=int(off))
                        pts.append((g[0], g[1], when))
            elif "visit" in t:
                g = geo(t["visit"].get("topCandidate", {}).get("placeLocation", {}).get("latLng")
                        if isinstance(t["visit"].get("topCandidate", {}).get("placeLocation"), dict)
                        else t["visit"].get("topCandidate", {}).get("placeLocation"))
                if g:
                    # a stay is one place for hours: emit a fix every 10 minutes so exiftool's
                    # 30-minute interpolation window is satisfied for every photo taken there
                    start, end = iso(t["startTime"]), iso(t["endTime"]) if t.get("endTime") else iso(t["startTime"])
                    when = start
                    while when <= end:
                        pts.append((g[0], g[1], when))
                        when += dt.timedelta(minutes=10)
                    if pts[-1][2] != end:
                        pts.append((g[0], g[1], end))
            elif "activity" in t:
                for key, tk in (("start", "startTime"), ("end", "endTime")):
                    g = geo(t["activity"].get(key, {}).get("latLng") if isinstance(t["activity"].get(key), dict) else t["activity"].get(key))
                    if g and t.get(tk):
                        pts.append((g[0], g[1], iso(t[tk])))
    pts.sort(key=lambda x: x[2])
    with open(out, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.0" creator="photo-import">\n<trk><trkseg>\n')
        for lat, lon, when in pts:
            f.write(f'<trkpt lat="{lat:.7f}" lon="{lon:.7f}"><time>{when.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}</time></trkpt>\n')
        f.write("</trkseg></trk></gpx>\n")
    return len(pts)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    ap.add_argument("ranges", nargs="+", help="YYYY-MM-DD..YYYY-MM-DD=Trip name")
    ap.add_argument("--root", default=os.path.expanduser("~/Pictures/darktable/Travel"))
    ap.add_argument("--timeline", help="Google Maps Timeline JSON export")
    ap.add_argument("--tz", default="+01:00", help="camera clock offset from UTC, e.g. +01:00 (default) or +09:00")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-open", action="store_true", help="do not launch darktable afterwards")
    ap.add_argument("--allow-unassigned", action="store_true", help="proceed even if some images match no range")
    a = ap.parse_args()
    if not re.fullmatch(r"[+-]\d{2}:\d{2}", a.tz):
        sys.exit("--tz must look like +01:00")
    ranges = [parse_range(r) for r in a.ranges]

    files = scan(a.source)
    if not files:
        sys.exit(f"no images found under {a.source}")
    plan, unassigned, undated = [], [], []
    for path, when, has_gps in files:
        if when is None:
            undated.append(path)
            continue
        trip = next((name for s, e, name in ranges if s <= when.date() <= e), None)
        if trip is None:
            unassigned.append((path, when))
            continue
        dest = os.path.join(a.root, str(when.year), trip, os.path.basename(path))
        plan.append((path, dest, has_gps))
    for path in undated:
        print(f"WARNING no capture date, skipped: {path}", file=sys.stderr)
    if unassigned:
        print(f"{len(unassigned)} image(s) match no trip range:", file=sys.stderr)
        for path, when in unassigned[:20]:
            print(f"  {when:%Y-%m-%d %H:%M}  {path}", file=sys.stderr)
        if len(unassigned) > 20:
            print(f"  … and {len(unassigned) - 20} more", file=sys.stderr)
        if not a.allow_unassigned:
            sys.exit("aborting: add a range for them or pass --allow-unassigned")

    # convert the timeline before touching the library: a missing or malformed export has to
    # stop the run here, not after the copy, when a rerun would skip the files it never tagged
    gpx, npts = None, 0
    if a.timeline:
        with tempfile.NamedTemporaryFile(suffix=".gpx", delete=False) as tmp:
            gpx = tmp.name
        try:
            npts = timeline_to_gpx(os.path.expanduser(a.timeline), gpx)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            os.unlink(gpx)
            sys.exit(f"cannot read timeline {a.timeline}: {e}")
        if not npts:
            os.unlink(gpx)
            sys.exit(f"no location points in timeline {a.timeline}")

    copied, skipped, conflicts, untagged = [], 0, [], []
    for src, dest, has_gps in plan:
        if os.path.exists(dest):
            if os.path.getsize(dest) == os.path.getsize(src):
                # same size means untouched since an earlier run (geotagging rewrites the file),
                # so it still lacks GPS if the source does: tag it on this run instead
                if not has_gps:
                    untagged.append(dest)
                skipped += 1
                continue
            conflicts.append(dest)
            continue
        if a.dry_run:
            print(f"would copy {src} -> {dest}")
        else:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(src, dest + ".part")
            os.replace(dest + ".part", dest)
        copied.append((dest, has_gps))
    for c in conflicts:
        print(f"CONFLICT different file already at {c}; source left untouched", file=sys.stderr)
    per_trip = {}
    for dest, _ in copied:
        per_trip[os.path.dirname(dest)] = per_trip.get(os.path.dirname(dest), 0) + 1
    for d, n in sorted(per_trip.items()):
        print(f"{n:5d}  {d}")
    print(f"{len(copied)} copied, {skipped} already present, {len(conflicts)} conflicts" + (" (dry run)" if a.dry_run else ""))

    if gpx and (copied or untagged) and not a.dry_run:
        need = untagged + [dest for dest, has_gps in copied if not has_gps]
        if need:
            print(f"geotagging {len(need)} image(s) from {npts} timeline points (camera clock {a.tz})")
            # the capture time falls back exactly as in scan(): exiftool applies the later
            # assignment only when its source tag exists, so DateTimeOriginal wins over CreateDate
            r = subprocess.run(["exiftool", "-geotag", gpx, f"-geotime<${{CreateDate}}{a.tz}",
                                f"-geotime<${{DateTimeOriginal}}{a.tz}",
                                "-api", "GeoMaxIntSecs=1800", "-overwrite_original", "-P", "-q", "-@", "-"],
                               input="\n".join(need), capture_output=True, text=True)
            sys.stderr.write(r.stderr)
            if r.returncode not in (0, 1):
                print("exiftool geotag failed", file=sys.stderr)
        else:
            print("all copied images already carry GPS; timeline not needed")
    if gpx:
        os.unlink(gpx)

    if copied and not a.no_open and not a.dry_run:
        subprocess.Popen(["open", "-a", "darktable", "--args", *sorted(per_trip)])
        print("darktable opened on the new folders")


if __name__ == "__main__":
    main()

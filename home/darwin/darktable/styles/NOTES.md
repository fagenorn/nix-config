# Lightroom preset ports for darktable 5.6.1

These files target **darktable 5.6.1**. They deliberately contain no crop,
orientation, white-balance/temperature, camera input profile, or output profile
from a reference image. Apply them in **append** mode to a normally initialized
raw history stack. Do not use `--style-overwrite`: that removes darktable's
raw preparation, demosaic, input color profile, and base color-calibration
steps and produces an invalid comparison.

## Files and intended use

- `LR - Kodak.dtstyle`: Film v2 / Kodak Night-family port, using the requested
  contrast -15 Night curve as its tonal base.
- `LR - Kodak Nature.dtstyle`: Kodak Nature port.
- `LR - Church.dtstyle`: Church port. There was no Church reference-render
  directory, so this one has technical round-trip verification but no
  Lightroom visual ground truth.
- `LR - Kodak (dt).dtstyle`: scene-referred reinterpretation of the Kodak look.
- `compare/kodak/`: eight Lightroom/darktable pairs for `LR - Kodak`.
- `compare/kodak-nature/`: three pairs for `LR - Kodak Nature`.
- `compare/kodak-dt/`: the same eight Kodak references rendered with the
  scene-referred variant.

The Lightroom files are copies of the supplied references. The darktable files
were rendered at a 2048-pixel bounding box with the finished style and the
isolated `out/dtconfig` configuration.

## Lightroom to darktable mapping

### LR - Kodak

| Lightroom control | darktable 5.6.1 mapping |
|---|---|
| Exposure / contrast -15 family | exposure v7, +0.45 EV with a -0.0025 black offset after the Round 2 crop-aware calibration; sigmoid v3 supplies the required scene-to-display transform |
| Point curve `(2,26) (62,57) (127,127) (197,204) (255,240)` | tone curve v5, normalized to 0..1, cubic spline |
| Orange hue -6; yellow -23; aqua +12; blue -45; blue luminance +16 | color equalizer (`colorequal`) v4 with the eight hue nodes stored directly in degrees and blue brightness at 1.16. Hue smoothing 0.65 keeps the blue move out of red/magenta subjects |
| Shadow grade 305°/13; highlight 41°/35 | split-toning v1, hue normalized to 0..1, 50 balance and 80 compression. Source inspection shows this confines shadow color to HSL lightness below roughly 0.136 instead of tinting the sky |
| Midtone grade 31°/24 and vibrance character | color balance rgb v5: midtone hue 31°, chroma 0.030; highlight hue 41°, chroma 0.035; vibrance 0.03 |
| Grain amount 26, size 42, roughness 53 | grain v2, lightness channel, scale 2.55 and strength 20.8. The scale/strength use darktable's Lightroom importer interpolation tables |
| Post-crop vignette -16, midpoint 50, feather 50 | vignetting v4: brightness -0.224, scale 100, falloff 50, saturation -0.30, automatic aspect ratio |
| Lens profile enabled (Kodak Night) | lens correction v10, embedded-metadata mode, with empty camera/lens strings so no reference camera is baked in |

### LR - Kodak Nature

| Lightroom control | darktable 5.6.1 mapping |
|---|---|
| Exposure 0; contrast -15; highlights -19; shadows +20; whites -4; blacks -19 | exposure v7 at +0.55 EV with black correction 0.0019, plus the Nature point curve. The EV value is the median visual calibration against the three supplied renders |
| Point curve `(0,14) (67,68) (127,127) (207,221) (254,246)` | tone curve v5, normalized cubic spline |
| Green hue -1; aqua +12; blue -45; red luminance -9; green -12; blue +16 | color equalizer v4: direct hue nodes and brightness multipliers 0.91/0.88/1.16 for red/green/blue |
| Shadow 305°/21; midtone 31°/37; highlight 41°/41 | split-toning v1 at 80 compression for the tails plus color balance rgb v5 for the missing midtone grade (midtone chroma 0.035, highlight chroma 0.025, vibrance 0.04) |
| Grain 38/42/53 | grain v2, lightness channel, scale 2.55, strength 30.4 |
| Vignette -16/50/50 | vignetting v4, automatic aspect ratio |
| Lens profile enabled | lens correction v10 in reusable embedded-metadata mode |

The Lightroom Nature sidecar also contains an image-specific sky mask. It is
not part of the preset and was not baked into the reusable style.

### LR - Church

| Lightroom control | darktable 5.6.1 mapping |
|---|---|
| Exposure +0.01, contrast +100, highlights -60, shadows +55, whites -50 | exposure v7 (+0.71 visual calibration), tone curve v5, and shadows/highlights v5 (55/-60, white point -5) |
| Texture +14, clarity +18, dehaze +35 | local contrast v3 (`bilat`, detail 0.117) and haze removal v3 (0.35) |
| Church point curve `(4,0) (60,65) (127,119) (193,177) (255,255)` | tone curve v5 |
| Hue/saturation/luminance mixer | color zones v5: yellow hue -28, aqua hue +94; red/orange/yellow/aqua/blue/purple/magenta saturation -28/+14/-47/-94/-24/-85/-94; orange/blue luminance +9/-14 |
| Shadow 195°/10; highlight 55°/9 | split-toning v1 |
| Grain 5/25/50; vignette -27, midpoint 26 | grain v2 and vignetting v4 |

The preset's 5185 K / +10 tint was intentionally excluded. Its Lightroom lens
profile flag is off, so the Church style intentionally has no lens module.

### LR - Kodak (dt)

This version avoids the legacy tone curve, color zones, and split-toning
modules. Its stack is:

- exposure v7: +0.75 EV after crop-aware calibration against DSC02299;
- a second color calibration v3 instance named `Kodak look calibration`, with
  the neutral built-in basic channel-mixer parameters (no global color matrix
  is used for the look);
- tone equalizer v2 bands `+0.12 +0.22 +0.28 +0.20 +0.08 -0.04 -0.14 -0.24
  -0.30` EV, opening deep shadows while restraining the top bands;
- color equalizer v4: orange -6°, yellow -23°, cyan +12°, blue -45°, and blue
  brightness 1.16, with hue smoothing 0.65;
- color balance rgb v5: shadow 305°/0.020, midtone 31°/0.012, highlight
  41°/0.060, global saturation 0.035, vibrance 0.10, global hue rotation 0°, small
  shadow brilliance lift and highlight brilliance restraint;
- sigmoid v3: contrast 1.38, skew -0.10, RGB-primary tuning (red inset 0.04 / +1.5°,
  green inset 0.04 / -0.8°, blue inset 0.12 / -4.5°), purity 0.04;
- diffuse or sharpen v2: one conservative detail iteration;
- lightness grain v2 (amount-equivalent 24, midtone bias 35), vignette v4
  (amount-equivalent -14), and reusable lens correction v10.

Compared with the direct port, sigmoid gives smoother highlight compression,
tone equalizer prevents the deepest shadows becoming muddy/blocked, and color
balance rgb keeps the warm-highlight/magenta-shadow relationship in a
scene-referred space. The Round 2 color equalizer is the scene-referred
selective HSL stage: it replaces both the former custom calibration matrix and
the former -12° global hue rotation, so reds remain true while only aqua/blue
is moved toward teal.

## Binary parameter audit

All style `op_params` are little-endian blobs encoded as lowercase hex. Blend
parameters are current blendop v14 blobs from a clean 5.6.1 database. The
following current struct versions and sizes were checked before encoding:

| Operation | Version | Blob bytes |
|---|---:|---:|
| exposure | 7 | 28 |
| sigmoid | 3 | 56 |
| channelmixerrgb / color calibration | 3 | 160 |
| colorbalancergb | 5 | 132 |
| toneequal | 2 | 72 |
| diffuse | 2 | 60 |
| tonecurve | 5 | 520 |
| colorzones | 5 | 520 |
| colorequal | 4 | 128 |
| splittoning | 1 | 24 |
| grain | 2 | 16 |
| vignette | 4 | 44 |
| lens | 10 | 356 |
| shadhi | 5 | 48 |
| hazeremoval | 3 | 16 |
| bilat | 3 | 20 |

`colorin` v7 (1044 bytes) and `colorout` v5 (520 bytes) were also checked, but
are deliberately absent so the styles do not bake a camera input or display
output profile. `filmicrgb.c` was inspected at its current v6 layout; it is not
encoded because the modern style uses sigmoid v3 instead.

The audit used the pinned `release-5.6.1` files under
[`src/iop`](https://github.com/darktable-org/darktable/tree/release-5.6.1/src/iop),
including `exposure.c`, `sigmoid.c`, `filmicrgb.c`, `colorbalancergb.c`,
`channelmixerrgb.c`, `toneequal.c`, `diffuse.c`, `grain.c`, `vignette.c`,
`colorin.c`, `colorout.c`, and `lens.cc`. The 5.6.1 Fossies source/Doxygen
mirror was used as a second readable view, including the
[`filmicrgb.c` v6 declaration](https://fossies.org/dox/darktable-5.6.1/filmicrgb_8c_source.html).
Direct shell `curl` was DNS-blocked in the scratch environment; no layout was
guessed. The installed 5.6.1 history/preset rows and successful fresh-database
round trip corroborated every blob size and module version.

## Verification and visual stopping point

The four XML files were parsed, imported as new rows into a newly initialized
`out/roundtrip-config-20260920/data.db`, and then applied by darktable-cli 5.6.1
to a raw. All four exports completed without module-conversion or parameter-size
errors. Fresh-config item counts were 9 / 9 / 10 / 9 for Kodak, Nature, Church,
and Kodak (dt), respectively.

Three visual tuning rounds were compared as Lightroom|darktable contact sheets.
The final direct Kodak port is close in median exposure, contrast, grain, and
vignette, and its warm/magenta grade reads consistently. The largest residuals
are Adobe's stronger gold/teal camera-profile response in the aircraft image
and the highly cyan individual dog image. Pushing the global style far enough
to match those two degraded the portrait and garden references, so tuning was
stopped at that diminishing-return point. Nature is close across all three
references; remaining differences are chiefly per-image crop, white balance,
and Adobe profile rendering. The modern version preserves the look while
showing cleaner bright skies/lights and more legible deep foliage/shadows.

The supplied Lightroom renders include per-image exposure, white balance,
crop/orientation, masks, and sometimes different members of the Kodak family.
Those image-specific operations explain unavoidable framing and some tone/color
differences; the reusable styles intentionally exclude them.

SHA-256:

```text
b73162252f03a6948e67fca126f53428de366535215be1afe42b82f1a28f272a  LR - Kodak.dtstyle
d37fc66265fcd5490313b214cd8588c76d8e5ceca0bc7c5b7d69c695a18d034b  LR - Kodak Nature.dtstyle
101d7b460c061af567a7d397f49c8a21bdc1167abed3941ff83a6b1d62c050b7  LR - Church.dtstyle
526d2a3253343ec48c902d5c5a9c7e013d072e37c7c10be39d7f30d30f4c601f  LR - Kodak (dt).dtstyle
```

## Importing and applying

Recommended GUI route:

1. Open lighttable and expand the **styles** module.
2. Click **import**, select the four `.dtstyle` files, and confirm replacement
   only if an older copy already exists.
3. Select images, choose **append** mode, and double-click the desired style.

The styles module and import behavior are documented in the
[darktable 5.6 manual](https://docs.darktable.org/usermanual/5.6/en/module-reference/utility-modules/shared/styles/).

For a headless import, close darktable first and back up `data.db`, then use the
tested helper retained in `work/`:

```sh
python3 work/import_dtstyles.py /path/to/darktable/data.db \
  'LR - Kodak.dtstyle' 'LR - Kodak Nature.dtstyle' \
  'LR - Church.dtstyle' 'LR - Kodak (dt).dtstyle'
```

An importable style is not itself an auto-apply preset, and the 5.6 import
dialog only auto-applies metadata/tags. For a fixed default look at import,
place the following in darktable's `luarc` after importing the style (change the
name if desired), then restart darktable:

```lua
local dt = require "darktable"
local wanted = "LR - Kodak (dt)"
local selected = nil
for _, style in ipairs(dt.styles) do
  if style.name == wanted then selected = style; break end
end
if selected then
  dt.register_event("lr_kodak_default", "post-import-image",
    function(_, image)
      if image.is_raw then image:apply_style(selected) end
    end)
else
  dt.print_error("auto style not found: " .. wanted)
end
```

This uses darktable's documented
[`darktable.styles.apply`](https://docs.darktable.org/lua/stable/lua.api.manual/darktable/darktable.styles/)
API and the `post-import-image` event. The official camera-style script uses
the same import-event approach. If automatic application is not wanted, assign
a shortcut to the style and apply it to the import selection from lighttable.

## Round 2

Round 2 supersedes the earlier visual stopping-point discussion. The reported
purple sky and pink-red failure were reproducible, and both came from color
operations that were too broad: legacy color-zones/split-toning for the direct
port, and a -12° global hue rotation plus a custom calibration matrix for the
modern port.

The replacement is `colorequal` v4. Its 128-byte 5.6.1 struct was checked
directly in the pinned
[`colorequal.c`](https://github.com/darktable-org/darktable/blob/release-5.6.1/src/iop/colorequal.c):
`threshold`, `smoothing_hue`, `contrast`, `white_level`, `chroma_size`,
`param_size`, `use_filter`, eight saturation floats, eight hue floats in
degrees, eight brightness floats, and `hue_shift`. All three Kodak-family
styles use the direct Lightroom-like nodes; the two main styles use orange
-6°, yellow -23°, cyan +12°, blue -45°, and blue brightness 1.16. The modern
style's global hue rotation is exactly 0° and its look-calibration matrix is
neutral. The direct and Nature split-toning compression is 80, which the pinned
`splittoning.c` formula maps to shadow toning below about 0.136 HSL lightness;
this keeps 305° magenta out of normal blue sky.

### Quantitative method and stopping point

For each pair, the darktable render was cropped from the normalized Lightroom
sidecar crop coordinates, then both images were Lanczos-resized to the same
grid (maximum dimension 512). ΔL* uses sRGB → CIELAB D65 and is darktable minus
Lightroom. Hue is a saturation/value-weighted circular HSV mean; ΔH is the
wrapped absolute difference. The same values were measured over the full frame
and its top 25%. Full mean RGB and H/S/V values for every final pair are in
`ROUND2_METRICS.md`.

The DSC02299 acceptance image changed as follows:

| Style | Full ΔL* before → after | Full ΔH° before → after | Top-25% ΔL* before → after | Top-25% ΔH° before → after |
|---|---:|---:|---:|---:|
| LR - Kodak | -7.94 → -3.53 | 14.6 → 7.8 | -11.32 → -6.81 | 13.0 → 7.8 |
| LR - Kodak (dt) | -8.25 → -2.96 | 24.5 → 6.6 | -11.72 → -6.20 | 34.3 → 8.4 |

The direct style therefore meets the ~8° sky-hue and 4 L* full-frame targets;
the modern style meets the L* target and is within 0.4° of the approximate
top-strip hue target. Its actual sky is visibly teal/cyan; the top strip also
contains large red and orange umbrellas, so its single circular mean is not a
pure sky segmentation.

Median absolute/difference summary across each complete reference set:

| Look | Median abs full ΔL* | Median full ΔH° | Median abs top ΔL* | Median top ΔH° |
|---|---:|---:|---:|---:|
| LR - Kodak | 3.12 → 3.96 | 25.8 → 18.9 | 5.99 → 6.31 | 33.8 → 17.9 |
| LR - Kodak (dt) | 3.04 → 4.45 | 21.4 → 14.4 | 7.53 → 6.40 | 26.2 → 13.8 |
| LR - Kodak Nature | 0.70 → 0.31 | 8.3 → 1.1 | 4.00 → 3.97 | 12.3 → 9.5 |

Per-image before → after values (`full ΔL*`, `full ΔH°`, `top ΔL*`, `top ΔH°`):

| LR - Kodak image | Full ΔL* | Full ΔH° | Top ΔL* | Top ΔH° |
|---|---:|---:|---:|---:|
| DSC00254 | +3.68 → +6.68 | 17.9 → 13.3 | +7.41 → +10.26 | 19.8 → 14.5 |
| DSC00334 | -2.55 → +4.13 | 149.3 → 69.3 | -6.40 → +1.56 | 93.4 → 11.0 |
| DSC01132 | -2.33 → +0.95 | 35.4 → 9.4 | -5.34 → -3.03 | 116.5 → 72.3 |
| DSC01719 | +4.21 → +7.48 | 25.5 → 23.0 | +5.58 → +7.91 | 36.3 → 30.9 |
| DSC02017 | +15.17 → +23.47 | 25.8 → 21.4 | +15.06 → +19.57 | 24.0 → 14.6 |
| DSC02299 | -7.94 → -3.53 | 14.6 → 7.8 | -11.32 → -6.81 | 13.0 → 7.8 |
| DSC03048 | +0.60 → +3.64 | 25.7 → 16.4 | -2.77 → +0.04 | 31.4 → 21.3 |
| R0001088 | -0.31 → +3.79 | 178.8 → 171.2 | +2.44 → +5.81 | 150.4 → 167.7 |

| LR - Kodak (dt) image | Full ΔL* | Full ΔH° | Top ΔL* | Top ΔH° |
|---|---:|---:|---:|---:|
| DSC00254 | +2.40 → +6.53 | 18.3 → 12.5 | +6.81 → +10.85 | 17.0 → 12.6 |
| DSC00334 | -3.67 → +2.91 | 70.2 → 24.2 | -8.24 → -1.01 | 51.2 → 15.1 |
| DSC01132 | -5.92 → -1.43 | 53.5 → 13.3 | -12.20 → -8.11 | 156.8 → 10.6 |
| DSC01719 | +2.31 → +5.95 | 14.6 → 15.4 | +2.54 → +5.41 | 14.4 → 14.9 |
| DSC02017 | +18.63 → +31.13 | 5.9 → 18.7 | +15.78 → +28.69 | 0.7 → 11.5 |
| DSC02299 | -8.25 → -2.96 | 24.5 → 6.6 | -11.72 → -6.20 | 34.3 → 8.4 |
| DSC03048 | +1.04 → +4.89 | 11.5 → 10.2 | -2.60 → +0.75 | 18.2 → 17.5 |
| R0001088 | -0.75 → +4.01 | 168.8 → 166.0 | +2.27 → +6.60 | 179.1 → 178.3 |

| LR - Kodak Nature image | Full ΔL* | Full ΔH° | Top ΔL* | Top ΔH° |
|---|---:|---:|---:|---:|
| DSC01503 | -0.36 → -0.31 | 4.6 → 0.4 | +1.30 → +1.61 | 6.6 → 0.7 |
| DSC01955 | +9.69 → +9.55 | 11.0 → 6.2 | +16.75 → +16.84 | 12.3 → 9.5 |
| DSC02348 | +0.70 → +0.29 | 8.3 → 1.1 | +4.00 → +3.97 | 20.8 → 12.5 |

Not every per-image L* residual can be brought under 4 with one reusable
style: the supplied Lightroom sidecars include different exposure,
highlight/shadow, white-balance, local-mask, and crop edits. For example,
DSC02017 uses -0.67 EV and 4420 K while DSC00334 uses +0.24 EV, highlights
-75, and 6021 K. Those image-specific corrections were not baked into the
styles. A trial of darktable's automatic exposure mode made the spread worse
(DSC02017 reached +47.65 L*) and was discarded. This is the documented
diminishing-returns boundary.

Visual review covered DSC02299 in both Kodak styles, DSC00334, and Nature
DSC01503. DSC02299 now has cyan/teal sky, warm whites, lifted blacks, and deep
red rather than pink umbrellas. DSC00334 confirms the blue-to-teal direction,
though Adobe's per-image -75 highlight recovery remains visibly darker. Nature
DSC01503 is close in tone and hue; darktable remains a little more saturated
and contrasty in foliage. Grain and vignette remain readable and consistent.

Finally, all four XML styles were re-imported into the fresh
`roundtrip-config-round2-20260920` database and each was applied by
darktable-cli 5.6.1 to a new raw path. Final item counts are 9 / 9 / 10 / 10
for Kodak, Nature, Church, and Kodak (dt), with no module-conversion,
parameter-size, or export errors.

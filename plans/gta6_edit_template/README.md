# GTA 6 streamer-clip vertical edit template

Built ahead of the Nov 19 GTA 6 launch per `plans/gta6_launch.md`. Reusable ffmpeg
preset + Python driver script that turns a landscape streamer VOD clip into a
9:16 post-ready render. Not specific to GTA 6 — works for any gaming clip; the
GTA-specific parts are the compliance defaults (radio muting, gore gate).

`DESIGN.md` (Calm Premium) governs the AutoClip *app's* UI only — it doesn't
apply to TikTok/Shorts caption styling in exported clips, so this template
uses platform-standard bold-white/black-outline captions instead, which is
what performs on those platforms.

## Files

- `build_clip.py` — the template/preset. Run with a config JSON.
- `text_png.py` — renders caption/hook/credit text to transparent PNGs (Pillow).
- `example_config.json` — annotated config shape for both facecam source options.
- `demo_config_gameplay_only.json`, `demo_config_facecam_geometry_check.json` — the two test configs actually run (see below).
- `make_demo_words.py`, `demo_words.json` — one-off helper that built word-timing for the demo render from an existing SRT. Not part of the reusable template.
- `sample_output/demo_gameplay_only.mp4` — **the real sample render**, verified.
- `sample_output/facecam_mode_geometry_check.mp4` — a 6s mechanism check for the two-pane facecam layout (see "What wasn't tested" below).

## Why ffmpeg `overlay`+PNG instead of `drawtext`

This machine's ffmpeg (`brew install ffmpeg`, 8.0.1) isn't built with
libfreetype/libass, so `drawtext` and `subtitles` filters aren't available
(`No such filter: 'drawtext'`). Rather than require a specific ffmpeg build,
the template renders all text (hook, credits, captions) as transparent PNGs
with Pillow and composites them with the `overlay` filter, which is a core
filter present in every ffmpeg build. This is more portable, not less —
no action needed on Cutter's machine either way.

## What the template does

- 1080x1920 canvas.
- **mode: "facecam"** — top pane facecam, bottom pane gameplay, stacked with `vstack`. Two ways to feed it:
  - `source_path` + `facecam_crop` (x/y/w/h in source pixels) — the realistic case: one OBS-composited VOD where the webcam is already a corner PIP. The script crops that corner for the top pane and reframes the same source (cover-crop) for the bottom pane.
  - `facecam_path` + `gameplay_path` — two separate feeds, if Cutter/Scout can get a multi-track replay or a standalone webcam recording.
  - `facecam_height_ratio` (default 0.38) controls the top/bottom split.
- **mode: "gameplay_only"** — single pane, full-frame cover-crop to 9:16. Fallback for clips with no visible facecam.
- **Hook text**: first 2 seconds only, large bold text just under the credit badge, inside the safe zone.
- **Streamer credit**: persistent small badge, top-left, inside the safe zone (not above it).
- **Word-level captions**: grouped into 2-3 word chunks (`caption_words_per_chunk`), bottom-anchored but kept clear of the platform's bottom UI (caption/username/like-share rail). Captions don't start until the hook's 2s window ends, so the two never overlap.
- **Safe zones**: `SAFE_TOP = 230px`, `SAFE_BOTTOM = 320px` at 1080x1920 — approximate TikTok/Shorts/Reels UI keep-out (profile/sound icons up top; caption/username/action rail at the bottom). All text respects these.
- **Radio audio**: `radio_mute_windows` (list of `[start, end]` seconds) get hard-muted (not ducked — muting is the safer default given Rockstar's policy explicitly bars monetizing their in-game radio tracks, and there's Content-ID risk on top). There's no automatic radio detector; Cutter/Yuriy has to flag the windows by ear.
- **Gore gate**: `gore_check_passed` must be `true` in the config or the script refuses to render. This is a manual-review checkbox, not computer-vision gore detection — nothing in this repo can reliably detect gore automatically, so the mandatory "no heavy gore in first 7s" rule is enforced as a human sign-off gate instead.
- Output: H.264/yuv420p + AAC, 30fps, faststart — verified to decode cleanly, correct resolution, and has an audio track.

## How Cutter's raw clips feed in

1. Cutter cuts a VOD down to a clip-length file (whatever AutoClip/Cutter's normal output is — a `.mp4`, landscape or already in some working resolution).
2. Get word-level caption timestamps for that clip. Use AutoClip's own transcription step — `backend/utils/speech_recognizer.py` / the pipeline's step1-2 output — not a new transcriber. Export it (or adapt the pipeline's SRT output) into the `[{"word","start","end"}, ...]` shape this template reads (see `captions_words_json` in `example_config.json`). If only an SRT is available, there's a working example of turning whisper-style SRT entries into this shape in `make_demo_words.py`.
3. Decide facecam vs gameplay-only:
   - If the VOD has a visible webcam corner, note its pixel rect (x, y, w, h) once per streamer's overlay layout (it's usually consistent per streamer/scene) → `facecam_crop`.
   - If there's no cam, or Scout's source doesn't show one, use `mode: "gameplay_only"`.
4. Flag any in-game-radio windows by ear → `radio_mute_windows`.
5. Watch the first 7 seconds once → set `gore_check_passed: true` (or trim the clip to start after the flagged moment and re-check).
6. Fill in `hook_text` and `streamer_credit`, point `output_path` at `queue/edited/...`, run:
   ```
   python3 plans/gta6_edit_template/build_clip.py your_config.json
   ```
7. Log it per the usual `queue/edited.md` convention once `queue/` exists for this batch (it doesn't yet — this repo's `queue/` only gets created when the first real clip run starts).

Thumbnails: AutoClip already has an upload-kit thumbnail feature
(`backend/utils/thumbnail_generator.py`, used in `step6_video.py`) — use that
for the final submission kit rather than adding a second thumbnail path here;
out of scope for this template/render task.

## What was tested, and what wasn't

No streamer facecam gaming clip exists anywhere in this repo yet (checked
`/Users/yuriy/autoclip/output`, `data/projects/*`, `shorts-studio-sandbox/*` —
GTA 6 sources that do exist are a trailer and a non-facecam 30-min gameplay
video, both correctly excluded from testing per the "non-GTA" instruction).

- **`sample_output/demo_gameplay_only.mp4`** — real, full validation. Source: the already-cut, non-GTA "Suits" clip (`data/projects/cb68835a.../output/clips/1_...mp4`, 47s, 640x360 16:9). Ran the full pipeline: gameplay-only reframe to 1080x1920, hook text (0-2s), persistent credit badge, 25 word-level caption chunks (timing derived from the project's existing `raw/input.srt`, offset to the clip), and a mute-window audio pass. Verified: ffprobe shows 1080x1920 @ 30fps with an AAC audio stream, duration 47.1s, decodes end-to-end with zero errors (`ffmpeg ... -f null -`), and inspected actual frames — credit/hook/caption all land inside the intended safe zones with no overlap.
- **`sample_output/facecam_mode_geometry_check.mp4`** — mechanism check only, not a creative sample. Built from the same Suits clip, splitting it into two crops of itself (a corner standing in for "facecam", the full frame standing in for "gameplay") purely to prove the single-source facecam/gameplay split + `vstack` + text overlays work together correctly on a two-pane canvas. Confirmed 1080x1920, clean decode, correct pane stacking, text placement correct in both panes. This does **not** validate real facecam content (framing of an actual face, cam size/aspect against a real OBS layout) because none exists in the repo — that needs a real streamer facecam clip once Cutter/Scout has one, ideally before Nov 18.
- Not automated, by design: radio detection (manual), gore detection (manual gate), picking `facecam_crop` per streamer (one-time manual measurement per overlay layout).

## Open items for Yuriy / Showrunner

- Need one real streamer facecam VOD (even a non-GTA one) to validate the facecam composite against actual face framing before relying on it live during launch week.
- Confirm whether `facecam_height_ratio` (0.38) looks right once tested on a real cam, or whether per-streamer overlay sizes need their own ratio.

#!/usr/bin/env python3
"""
GTA 6 streamer-clip vertical edit template.

Reusable ffmpeg-driven preset for turning a landscape streamer VOD clip into a
9:16 post-ready render: facecam-top/gameplay-bottom (or a gameplay-only
fallback when there's no separate facecam feed), burned-in word-level
captions kept out of the TikTok/Shorts/Reels UI safe zones, a hook-text
overlay for the first 2 seconds, a persistent streamer-credit badge, and
in-game-radio audio handling.

Text is rendered as transparent PNGs (text_png.py) and composited with
ffmpeg's `overlay` filter rather than drawtext/subtitles, since those need
libfreetype/libass compiled into ffmpeg and this machine's build doesn't
have them. overlay is a core filter and works everywhere.

Usage:
    python3 build_clip.py config.json

See example_config.json for the config shape and README.md for how this
plugs into Cutter's output and AutoClip's transcription step.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from text_png import render_text_png

CANVAS_W = 1080
CANVAS_H = 1920

# TikTok / Shorts / Reels on-screen UI keep-out, in px at 1080x1920.
# Top: profile pic, follow/sound icons. Bottom: caption, username, like/share rail.
SAFE_TOP = 230
SAFE_BOTTOM = 320

CAPTION_FONTSIZE = 72
HOOK_FONTSIZE = 84
CREDIT_FONTSIZE = 40


def cover_crop_scale_filter(label_in, label_out, target_w, target_h):
    """CSS object-fit:cover — scale up to cover target box, then center-crop."""
    return (
        f"[{label_in}]scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
        f"crop={target_w}:{target_h}[{label_out}]"
    )


def build_caption_chunks(words, max_words_per_chunk=3):
    """Group word-level timestamps into short on-screen caption chunks."""
    chunks = []
    cur = []
    for w in words:
        cur.append(w)
        if len(cur) >= max_words_per_chunk:
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return [
        {"text": " ".join(w["word"] for w in c).upper(),
         "start": c[0]["start"], "end": c[-1]["end"]}
        for c in chunks
    ]


class Graph:
    """Small helper to build an ffmpeg -filter_complex graph with extra
    PNG overlay inputs, tracking input indices and filter labels."""

    def __init__(self, base_inputs):
        self.inputs = list(base_inputs)  # ["-i", path, ...] pairs already set up
        self.extra_inputs = []  # list of png paths, appended as further -i args
        self.parts = []
        self._label_n = 0

    def next_label(self):
        self._label_n += 1
        return f"v{self._label_n}"

    def add_png_input(self, path):
        idx = len(self.inputs) // 2 + len(self.extra_inputs)
        self.extra_inputs.append(path)
        return idx

    def overlay(self, cur_label, png_path, x, y, enable_expr=None):
        idx = self.add_png_input(png_path)
        out = self.next_label()
        en = f":enable='{enable_expr}'" if enable_expr else ""
        self.parts.append(f"[{cur_label}][{idx}:v]overlay=x={x}:y={y}{en}[{out}]")
        return out


def main():
    if len(sys.argv) != 2:
        print("usage: build_clip.py config.json", file=sys.stderr)
        sys.exit(1)

    cfg = json.loads(Path(sys.argv[1]).read_text())
    mode = cfg["mode"]
    gore_zone_end = 7.0

    if not cfg.get("gore_check_passed", False):
        raise SystemExit(
            "Refusing to render: config.gore_check_passed must be true after a "
            f"human reviews the first {gore_zone_end:.0f}s for heavy gore/dismemberment "
            "(YouTube monetization rule). This is a manual-review gate, not CV detection."
        )

    base_inputs = []
    audio_src = "0:a"
    if mode == "facecam":
        if "source_path" in cfg:
            # Common real case: one pre-composited OBS VOD with the webcam
            # already baked in as a corner PIP. facecam_crop picks that
            # corner out of the single source; the bottom pane reframes the
            # same source (cover-crop) for the gameplay view.
            base_inputs += ["-i", cfg["source_path"]]
            fc = cfg["facecam_crop"]
            face_src_filter = (
                f"[0:v]crop={fc['w']}:{fc['h']}:{fc['x']}:{fc['y']}[face_src]"
            )
            game_src_label = "0:v"
        else:
            # Separate facecam + gameplay feeds (e.g. a multi-track replay
            # or a dedicated webcam recording synced to the gameplay capture).
            base_inputs += ["-i", cfg["facecam_path"], "-i", cfg["gameplay_path"]]
            face_src_filter = None
            game_src_label = "1:v"
            audio_src = "1:a"
    elif mode == "gameplay_only":
        base_inputs += ["-i", cfg["gameplay_path"]]
    else:
        raise ValueError(f"unknown mode: {mode}")

    g = Graph(base_inputs)

    if mode == "facecam":
        face_ratio = cfg.get("facecam_height_ratio", 0.38)
        face_h = round(CANVAS_H * face_ratio)
        game_h = CANVAS_H - face_h
        if face_src_filter:
            g.parts.append(face_src_filter)
            g.parts.append(cover_crop_scale_filter("face_src", "face", CANVAS_W, face_h))
        else:
            g.parts.append(cover_crop_scale_filter("0:v", "face", CANVAS_W, face_h))
        g.parts.append(cover_crop_scale_filter(game_src_label, "game", CANVAS_W, game_h))
        g.parts.append("[face][game]vstack=inputs=2[stacked]")
        cur = "stacked"
    else:
        g.parts.append(cover_crop_scale_filter("0:v", "game", CANVAS_W, CANVAS_H))
        cur = "game"

    with tempfile.TemporaryDirectory(prefix="gta6_tpl_") as tmpdir:
        tmpdir = Path(tmpdir)

        # Credit badge sits at the top of the safe zone (not above it, which
        # would push it under the platform's own top UI icons).
        credit_bottom = SAFE_TOP
        credit = cfg.get("streamer_credit")
        if credit:
            png, w, h = render_text_png(
                credit, tmpdir / "credit.png", CREDIT_FONTSIZE,
                box=True, box_fill=(0, 0, 0, 130), max_text_w=900,
            )
            x = 30
            y = SAFE_TOP
            cur = g.overlay(cur, png, x, y)
            credit_bottom = y + h

        hook = cfg.get("hook_text")
        hook_end = 0.0
        if hook:
            png, w, h = render_text_png(
                hook.upper(), tmpdir / "hook.png", HOOK_FONTSIZE,
                box=True, box_fill=(0, 0, 0, 110), max_text_w=CANVAS_W - 120,
            )
            x = (CANVAS_W - w) // 2
            y = credit_bottom + 30
            cur = g.overlay(cur, png, x, y, "between(t,0,2)")
            hook_end = 2.0

        words_path = cfg.get("captions_words_json")
        if words_path:
            words = json.loads(Path(words_path).read_text())
            chunks = build_caption_chunks(words, cfg.get("caption_words_per_chunk", 3))
            caption_bottom_y = CANVAS_H - SAFE_BOTTOM - 180
            for i, c in enumerate(chunks):
                # Keep the big hook card clear of the chest-high word captions:
                # captions don't start until the hook window ends.
                start = max(c["start"], hook_end)
                end = max(c["end"], start + 0.05)
                if start >= c["end"]:
                    continue
                png, w, h = render_text_png(
                    c["text"], tmpdir / f"cap_{i:04d}.png", CAPTION_FONTSIZE,
                    box=False,
                )
                x = (CANVAS_W - w) // 2
                y = caption_bottom_y
                cur = g.overlay(cur, png, x, y,
                                 f"between(t,{start:.3f},{end:.3f})")

        g.parts.append(f"[{cur}]format=yuv420p[vout]")

        # Audio: hard-mute any flagged in-game-radio windows (Rockstar music
        # bars monetization + Content-ID risk). Safer default than a partial duck.
        mute_windows = cfg.get("radio_mute_windows", [])
        if mute_windows:
            expr = "+".join(f"between(t,{s},{e})" for s, e in mute_windows)
            g.parts.append(f"[{audio_src}]volume=0:enable='{expr}'[aout]")
        else:
            g.parts.append(f"[{audio_src}]anull[aout]")

        out_path = Path(cfg["output_path"])
        out_path.parent.mkdir(parents=True, exist_ok=True)

        extra_input_args = []
        for p in g.extra_inputs:
            extra_input_args += ["-i", p]

        trim_args = ["-t", str(cfg["max_duration"])] if cfg.get("max_duration") else []
        cmd = [
            "ffmpeg", "-y", *base_inputs, *extra_input_args,
            "-filter_complex", ";".join(g.parts),
            "-map", "[vout]", "-map", "[aout]", *trim_args,
            "-r", "30", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            str(out_path),
        ]
        print("Running ffmpeg with", len(g.extra_inputs), "text overlays ->", out_path)
        subprocess.run(cmd, check=True, cwd=str(Path(__file__).parent))

    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()

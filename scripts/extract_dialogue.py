#!/usr/bin/env python3
"""Extract on-screen dialogue (burned-in subtitles) from a video via the
Concentrate API (OpenAI-compatible gateway, vision models).

Concentrate proxies text and image input only - no audio routes - so this
reads subtitles straight off frames. Reads the working key from
data/settings.json (openai_api_key + openai_base_url); falls back to the
CONCENTRATE_API_KEY env var.

Usage:
    python3 scripts/extract_dialogue.py <video> [--out dialogue.json]
        [--interval 1.0] [--batch 10] [--model gpt-4o-mini]
        [--start 0] [--end None] [--width 720]
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_concentrate_credentials():
    settings_path = ROOT / "data" / "settings.json"
    key = base = None
    if settings_path.exists():
        try:
            s = json.loads(settings_path.read_text())
            key = s.get("openai_api_key") or None
            base = s.get("openai_base_url") or None
        except Exception:
            pass
    if not key:
        key = os.environ.get("CONCENTRATE_API_KEY")
    if not base:
        base = "https://api.concentrate.ai/v1/"
    return key, base.rstrip("/")


def extract_frames(video, tmpdir, interval, start, end, width):
    out = Path(tmpdir) / "f_%05d.jpg"
    cmd = ["ffmpeg", "-y", "-v", "error"]
    if start:
        cmd += ["-ss", str(start)]
    if end:
        cmd += ["-t", str(end - start)]
    cmd += ["-i", str(video), "-vf", f"fps={1 / interval},scale={width}:-2", "-q:v", "5", str(out)]
    subprocess.run(cmd, check=True)
    return sorted(Path(tmpdir).glob("f_*.jpg"))


def transcribe_batch(frames, offset, interval, key, base, model):
    content = []
    for i, f in enumerate(frames):
        b64 = base64.b64encode(f.read_bytes()).decode()
        content.append({"type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
        content.append({"type": "text",
                        "text": f"Image {offset + i} (t={round((offset + i) * interval, 2)}s)."})
    content.append({"type": "text", "text":
        "Each image is a frame of a GTA gameplay video with burned-in dialogue subtitles. "
        "For EVERY image index return a JSON object with:\n"
        "- \"text\": the on-screen subtitle transcribed exactly as written (preserve profanity), or empty string if none.\n"
        "- \"game\": a short punchy line (max 8 words, ALL CAPS) about WHAT IS HAPPENING IN THE GAME right now - "
        "the action, the stakes, the objective (e.g. \"COPS CLOSING IN\", \"SEAPLANE IN SIGHT\", \"ONE SHOT FROM DEAD\"). "
        "Ground it in what is actually on screen. Empty string only if nothing notable is happening.\n"
        "Reply with ONLY a JSON array: [{\"i\": <image index>, \"text\": <string>, \"game\": <string>}]"})
    body = {"model": model, "messages": [{"role": "user", "content": content}],
            "max_tokens": 2500, "temperature": 0}
    req = urllib.request.Request(
        f"{base}/chat/completions", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read())
    text = d["choices"][0]["message"]["content"]
    m = text.find("[")
    return json.loads(text[m:text.rfind("]") + 1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--out")
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--batch", type=int, default=10)
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float)
    ap.add_argument("--width", type=int, default=720)
    args = ap.parse_args()

    key, base = load_concentrate_credentials()
    if not key:
        sys.exit("No Concentrate key found (data/settings.json or CONCENTRATE_API_KEY)")

    with tempfile.TemporaryDirectory() as tmp:
        frames = extract_frames(args.video, tmp, args.interval, args.start, args.end, args.width)
        if not frames:
            sys.exit("No frames extracted")
        print(f"{len(frames)} frames @ {args.interval}s interval", file=sys.stderr)

        results = {}
        for off in range(0, len(frames), args.batch):
            chunk = frames[off:off + args.batch]
            for attempt in range(3):
                try:
                    for item in transcribe_batch(chunk, off, args.interval, key, base, args.model):
                        results[item["i"]] = {
                            "text": item.get("text", "").strip(),
                            "game": " ".join(item.get("game", "").strip().split()),
                        }
                    break
                except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError, KeyError) as e:
                    if attempt == 2:
                        raise
                    print(f"batch @{off} failed ({e}); retrying", file=sys.stderr)
                    time.sleep(5 * (attempt + 1))
            done = min(off + args.batch, len(frames))
            print(f"  {done}/{len(frames)} frames", file=sys.stderr)

    # collapse consecutive identical subtitle lines into timed segments,
    # keeping the game-context line seen at the end of each run
    segments = []
    for i in sorted(results):
        text, game = results[i]["text"], results[i]["game"]
        if not text:
            continue
        t = round(args.start + i * args.interval, 2)
        if segments and segments[-1]["text"] == text:
            segments[-1]["end"] = round(t + args.interval, 2)
            if game:
                segments[-1]["game"] = game
        else:
            segments.append({"start": t, "end": round(t + args.interval, 2),
                             "text": text, "game": game})

    out_path = Path(args.out) if args.out else Path(args.video).with_suffix(".dialogue.json")
    out_path.write_text(json.dumps({"video": str(args.video), "model": args.model,
                                    "segments": segments}, indent=2, ensure_ascii=False))
    print(f"{len(segments)} dialogue segments -> {out_path}")
    for s in segments:
        game = f"   [{s['game']}]" if s.get("game") else ""
        print(f"  {s['start']:>7.2f}-{s['end']:>7.2f}  {s['text']}{game}")


if __name__ == "__main__":
    main()

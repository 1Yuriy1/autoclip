#!/usr/bin/env python3
"""Build Shorts from a production sheet (like shorts_production_sheet.md):
ElevenLabs voiceover + gameplay b-roll + on-screen hook title -> ready kit.

Pipeline per short:
  1. Parse the sheet (markdown) for voiceover text, on-screen title,
     title options, hashtags, pinned comment, b-roll note.
  2. Synthesize the voiceover with ElevenLabs (needs ELEVENLABS_API_KEY in env
     or data/settings.json key 'elevenlabs_api_key'; pass --voice <id> to pick).
  3. Assemble a 1080x1920 Short: b-roll segments cut from the source gameplay
     video, cropped 9:16, trimmed to the voiceover length, hook title overlaid
     top of frame for the first 3 seconds, voiceover as the audio track.
  4. Write a ready kit: title options, hashtags, pinned comment, description.

Usage:
  python3 scripts/build_shorts.py --sheet queue/shorts_production/shorts_production_sheet.md \
      --source data/uploads/gta6_ztz_20261119.mp4 --out ready/2026-11-23/shorts_voiceover \
      [--only N01,S03] [--dry-run] [--pool-cache cache_dir]
"""
import argparse
import hashlib
import json
import math
import os
import random
import re
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TITLE_SECONDS = 3.0
SEG_LEN = 7.0
FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Helvetica Bold.ttf",
]
ELEVENLABS_TTS = "https://api.elevenlabs.io/v1/text-to-speech/{voice}"
DEFAULT_VOICE = "21m00Tcm4TlvDq8ikWAM"  # Rachel - swap with --voice


def parse_sheet(path):
    text = Path(path).read_text(encoding="utf-8")
    shorts = []
    blocks = re.split(r"^## ", text, flags=re.M)[1:]
    for block in blocks:
        m_id = re.match(r"([NS]\d+):", block)
        if not m_id:
            continue
        sid = m_id.group(1)
        title = re.search(r"\*\*On-screen title:\*\*\s*(.+)", block)
        opts = re.search(r"\*\*Title options:\*\*\s*(.+)", block)
        pinned = re.search(r"\*\*Pinned comment:\*\*\s*(.+)", block)
        tags = re.search(r"\*\*Hashtags:\*\*\s*(.+)", block)
        broll = re.search(r"\*\*B-roll and caption note:\*\*\s*(.+)", block)
        fences = re.findall(r"```\n(.*?)```", block, flags=re.S)
        voiceover = fences[-1].strip() if fences else None
        if not voiceover:
            print(f"  {sid}: no voiceover text found, skipping", file=sys.stderr)
            continue
        shorts.append({
            "id": sid,
            "title": title.group(1).strip() if title else sid,
            "title_options": [o.strip() for o in opts.group(1).split("/")] if opts else [],
            "pinned": pinned.group(1).strip() if pinned else "",
            "hashtags": tags.group(1).strip() if tags else "",
            "broll_note": broll.group(1).strip() if broll else "",
            "voiceover": voiceover,
            "words": len(voiceover.split()),
        })
    return shorts


def elevenlabs_key():
    key = os.environ.get("ELEVENLABS_API_KEY")
    if key:
        return key
    key_file = os.environ.get("ELEVENLABS_KEY_FILE")
    if key_file and Path(key_file).exists():
        return Path(key_file).read_text().strip()
    settings = ROOT / "data" / "settings.json"
    if settings.exists():
        try:
            return json.loads(settings.read_text()).get("elevenlabs_api_key") or None
        except Exception:
            return None
    return None


def synth_voiceover(text, out_mp3, voice, key):
    body = json.dumps({
        "text": text,
        "model_id": "eleven_flash_v2_5",
        "voice_settings": {"stability": 0.45, "similarity_boost": 0.75,
                           "style": 0.3, "use_speaker_boost": True},
    }).encode()
    req = urllib.request.Request(
        ELEVENLABS_TTS.format(voice=voice), data=body,
        headers={"xi-api-key": key, "Content-Type": "application/json",
                 "Accept": "audio/mpeg"})
    with urllib.request.urlopen(req, timeout=300) as r:
        out_mp3.write_bytes(r.read())


def ffprobe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def make_pool(source, cache, n=60):
    """Cut n evenly-spaced 9:16 segments from the source gameplay video."""
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    existing = sorted(cache.glob("pool_*.mp4"))
    if len(existing) >= n:
        return existing
    total = ffprobe_duration(source)
    step = (total - SEG_LEN - 30) / n
    segs = []
    for i in range(n):
        start = 15 + i * step
        out = cache / f"pool_{i:02d}.mp4"
        if not out.exists():
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}",
                            "-t", str(SEG_LEN), "-i", str(source),
                            "-vf", "crop=603:1072:658:0,scale=1080:1920",
                            "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "19",
                            "-pix_fmt", "yuv420p", str(out)], check=True)
        segs.append(out)
    return segs


def wrap_title(title, max_chars=14):
    words, lines, cur = title.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > max_chars and cur:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    lines.append(cur)
    return lines[:3]


def ensure_pil():
    try:
        import PIL  # noqa: F401
        return
    except ImportError:
        venv_py = ROOT / ".venv" / "bin" / "python"
        if venv_py.exists() and Path(sys.executable).resolve() != venv_py.resolve():
            os.execv(str(venv_py), [str(venv_py), str(Path(__file__).resolve()), *sys.argv[1:]])
        sys.exit("PIL required: run with .venv/bin/python")


def render_title_png(short, png_path):
    from PIL import Image, ImageDraw, ImageFont
    font_path = next((f for f in FONT_CANDIDATES if Path(f).exists()), None)
    img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, 92) if font_path else ImageFont.load_default(size=92)
    y = 220
    for line in wrap_title(short["title"]):
        draw.text((540, y), line, font=font, fill=(255, 255, 255, 255),
                  stroke_width=6, stroke_fill=(0, 0, 0, 255), anchor="ma")
        y += 104
    img.save(png_path)


def pick_segments(short_id, duration, pool):
    """Pick a distinct, shuffled set of b-roll segments for this short.

    Seeded by the short's own id so picks are stable across reruns but
    different from every other short in the batch (no shared opening clip).
    """
    rng = random.Random(int(hashlib.md5(short_id.encode()).hexdigest(), 16))
    n_needed = max(1, math.ceil(duration / SEG_LEN))
    order = list(range(len(pool)))
    rng.shuffle(order)
    picks = [order[i % len(order)] for i in range(n_needed)]
    return [pool[i] for i in picks]


def assemble(short, segments, voice_mp3, title_png, out_mp4, dry_run):
    duration = ffprobe_duration(voice_mp3) if voice_mp3 else min(
        8.0, max(4.0, short["words"] / 2.6))
    filters = []
    t, idx = 0.0, 0
    while t < duration - 0.05:
        take = min(SEG_LEN, duration - t)
        filters.append(f"[{idx}:v]trim=duration={take:.2f},setpts=PTS-STARTPTS[v{idx}]")
        t += take
        idx += 1
    joins = "".join(f"[v{i}]" for i in range(idx))
    filters.append(f"{joins}concat=n={idx}:v=1:a=0[cat]")
    next_input = idx
    if title_png:
        filters.append(
            f"[cat][{next_input}:v]overlay=0:0:enable='between(t,0,{TITLE_SECONDS})'[vout]")
        next_input += 1
    else:
        filters.append("[cat]null[vout]")
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for i in range(idx):
        cmd += ["-i", str(segments[i % len(segments)])]
    if title_png:
        cmd += ["-i", str(title_png)]
    if voice_mp3 and not dry_run:
        cmd += ["-i", str(voice_mp3)]
        filters.append(f"[{next_input}:a]anull[aout]")
    else:
        filters.append("anullsrc=r=44100:cl=stereo[dummy]")
        filters.append(f"[dummy]atrim=duration={duration:.2f}[aout]")
    cmd += ["-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            "-t", f"{duration + 0.1:.2f}", str(out_mp4)]
    subprocess.run(cmd, check=True)
    return duration


def write_kit(short, out_dir, duration, voice_used):
    desc = (f"{short['title_options'][0] if short['title_options'] else short['title']}\n\n"
            f"{short['voiceover'].splitlines()[0]}\n\n"
            f"{short['hashtags']}")
    kit = out_dir / f"{short['id']}_kit.md"
    kit.write_text(f"""# {short['id']}: {short['title']}

**Length:** {duration:.1f}s | **Words:** {short['words']} | **Voice:** {voice_used or 'TBD'}
**On-screen title:** {short['title']}
**Title options:** {' / '.join(short['title_options'])}
**Pinned comment:** {short['pinned']}
**Hashtags:** {short['hashtags']}
**B-roll note from sheet:** {short['broll_note']}

## Description (ready to paste)
{desc}
""", encoding="utf-8")
    return kit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--source", required=True, help="gameplay video for b-roll")
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", help="comma-separated ids, e.g. N01,S03")
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    ap.add_argument("--dry-run", action="store_true", help="skip ElevenLabs, use silent audio")
    ap.add_argument("--pool-cache", default="data/cache/shorts_broll_pool")
    args = ap.parse_args()

    shorts = parse_sheet(args.sheet)
    if args.only:
        wanted = set(args.only.split(","))
        shorts = [s for s in shorts if s["id"] in wanted]
    print(f"{len(shorts)} shorts in scope", file=sys.stderr)

    key = elevenlabs_key()
    if not args.dry_run and not key:
        sys.exit("No ElevenLabs key (env ELEVENLABS_API_KEY or settings elevenlabs_api_key)")

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    ensure_pil()
    pool = make_pool(args.source, args.pool_cache)

    for short in shorts:
        d = out_root / short["id"]
        d.mkdir(exist_ok=True)
        voice_mp3, voice_used = None, None
        if not args.dry_run:
            voice_mp3 = d / f"{short['id']}_voice.mp3"
            if not voice_mp3.exists():
                print(f"  {short['id']}: synthesizing voiceover ({short['words']} words)", file=sys.stderr)
                synth_voiceover(short["voiceover"], voice_mp3, args.voice, key)
            voice_used = f"ElevenLabs {args.voice}"
        title_png = d / f"{short['id']}_title.png"
        if not title_png.exists():
            render_title_png(short, title_png)
        out_mp4 = d / f"{short['id']}.mp4"
        est_duration = ffprobe_duration(voice_mp3) if voice_mp3 else min(
            8.0, max(4.0, short["words"] / 2.6))
        segments = pick_segments(short["id"], est_duration, pool)
        print(f"  {short['id']}: assembling {out_mp4.name} "
              f"(b-roll: {', '.join(s.stem for s in segments)})", file=sys.stderr)
        duration = assemble(short, segments, voice_mp3, title_png, out_mp4, args.dry_run)
        kit = write_kit(short, d, duration, voice_used)
        print(f"{short['id']}: {duration:.1f}s -> {out_mp4} ({kit.name})")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build voiceover Shorts, v2: word-by-word captions, b-roll matched to each line, fast cuts, a ducked music bed with
loudness at -14 LUFS, and an ending that loops into the hook.

What changed from build_shorts.py (which stays as it was):
  1. Captions: big centered captions, up to three words at a time, the spoken word in yellow. Timed from ElevenLabs'
     character timestamps, or with faster-whisper when reusing a voice file made without them.
  2. Matched b-roll: each shot is chosen from a hand-tagged scene catalog (data/broll_catalog/*.json) by the words
     spoken over it, instead of at random.
  3. Fast cuts: a new shot every 1.4 to 2.8 seconds, cut on phrase ends, with slow pans and a punch-in every third shot.
  4. Sound: an original music bed (scripts/make_music_bed.py) ducked under the voice, then loudness-normalized to -14 LUFS.
  5. Loop: the video ends on the last spoken word, with no tail, so a voiceover whose last line leads into the hook
     replays as one sentence.

Usage:
  python3 scripts/build_shorts_v2.py --sheet queue/Test2/test2_sheet.md --out ready/Test2 \
      --catalog data/broll_catalog/gta6_ztz_20261119.json --voice 6OzrBCQf8cjERkYgzSg8 [--only N05] \
      [--reuse-voice-dir ready/2026-11-23/shorts_voiceover]
"""
import argparse
import base64
import json
import random
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_shorts import ROOT, FONT_CANDIDATES, elevenlabs_key, ffprobe_duration, parse_sheet, render_title_png  # noqa: E402

TTS_WITH_TIMESTAMPS = "https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps"
W, H, FPS = 1080, 1920, 60
TITLE_SECONDS = 2.5
SHOT_MIN, SHOT_MAX = 1.4, 2.8
TAIL = 0.08  # seconds kept after the last word; any more breaks the loop
CAPTION_Y = 1180
YELLOW, WHITE, BLACK = (255, 212, 0, 255), (255, 255, 255, 255), (0, 0, 0, 255)

# Script words -> catalog tags. A word also matches a tag of the same name.
KEYWORDS = {
    "insane": ["insane", "highlight", "action"], "crazy": ["insane", "action"], "incredible": ["incredible", "highlight"],
    "viral": ["viral", "highlight"], "clip": ["highlight", "viral"], "clips": ["highlight", "viral"],
    "highlight": ["highlight", "action"], "reel": ["highlight"], "perfect": ["highlight", "epic"],
    "session": ["session", "normal"], "worse": ["normal", "boring"], "normal": ["normal", "everyday"],
    "everyday": ["everyday", "normal", "routine"], "experience": ["normal", "drive"],
    "vacations": ["vacation", "ocean", "scenic"], "vacation": ["vacation", "ocean"],
    "relationships": ["relationship", "phone", "call"], "job": ["job", "linkedin"], "linkedin": ["linkedin", "phone"],
    "minute": ["highlight"], "hours": ["hours", "routine", "waiting"], "hour": ["stuck", "waiting"],
    "stuck": ["stuck", "fence"], "fence": ["fence"], "posts": ["posts", "phone", "social"],
    "videos": ["funny", "fail"], "best": ["funny", "highlight"], "wrong": ["fail", "stuck"],
    "movie": ["movie", "cinematic"], "trailer": ["trailer", "cinematic", "epic"],
    "phone": ["phone"], "scrolling": ["scrolling", "phone"], "mission": ["action"], "chase": ["chase", "action"],
    "drive": ["drive"], "sunset": ["sunset"], "city": ["city"], "boring": ["boring"], "new": ["highlight"],
    # Week one, fading, routines (N06-N10)
    "honeymoon": ["vacation", "scenic", "highlight"], "screenshot": ["scenic", "sunset"], "doorways": ["scenic"],
    "explorer": ["scenic", "walking"], "explore": ["scenic", "walking"], "laundry": ["home", "chores"],
    "dishes": ["home", "chores"], "email": ["phone", "job"], "responsibility": ["home", "chores"],
    "settled": ["calm", "quiet"], "ride": ["drive", "cruise"], "fade": ["calm", "quiet"], "apartment": ["apartment", "home"],
    "chair": ["home"], "couch": ["home", "quiet"], "texting": ["phone", "text"], "talking": ["talking", "people"],
    "magical": ["scenic", "sunset"], "magic": ["scenic", "sunset"], "world": ["scenic", "city"],
    "missions": ["action"], "tourist": ["scenic", "vacation"], "park": ["scenic", "quiet"], "sun": ["sunset", "scenic"],
    "night": ["night"], "routine": ["routine"], "teeth": ["home", "routine"], "explosions": ["action", "chaos"],
    "food": ["home"], "scarce": ["quiet"], "light": ["sunset", "night"], "horizon": ["ocean", "sunset"],
    "years": ["sunset", "calm"], "school": ["walking"], "jobs": ["job", "work"], "moves": ["drive"],
    "heartbreak": ["call", "relationship"], "waited": ["waiting"],
    # Psychology set (S01-S10)
    "stealing": ["car", "drive"], "car": ["car", "drive"], "cars": ["car", "drive", "speed"], "guilt": ["chaos"],
    "bubble": ["scenic"], "rules": ["cop"], "poker": ["people", "talking"], "reckless": ["chaos", "speed"],
    "speedboat": ["boat", "speed"], "pier": ["boat", "dock"], "launching": ["boat", "speed"],
    "dog": ["funny"], "puppy": ["funny"], "puppies": ["funny", "fight"], "wrestling": ["fight"], "tackle": ["fight"],
    "chase": ["chase", "speed"], "chases": ["chase", "speed"], "chaos": ["chaos", "action"], "danger": ["action"],
    "dangerous": ["action", "chase"], "anger": ["fight", "chaos"], "angry": ["fight"], "mad": ["fight", "cop"],
    "punching": ["fight"], "steam": ["chaos"], "mission": ["action"], "win": ["highlight", "epic"],
    "reward": ["highlight"], "progress": ["action"], "hide": ["hiding", "stealth"], "shadow": ["hiding", "night"],
    "stranger": ["people"], "consequences": ["chaos", "cop"], "table": ["home"], "dessert": ["home"],
    "sorry": ["people", "walking"], "pedestrian": ["walking", "people"], "destruction": ["chaos", "action"],
    "passenger": ["car", "drive"], "movies": ["cinematic"], "dream": ["city", "money"], "money": ["money", "shop"],
    "success": ["city", "money"], "rent": ["rent", "apartment"], "plot": ["cinematic"], "crime": ["guns", "chaos"],
    "violence": ["guns", "chaos"], "violent": ["guns"], "killers": ["guns"], "actors": ["cinematic", "people"],
    "banks": ["money", "shop"], "role": ["cinematic"], "achievers": ["action"], "explorers": ["scenic"],
    "socializers": ["people", "talking"], "goblin": ["chaos"], "completionist": ["routine"],
    "screenshots": ["scenic", "sunset"], "lights": ["night", "city"], "criminal": ["guns", "chaos"],
    "underdog": ["people"], "villains": ["guns"], "jason": ["boat", "people"], "lucia": ["call", "relationship"],
    "system": ["city"], "listing": ["phone", "job"], "cop": ["cop", "chase"], "cops": ["cop", "chase"],
    "taxes": ["money", "routine"], "freedom": ["speed", "drive"], "toddler": ["funny"], "stop": ["cop"],
    "wild": ["speed", "chaos"], "path": ["drive", "road"], "goal": ["drive", "road"], "goals": ["action"],
    "move": ["action", "speed"], "alive": ["sunset"], "forward": ["sunset", "drive"], "next": ["drive"],
    "love": ["sunset", "scenic"], "exciting": ["action", "speed"], "special": ["sunset", "scenic"],
    "missed": ["quiet", "calm"], "practice": ["action"], "risky": ["chase", "speed"], "serious": ["cinematic"],
    "fiction": ["cinematic"], "pretend": ["cinematic"], "evil": ["night", "hiding"], "loudest": ["action"],
    "event": ["highlight"], "stages": ["highlight"], "week": ["routine"], "circle": ["city"],
}
# Lines that match nothing get calm footage that fits the short's overall mood, never a fight or a crash.
NEUTRAL = {"scenic", "calm", "drive", "city", "quiet", "cruise", "ocean", "sunset", "walking"}
UNSAFE = {"violent", "fight", "gunfight", "chaos", "guns"}


def synth_with_timestamps(text, voice, key, out_mp3, out_json):
    body = json.dumps({
        "text": text, "model_id": "eleven_flash_v2_5",
        "voice_settings": {"stability": 0.45, "similarity_boost": 0.75, "style": 0.3, "use_speaker_boost": True},
    }).encode()
    req = urllib.request.Request(TTS_WITH_TIMESTAMPS.format(voice=voice), data=body,
                                 headers={"xi-api-key": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        data = json.loads(r.read())
    out_mp3.write_bytes(base64.b64decode(data["audio_base64"]))
    out_json.write_text(json.dumps({"text": text, "alignment": data["alignment"]}))


def words_from_alignment(alignment):
    words, cur, start, end = [], "", None, None
    for ch, s, e in zip(alignment["characters"], alignment["character_start_times_seconds"],
                        alignment["character_end_times_seconds"]):
        if ch.isspace():
            if cur:
                words.append({"text": cur, "start": start, "end": end})
            cur, start = "", None
            continue
        if start is None:
            start = s
        cur, end = cur + ch, e
    if cur:
        words.append({"text": cur, "start": start, "end": end})
    return words


def words_from_whisper(mp3):
    from faster_whisper import WhisperModel
    model = WhisperModel("small.en", compute_type="int8")
    segments, _ = model.transcribe(str(mp3), word_timestamps=True)
    return [{"text": w.word.strip(), "start": w.start, "end": w.end} for s in segments for w in s.words]


def group_shots(words, duration):
    """Cut on phrase ends: a shot closes at punctuation once it is SHOT_MIN long, or before the next word would take it
    past SHOT_MAX."""
    shots, current, start = [], [], 0.0
    for i, w in enumerate(words):
        current.append(w)
        length = w["end"] - start
        if i + 1 >= len(words):
            break
        nxt = words[i + 1]["start"]
        too_long = words[i + 1]["end"] - start > SHOT_MAX and length >= 1.0
        if (length >= SHOT_MIN and re.search(r"[.,?!;:]$", w["text"])) or too_long:
            cut = (w["end"] + nxt) / 2
            shots.append({"start": start, "end": cut, "words": current})
            current, start = [], cut
    shots.append({"start": start, "end": duration, "words": current})
    # Fold a too-short last shot into the one before it.
    if len(shots) > 1 and shots[-1]["end"] - shots[-1]["start"] < 1.0:
        last = shots.pop()
        shots[-1]["end"], shots[-1]["words"] = last["end"], shots[-1]["words"] + last["words"]
    return shots


def shot_tags(shot):
    """The words themselves (exact), and the tags they suggest."""
    exact, suggested = set(), set()
    for w in shot["words"]:
        token = re.sub(r"[^a-z]", "", w["text"].lower())
        exact.add(token)
        suggested.update(KEYWORDS.get(token, []))
    return exact, suggested


def pick_scenes(shots, catalog, seed, mood=frozenset()):
    """Best tag overlap first, a word naming a tag counting double; scenes already used score lower, the previous shot's
    scene is skipped so every cut shows a change, and no stretch of footage is shown twice. A line that matches no scene
    gets neutral footage, leaning to the short's mood (the tags its whole script and b-roll note suggest)."""
    rng = random.Random(seed)
    used = {i: [] for i in range(len(catalog["scenes"]))}
    picks = []
    for shot in shots:
        need = shot["end"] - shot["start"]
        exact, suggested = shot_tags(shot)
        tags = exact | suggested
        matched_any = any(tags & set(scene["tags"]) for scene in catalog["scenes"])
        previous = picks[-1]["scene"] if picks else None
        scored = []
        for i, scene in enumerate(catalog["scenes"]):
            scene_tags = set(scene["tags"])
            score = 2 * len(exact & scene_tags) + len(suggested & scene_tags - exact) - 0.75 * len(used[i])
            if not matched_any:
                score += (1.5 if scene_tags & NEUTRAL else 0) - (5 if scene_tags & UNSAFE else 0)
                score += 0.3 * len(mood & scene_tags)
            score += rng.random() * 0.1 - (100 if i == previous else 0)
            scored.append((score, i))
        for score, i in sorted(scored, reverse=True):
            scene = catalog["scenes"][i]
            offset = free_offset(scene, used[i], need, rng)
            if offset is not None:
                used[i].append((offset, offset + need))
                picks.append({"scene": i, "at": offset, "score": round(score, 2),
                              "matched": sorted(tags & set(scene["tags"]))})
                break
    return picks


def free_offset(scene, taken, need, rng):
    candidates = []
    t = scene["start"]
    while t + need <= scene["end"]:
        if all(t + need <= a or t >= b for a, b in taken):
            candidates.append(t)
        t += 0.5
    return rng.choice(candidates) if candidates else None


def render_video(shots, picks, catalog, out_mp4):
    source = ROOT / catalog["source"]
    cmd, filters = ["ffmpeg", "-y", "-v", "error"], []
    big_w, big_h = int(W * 1.12) // 2 * 2, int(H * 1.12) // 2 * 2
    for n, (shot, pick) in enumerate(zip(shots, picks)):
        dur = shot["end"] - shot["start"]
        cmd += ["-ss", f"{pick['at']:.2f}", "-t", f"{dur + 0.05:.3f}", "-i", str(source)]
        base = f"[{n}:v]{catalog['crop']},fps={FPS},scale={big_w}:{big_h},setsar=1"
        dx, dy = big_w - W, big_h - H
        if n % 3 == 2:  # punch-in: a tighter, still frame
            move = f"scale={int(big_w * 1.1) // 2 * 2}:{int(big_h * 1.1) // 2 * 2},crop={W}:{H}"
        else:  # slow pan, alternating direction
            sign = "+" if n % 2 == 0 else "-"
            move = f"crop={W}:{H}:x='{dx / 2}{sign}{dx / 2}*(t/{dur:.3f}-0.5)':y='{dy / 2}'"
        filters.append(f"{base},{move},setsar=1,trim=duration={dur:.3f},setpts=PTS-STARTPTS[v{n}]")
    filters.append("".join(f"[v{n}]" for n in range(len(shots))) + f"concat=n={len(shots)}:v=1:a=0[vout]")
    cmd += ["-filter_complex", ";".join(filters), "-map", "[vout]", "-an",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", str(out_mp4)]
    subprocess.run(cmd, check=True)


def caption_chunks(words):
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) == 3 or re.search(r"[.,?!;:]$", w["text"]):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def caption_font(size):
    from PIL import ImageFont
    for path in ["/System/Library/Fonts/Supplemental/Arial Black.ttf", *FONT_CANDIDATES]:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def render_caption(chunk, active, png):
    from PIL import Image, ImageDraw
    labels = [re.sub(r"[.,;:]$", "", w["text"]).upper() for w in chunk]
    size = 92
    while True:
        font = caption_font(size)
        space = font.getlength(" ")
        widths = [font.getlength(t) for t in labels]
        if sum(widths) + space * (len(labels) - 1) <= 960 or size <= 56:
            break
        size -= 4
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    x = (W - (sum(widths) + space * (len(labels) - 1))) / 2
    for i, (label, width) in enumerate(zip(labels, widths)):
        draw.text((x, CAPTION_Y), label, font=font, fill=YELLOW if i == active else WHITE,
                  stroke_width=9, stroke_fill=BLACK, anchor="lm")
        x += width + space
    img.save(png)


def render_captions(words, duration, work):
    """Caption frames as a concat list of transparent PNGs, each held until the next word starts."""
    blank = work / "cap_blank.png"
    from PIL import Image
    Image.new("RGBA", (W, H), (0, 0, 0, 0)).save(blank)
    entries, t = [], 0.0
    for c, chunk in enumerate(caption_chunks(words)):
        for i, w in enumerate(chunk):
            if w["start"] > t + 0.01 and i == 0:
                entries.append((blank, w["start"] - t))
                t = w["start"]
            png = work / f"cap_{c:03d}_{i}.png"
            render_caption(chunk, i, png)
            if i + 1 < len(chunk):
                until = chunk[i + 1]["start"]
            else:
                following = [x for x in words if x["start"] > w["start"]]
                until = min(following[0]["start"], w["end"] + 0.5) if following else duration
            entries.append((png, max(0.02, until - t)))
            t = until
    if t < duration:
        entries.append((blank, duration - t))
    listing = work / "captions.ffconcat"
    lines = ["ffconcat version 1.0"]
    for png, d in entries:
        lines += [f"file '{png}'", f"duration {d:.3f}"]
    lines.append(f"file '{entries[-1][0]}'")
    listing.write_text("\n".join(lines) + "\n")
    return listing


LOUDNESS = "I=-14:TP=-1.5:LRA=11"


def mix_audio(voice, music, duration, out_wav):
    """Voice over the music bed, the bed ducked while the voice speaks, then two-pass loudness normalization to -14 LUFS
    (one pass undershoots on a short clip)."""
    mix = (f"[0:a]atrim=0:{duration:.3f},asetpts=PTS-STARTPTS,aresample=44100,aformat=channel_layouts=stereo,asplit=2[vo][key];"
           "[1:a]volume=0.16,aresample=44100[bed];"
           "[bed][key]sidechaincompress=threshold=0.02:ratio=6:attack=15:release=350[ducked];"
           "[vo][ducked]amix=inputs=2:normalize=0:duration=first")
    inputs = ["-i", str(voice), "-i", str(music)]
    probe = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", *inputs, "-filter_complex",
                            f"{mix},loudnorm={LOUDNESS}:print_format=json", "-f", "null", "-"],
                           capture_output=True, text=True, check=True).stderr
    m = json.loads(probe[probe.rindex("{"):probe.rindex("}") + 1])
    second = (f"loudnorm={LOUDNESS}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
              f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", f"{mix},{second},aresample=44100",
                    str(out_wav)], check=True)


def finish(video, captions, title_png, voice, music, duration, out_mp4):
    audio = Path(video).with_name("mix.wav")
    mix_audio(voice, music, duration, audio)
    filters = [
        f"[1:v]format=rgba,fps={FPS}[cap]",
        "[0:v][cap]overlay=0:0:shortest=0[v1]",
        f"[v1][2:v]overlay=0:0:enable='between(t,0,{TITLE_SECONDS})'[vout]",
    ]
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(video), "-f", "concat", "-safe", "0", "-i", str(captions),
        "-loop", "1", "-i", str(title_png), "-i", str(audio),
        "-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "3:a", "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-movflags", "+faststart", str(out_mp4)], check=True)


def write_kit(short, out_dir, duration, shots, picks, catalog, words_source):
    rows = "\n".join(
        f"| {s['start']:.1f}-{s['end']:.1f}s | {' '.join(w['text'] for w in s['words'])} | "
        f"{catalog['scenes'][p['scene']]['start'] + 0:.0f}s scene, at {p['at']:.1f}s | {', '.join(p['matched']) or 'no match: calm footage for the mood'} |"
        for s, p in zip(shots, picks))
    kit = out_dir / f"{short['id']}_kit.md"
    kit.write_text(f"""# {short['id']} (v2): {short['title']}

**Length:** {duration:.1f}s | **Shots:** {len(shots)} (avg {duration / len(shots):.1f}s) | **Caption timing:** {words_source}
**Title options:** {' / '.join(short['title_options'])}
**Pinned comment:** {short['pinned']}
**Hashtags:** {short['hashtags']}

## Description (ready to paste)
{short['title_options'][0] if short['title_options'] else short['title']}

{short['voiceover'].splitlines()[0]}

{short['hashtags']}

## Shot list
| Time | Words | Footage | Matched on |
|---|---|---|---|
{rows}
""")
    return kit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--voice", required=True)
    ap.add_argument("--music", default="data/music/bed_lofi_01.wav")
    ap.add_argument("--only", default="")
    ap.add_argument("--reuse-voice-dir", default="", help="Use <dir>/<ID>/<ID>_voice.mp3 when its text is unchanged")
    args = ap.parse_args()
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    catalog = json.loads((ROOT / args.catalog).read_text())
    music = ROOT / args.music
    if not music.exists():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_music_bed.py"), "--out", str(music)], check=True)
    for short in parse_sheet(ROOT / args.sheet):
        if only and short["id"] not in only:
            continue
        out_dir = ROOT / args.out / short["id"]
        out_dir.mkdir(parents=True, exist_ok=True)
        voice_mp3, align_json = out_dir / f"{short['id']}_voice.mp3", out_dir / f"{short['id']}_alignment.json"
        reused = Path(args.reuse_voice_dir) / short["id"] / f"{short['id']}_voice.mp3" if args.reuse_voice_dir else None
        cached = align_json.exists() and json.loads(align_json.read_text())["text"] == short["voiceover"]
        if cached:
            words, source = words_from_alignment(json.loads(align_json.read_text())["alignment"]), "ElevenLabs timestamps"
        elif reused and reused.exists():
            voice_mp3 = reused
            words, source = words_from_whisper(voice_mp3), "faster-whisper on the existing voice file"
        else:
            key = elevenlabs_key()
            if not key:
                sys.exit("No ElevenLabs key: set ELEVENLABS_API_KEY")
            print(f"{short['id']}: synthesizing voice with timestamps")
            synth_with_timestamps(short["voiceover"], args.voice, key, voice_mp3, align_json)
            words, source = words_from_alignment(json.loads(align_json.read_text())["alignment"]), "ElevenLabs timestamps"
        duration = min(ffprobe_duration(voice_mp3), words[-1]["end"] + TAIL)
        shots = group_shots(words, duration)
        mood = set()
        for token in re.findall(r"[a-z]+", (short["voiceover"] + " " + short["broll_note"]).lower()):
            mood.update(KEYWORDS.get(token, []))
        picks = pick_scenes(shots, catalog, seed=short["id"], mood=frozenset(mood - UNSAFE))
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            title_png = out_dir / f"{short['id']}_title.png"
            render_title_png(short, title_png)
            print(f"{short['id']}: {len(shots)} shots over {duration:.1f}s, rendering")
            render_video(shots, picks, catalog, work / "cut.mp4")
            captions = render_captions(words, duration, work)
            finish(work / "cut.mp4", captions, title_png, voice_mp3, music, duration, out_dir / f"{short['id']}.mp4")
        kit = write_kit(short, out_dir, duration, shots, picks, catalog, source)
        print(f"{short['id']}: {duration:.1f}s -> {out_dir / (short['id'] + '.mp4')} ({kit.name})")


if __name__ == "__main__":
    main()

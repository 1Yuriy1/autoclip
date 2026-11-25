"""Burn clip-relative captions using portable PNG overlays (no libass required)."""
import re
import subprocess
import tempfile
from pathlib import Path

import pysrt
from PIL import Image, ImageDraw, ImageFont

from .ffmpeg_utils import get_ffmpeg_path, get_ffprobe_path


def clip_cues(srt_path, start, duration):
    cues = []
    for sub in pysrt.open(str(srt_path), encoding='utf-8-sig'):
        begin = max(0.0, sub.start.ordinal / 1000 - start)
        end = min(duration, sub.end.ordinal / 1000 - start)
        text = re.sub(r'<[^>]+>', '', sub.text).replace('\n', ' ').strip()
        text = re.sub(r'>>\s*', '', text).strip()
        if end > begin and text:
            cues.append([begin, end, text])
    cues.sort(key=lambda cue: cue[0])
    # Rolling source captions often overlap; show the latest cue without stacking.
    for current, following in zip(cues, cues[1:]):
        current[1] = min(current[1], following[0])
    return [cue for cue in cues if cue[1] > cue[0]]


def burn_captions(video_path, srt_path, start=0.0):
    """Atomically replace a clip only after a successful caption render."""
    import json
    video_path = Path(video_path).resolve()
    probe = subprocess.run([get_ffprobe_path(), '-v', 'error', '-show_streams',
                            '-show_format', '-of', 'json', str(video_path)],
                           capture_output=True, text=True, check=True)
    info = json.loads(probe.stdout)
    stream = next(s for s in info['streams'] if s['codec_type'] == 'video')
    width, height = stream['width'], stream['height']
    duration = float(info['format']['duration'])
    cues = clip_cues(srt_path, start, duration)
    if not cues:
        return False
    size = max(18, round(width * 0.045))
    font = None
    for name in ('/System/Library/Fonts/Supplemental/Arial Bold.ttf',
                 '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 'Arial.ttf'):
        try:
            font = ImageFont.truetype(name, size)
            break
        except OSError:
            pass
    if font is None:
        font = ImageFont.load_default(size=size)
    band_height = round(height * 0.30)
    with tempfile.TemporaryDirectory(prefix='captions-', dir=video_path.parent) as tmp:
        tmp = Path(tmp)
        entries = []
        position = 0.0

        def frame(text, seconds):
            if seconds <= 0:
                return
            canvas = Image.new('RGBA', (width, band_height))
            draw = ImageDraw.Draw(canvas)
            lines, line = [], ''
            for word in text.split():
                candidate = (line + ' ' + word).strip()
                if draw.textlength(candidate, font=font) > width * 0.84 and line:
                    lines.append(line)
                    line = word
                else:
                    line = candidate
            if line:
                lines.append(line)
            label = '\n'.join(lines)
            draw.multiline_text((width / 2, band_height / 2), label, font=font,
                                anchor='mm', align='center', fill='white',
                                stroke_width=max(2, size // 14), stroke_fill='black', spacing=5)
            filename = f'{len(entries)}.png'
            canvas.save(tmp / filename)
            entries.append((filename, seconds))

        for begin, end, text in cues:
            frame('', begin - position)
            frame(text, end - begin)
            position = end
        frame('', duration - position)
        manifest = ''.join(f"file '{name}'\nduration {seconds:.6f}\n" for name, seconds in entries)
        manifest += f"file '{entries[-1][0]}'\n"
        (tmp / 'frames.txt').write_text(manifest)
        output = tmp / 'captioned.mp4'
        subprocess.run([
            get_ffmpeg_path(), '-v', 'error', '-i', str(video_path),
            '-f', 'concat', '-safe', '0', '-i', 'frames.txt',
            '-filter_complex', f'[0:v][1:v]overlay=0:{round(height * 0.62)}:eof_action=pass[v]',
            '-map', '[v]', '-map', '0:a?', '-c:v', 'libx264', '-preset', 'veryfast',
            '-crf', '20', '-pix_fmt', 'yuv420p', '-c:a', 'copy', '-t', str(duration),
            '-movflags', '+faststart', '-y', str(output)
        ], cwd=tmp, capture_output=True, text=True, check=True)
        output.replace(video_path)
    return True

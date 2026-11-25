"""Assemble timestamped episode footage under a new narrated story."""
import math
import shutil
from .media import (FFMPEG, asset_path, probe, timeline, narration, align_audio,
                    burn_clip_captions, run, clean)


def scene_captions(scenes):
    cues = []
    offset = 0
    for scene in scenes:
        words = clean(scene.get('text', '')).split()
        groups = [words[i:i + 5] for i in range(0, len(words), 5)]
        position = offset
        for group in groups:
            span = scene['duration'] * len(group) / len(words)
            cues.append({'start': position, 'end': position + span, 'text': ' '.join(group)})
            position += span
        offset += scene['duration']
    return cues


def render_recap(project, job, out, width=720):
    source = asset_path(project['sourceId'])
    info = probe(source)
    scenes = timeline(project)
    duration = project['duration']
    height = width * 16 // 9
    fps = 24
    # Rounding cumulative boundaries avoids duration drift at scene joins.
    total_frames = round(duration * fps)
    boundary = 0
    elapsed = 0
    for scene in scenes:
        elapsed += scene['duration']
        next_boundary = min(total_frames, round(elapsed * fps))
        scene['duration'] = (next_boundary - boundary) / fps
        boundary = next_boundary
        if scene['start'] < 0 or scene['end'] > info['duration'] + .05:
            raise ValueError('A recap footage range extends past the source video')

    audio = narration(project, job, duration, scenes)
    cues = scene_captions(scenes)
    if audio and project.get('alignCaptions', True) and project.get('captions') != 'none':
        aligned = align_audio(audio, job)
        if aligned:
            cues = aligned

    parts = []
    for i, scene in enumerate(scenes):
        job.progress(25 + i / len(scenes) * 45, 'Cutting ' + scene.get('title', f'story beat {i + 1}'))
        seconds = scene['duration']
        available = scene['end'] - scene['start']
        # Keep footage at normal speed. A short selection holds its final frame;
        # a long selection uses its opening, and the editor exposes exact trims.
        take = min(seconds, available)
        center = max(0, min(1, float(scene.get('cropX', project.get('cropX', .5)))))
        if project.get('layout', 'blur_pad') == 'blur_pad':
            graph = (f'[0:v]split[b][f];[b]scale={width}:{height}:force_original_aspect_ratio=increase,'
                     f'crop={width}:{height},gblur=sigma=20[b2];'
                     f'[f]scale={width}:{height}:force_original_aspect_ratio=decrease[f2];'
                     '[b2][f2]overlay=(W-w)/2:(H-h)/2')
        else:
            graph = (f'[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,'
                     f'crop={width}:{height}:(iw-ow)*{center}:(ih-oh)/2')
        graph += f',setsar=1,fps={fps},tpad=stop_mode=clone:stop_duration={seconds}[v]'
        part = job.temp / f'recap-{i}.mp4'
        run([FFMPEG, '-v', 'error', '-ss', str(scene['start']), '-t', str(take),
             '-i', str(source), '-filter_complex', graph, '-map', '[v]', '-an',
             '-frames:v', str(round(seconds * fps)), '-c:v', 'libx264', '-preset', 'veryfast',
             '-crf', '23', '-threads', '2', '-pix_fmt', 'yuv420p', '-y', str(part)], job)
        parts.append(part)

    manifest = job.temp / 'recap-cuts.txt'
    manifest.write_text(''.join(f"file '{p.name}'\n" for p in parts))
    silent = job.temp / 'recap-silent.mp4'
    run([FFMPEG, '-v', 'error', '-f', 'concat', '-safe', '0', '-i', str(manifest),
         '-c', 'copy', '-t', str(duration), '-y', str(silent)], job)
    for part in parts:
        part.unlink(missing_ok=True)

    mixed = job.temp / 'recap-mixed.mp4'
    job.progress(78, 'Adding recap narration')
    if audio:
        args = [FFMPEG, '-v', 'error', '-i', str(silent), '-i', str(audio)]
        if project.get('musicId'):
            gain = max(0, min(.5, float(project.get('musicVolume', .12))))
            args += ['-stream_loop', '-1', '-i', str(asset_path(project['musicId'])),
                     '-filter_complex', f'[1:a]apad,asplit=2[voice][control];[2:a]volume={gain}[music];'
                     '[music][control]sidechaincompress=threshold=0.025:ratio=8:attack=20:release=350[duck];'
                     '[voice][duck]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[a]',
                     '-map', '0:v', '-map', '[a]']
        else:
            args += ['-map', '0:v', '-map', '1:a', '-af', 'apad,loudnorm=I=-16:TP=-1.5:LRA=11']
        run(args + ['-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k', '-t', str(duration),
                    '-movflags', '+faststart', '-y', str(mixed)], job)
    else:
        shutil.move(silent, mixed)
    job.progress(86, 'Burning recap subtitles')
    if cues and project.get('captions') != 'none':
        burn_clip_captions(mixed, cues, project, job, out, width)
    else:
        shutil.move(mixed, out)
    return cues

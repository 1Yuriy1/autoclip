"""Import a single public YouTube video for an episode recap."""
import math
import re
import shutil
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .media import Cancelled, FFMPEG, parse_srt, probe, run
from .store import DATA, register, require_space, uid

MAX_VIDEO_BYTES = 1536 * 1024**2
MAX_EPISODE_SECONDS = 4 * 60 * 60
VIDEO_EXTENSIONS = {'mp4', 'mkv', 'webm', 'mov'}


def validate_youtube_url(value):
    """Return one canonical watch URL; never hand arbitrary URLs to yt-dlp."""
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError('Paste a YouTube video link.')
    try:
        parsed = urlsplit(value.strip())
        if (parsed.scheme not in {'http', 'https'} or parsed.username or parsed.password
                or parsed.port is not None):
            raise ValueError()
        host = (parsed.hostname or '').lower()
        query = parse_qs(parsed.query, keep_blank_values=True)
        if 'list' in query or 'playlist' in query:
            raise ValueError('Use a single episode video link without a playlist.')
        if host == 'youtu.be':
            video_id = parsed.path.strip('/')
        elif host in {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'}:
            if parsed.path.rstrip('/') == '/watch':
                ids = query.get('v', [])
                video_id = ids[0] if len(ids) == 1 else ''
            else:
                match = re.fullmatch(r'/(?:shorts|embed|live)/([\w-]{11})/?', parsed.path, re.ASCII)
                video_id = match.group(1) if match else ''
        else:
            raise ValueError()
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
            raise ValueError()
    except (ValueError, TypeError) as error:
        if 'playlist' in str(error):
            raise
        raise ValueError('Use a valid youtube.com or youtu.be video link.') from None
    return f'https://www.youtube.com/watch?v={video_id}'


youtube_url = validate_youtube_url


def _estimate_bytes(info):
    formats = info.get('requested_formats') or [info]
    estimate = 0
    for fmt in formats:
        known = fmt.get('filesize') or fmt.get('filesize_approx')
        if known:
            estimate += max(0, int(known))
        elif fmt.get('tbr'):
            estimate += int(float(fmt['tbr']) * 125 * float(info['duration']))
    return estimate or int(float(info['duration']) * 180000)


class _QuietLogger:
    def debug(self, message): pass
    def info(self, message): pass
    def warning(self, message): pass
    def error(self, message): pass


def _download_error(error):
    detail = str(error).lower()
    if any(word in detail for word in ('sign in', 'private video', 'members-only', 'premium', 'age-restricted', 'not a bot')):
        return 'YouTube requires access or verification for this video. Upload the episode file instead.'
    if any(word in detail for word in ('403', '429', 'unavailable', 'blocked', 'removed')):
        return 'YouTube could not provide this video. Try another public episode link or upload the file.'
    if 'space' in detail or 'file too large' in detail:
        return 'There is not enough free space to download this episode. Free disk space or upload a smaller file.'
    return 'The YouTube download failed. Retry or upload the episode file instead.'


def _captions(ydl_class, info, directory, job):
    available = dict(info.get('automatic_captions') or {})
    available.update(info.get('subtitles') or {})
    languages = [key for key in available if key == 'en' or key.startswith('en-')]
    languages.sort(key=lambda key: (key not in (info.get('subtitles') or {}), key != 'en', key != 'en-orig', key))
    if not languages:
        return []
    opts = {
        'skip_download': True, 'quiet': True, 'no_warnings': True, 'logger': _QuietLogger(),
        'writesubtitles': True, 'writeautomaticsub': True, 'subtitleslangs': languages[:1],
        'subtitlesformat': 'srt/vtt/best', 'ignoreerrors': True,
        'outtmpl': str(directory / 'captions.%(ext)s'), 'socket_timeout': 20,
        'retries': 1, 'fragment_retries': 1,
        'progress_hooks': [lambda data: job.check()],
    }
    try:
        job.check()
        with ydl_class(opts) as downloader:
            downloader.process_ie_result(dict(info), download=True)
        job.check()
        paths = sorted(directory.glob('captions.*.srt'))
        if not paths:
            for source in sorted(directory.glob('captions.*.vtt')):
                output = source.with_suffix('.srt')
                run([FFMPEG, '-v', 'error', '-i', str(source), '-y', str(output)], job, timeout=60)
                paths.append(output)
        if paths:
            cues = parse_srt(paths[0].read_text(encoding='utf-8-sig'))
            # Auto captions can repeat a whole line in adjacent rolling cues.
            deduped = []
            for cue in cues:
                if deduped and cue['text'] == deduped[-1]['text'] and cue['start'] <= deduped[-1]['end'] + .1:
                    deduped[-1]['end'] = max(deduped[-1]['end'], cue['end'])
                else:
                    deduped.append(cue)
            return deduped
    except Cancelled:
        raise
    except Exception:
        job.check()  # A caption failure should fall back to local transcription.
    return []


def import_youtube(url, job):
    """Download video/captions into sandbox storage and return the saved asset."""
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError

    canonical = youtube_url(url)
    directory = Path(job.temp) / 'youtube'
    directory.mkdir(parents=True, exist_ok=True)
    destination = None
    completed = False
    last_update = [0.0]
    downloaded = {}

    def progress(data):
        job.check()
        if data.get('status') not in {'downloading', 'finished'}:
            return
        current = int(data.get('downloaded_bytes') or 0)
        total = int(data.get('total_bytes') or data.get('total_bytes_estimate') or current)
        downloaded[str(data.get('filename', 'video'))] = current
        if sum(downloaded.values()) > MAX_VIDEO_BYTES or total > MAX_VIDEO_BYTES:
            raise ValueError('This episode exceeds the 1.5 GB download limit. Upload a smaller file.')
        now = time.monotonic()
        if now - last_update[0] >= .8 or data['status'] == 'finished':
            require_space(max(16 * 1024**2, total - current) + 30 * 1024**2)
            job.progress(5 + min(16, current / max(1, total) * 16), 'Downloading episode from YouTube')
            last_update[0] = now

    def postprocess(data):
        job.check()
        if data.get('status') == 'started':
            require_space(sum(downloaded.values()) + 30 * 1024**2)
            job.progress(22, 'Preparing the downloaded episode')

    opts = {
        'format': 'bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/bv*[height<=720]+ba/b[height<=720]',
        'merge_output_format': 'mp4', 'outtmpl': str(directory / 'source.%(ext)s'),
        'noplaylist': True, 'quiet': True, 'no_warnings': True, 'logger': _QuietLogger(),
        'socket_timeout': 20, 'retries': 2, 'fragment_retries': 2, 'extractor_retries': 1,
        'max_filesize': MAX_VIDEO_BYTES, 'progress_hooks': [progress],
        'postprocessor_hooks': [postprocess], 'ffmpeg_location': FFMPEG,
    }
    try:
        job.check()
        job.progress(2, 'Reading YouTube episode information')
        require_space(60 * 1024**2)
        with YoutubeDL(opts) as downloader:
            info = downloader.extract_info(canonical, download=False)
            job.check()
            if not info or info.get('_type', 'video') != 'video' or info.get('entries') is not None:
                raise ValueError('Use a single episode video link.')
            if info.get('is_live') or info.get('live_status') in {'is_live', 'is_upcoming'}:
                raise ValueError('Use a completed episode, not an ongoing or upcoming live stream.')
            duration = float(info.get('duration') or 0)
            if not math.isfinite(duration) or not 1 <= duration <= MAX_EPISODE_SECONDS:
                raise ValueError('Use a completed video between 1 second and 4 hours long.')
            estimated = _estimate_bytes(info)
            if estimated > MAX_VIDEO_BYTES:
                raise ValueError('This episode exceeds the 1.5 GB download limit. Upload a smaller file.')
            require_space(int(estimated * 2.1) + 30 * 1024**2)
            downloaded_info = downloader.process_ie_result(dict(info), download=True)
        job.check()
        paths = [directory / ('source.' + ext) for ext in sorted(VIDEO_EXTENSIONS)]
        paths = [path for path in paths if path.is_file()]
        if not paths:
            raise ValueError('YouTube did not return a downloadable video. Upload the episode file instead.')
        source = max(paths, key=lambda path: path.stat().st_size)
        if source.stat().st_size > MAX_VIDEO_BYTES:
            raise ValueError('This episode exceeds the 1.5 GB download limit. Upload a smaller file.')
        media = probe(source)
        if not any(stream.get('codec_type') == 'video' for stream in media['streams']) or media['duration'] <= 0:
            raise ValueError('The download did not contain a readable video.')
        job.progress(23, 'Reading available episode captions')
        cues = _captions(YoutubeDL, downloaded_info or info, directory, job)
        job.check()
        destination = DATA / 'assets' / (uid() + source.suffix)
        shutil.move(str(source), str(destination))
        job.progress(25, 'YouTube episode imported')
        asset = register(destination, name=str(info.get('title') or 'YouTube episode')[:180],
                         mediaType='video', **media, cues=cues, sourceUrl=canonical,
                         sourceType='youtube', youtubeId=info.get('id'),
                         transcriptTiming='youtube-captions' if cues else None)
        completed = True
        return asset
    except DownloadError as error:
        job.check()
        raise ValueError(_download_error(error)) from None
    finally:
        if destination is not None and not completed:
            destination.unlink(missing_ok=True)
        shutil.rmtree(directory, ignore_errors=True)

from pathlib import Path
from unittest.mock import patch

import pytest

from studio import recap_source as source
from studio.media import Cancelled


@pytest.mark.parametrize('url', [
    'https://youtu.be/abcdefghijk?t=40',
    'https://www.youtube.com/watch?v=abcdefghijk&feature=share',
    'http://m.youtube.com/watch?v=abcdefghijk',
    'https://youtube.com/shorts/abcdefghijk',
])
def test_normalizes_one_youtube_video(url):
    assert source.youtube_url(url) == 'https://www.youtube.com/watch?v=abcdefghijk'


@pytest.mark.parametrize('url', [
    'http://127.0.0.1:8000/private', 'https://youtube.com.example.org/watch?v=abcdefghijk',
    'https://youtube.com@evil.test/watch?v=abcdefghijk',
    'https://youtube.com:8443/watch?v=abcdefghijk', 'file:///etc/passwd',
    'https://www.youtube.com/playlist?list=123', 'https://youtu.be/abcdefghijk?list=123',
    'https://youtube.com/watch?v=abcdefghijk&v=11111111111',
    'https://youtu.be/abcdefghijk/other', 'https://youtube.com/channel/abcdefghijk',
])
def test_rejects_other_sources_and_playlists(url):
    with pytest.raises(ValueError):
        source.youtube_url(url)


class FakeJob:
    def __init__(self, temp):
        self.temp = temp
        self.messages = []
        self.cancelled = False

    def check(self):
        if self.cancelled:
            raise Cancelled('Cancelled')

    def progress(self, percent, message):
        self.check()
        self.messages.append((percent, message))


class FakeDownloader:
    instances = []
    info = {'id': 'abcdefghijk', 'title': 'Episode one', 'duration': 120,
            'filesize': 1000, 'subtitles': {'en': [{'ext': 'srt'}]}}
    error = None

    def __init__(self, opts):
        self.opts = opts
        self.instances.append(self)

    def __enter__(self): return self
    def __exit__(self, *args): return False

    def extract_info(self, url, download=False):
        if self.error:
            raise self.error
        return dict(self.info)

    def process_ie_result(self, info, download=True):
        template = self.opts['outtmpl']
        if self.opts.get('skip_download'):
            path = Path(template.replace('%(ext)s', 'en.srt'))
            path.write_text('1\n00:00:01,000 --> 00:00:03,000\n>> A beginning.\n')
        else:
            path = Path(template.replace('%(ext)s', 'mp4'))
            path.write_bytes(b'fake video')
            for hook in self.opts.get('progress_hooks', []):
                hook({'status': 'finished', 'filename': str(path), 'downloaded_bytes': 10, 'total_bytes': 10})
        return info


def test_import_registers_owned_video_and_clean_captions(tmp_path):
    FakeDownloader.instances = []
    (tmp_path / 'assets').mkdir()
    job = FakeJob(tmp_path / 'temp')
    job.temp.mkdir()
    with patch('yt_dlp.YoutubeDL', FakeDownloader), patch.object(source, 'DATA', tmp_path), \
            patch.object(source, 'require_space') as space, \
            patch.object(source, 'probe', return_value={'duration': 120, 'streams': [{'codec_type': 'video'}]}), \
            patch.object(source, 'register', side_effect=lambda path, **kwargs: dict(path=str(path), **kwargs)):
        result = source.import_youtube('https://youtu.be/abcdefghijk', job)
    assert Path(result['path']).parent == tmp_path / 'assets'
    assert Path(result['path']).read_bytes() == b'fake video'
    assert result['cues'] == [{'start': 1.0, 'end': 3.0, 'text': 'A beginning.'}]
    assert result['sourceType'] == 'youtube'
    assert space.call_count >= 2
    assert not (job.temp / 'youtube').exists()
    assert FakeDownloader.instances[0].opts['noplaylist'] is True
    assert '[height<=720]' in FakeDownloader.instances[0].opts['format']
    assert not FakeDownloader.instances[0].opts.get('cookiefile')


def test_registration_failure_removes_owned_file(tmp_path):
    (tmp_path / 'assets').mkdir()
    job = FakeJob(tmp_path)
    with patch('yt_dlp.YoutubeDL', FakeDownloader), patch.object(source, 'DATA', tmp_path), \
            patch.object(source, 'require_space'), \
            patch.object(source, 'probe', return_value={'duration': 120, 'streams': [{'codec_type': 'video'}]}), \
            patch.object(source, 'register', side_effect=ValueError('Database failed')):
        with pytest.raises(ValueError, match='Database failed'):
            source.import_youtube('https://youtu.be/abcdefghijk', job)
    assert not list((tmp_path / 'assets').iterdir())
    assert not (tmp_path / 'youtube').exists()


def test_cancellation_is_not_relabelled_as_download_failure(tmp_path):
    job = FakeJob(tmp_path)
    job.cancelled = True
    with pytest.raises(Cancelled):
        source.import_youtube('https://youtu.be/abcdefghijk', job)
    assert not (tmp_path / 'youtube').exists()


def test_restricted_video_has_actionable_failure(tmp_path):
    from yt_dlp.utils import DownloadError
    with patch('yt_dlp.YoutubeDL', FakeDownloader), patch.object(source, 'require_space'), \
            patch.object(FakeDownloader, 'error', DownloadError('Sign in to confirm you are not a bot')):
        with pytest.raises(ValueError, match='Upload the episode file'):
            source.import_youtube('https://youtu.be/abcdefghijk', FakeJob(tmp_path))


def test_live_video_is_rejected_before_downloading(tmp_path):
    with patch('yt_dlp.YoutubeDL', FakeDownloader), patch.object(source, 'require_space'), \
            patch.object(FakeDownloader, 'info', dict(FakeDownloader.info, is_live=True)):
        with pytest.raises(ValueError, match='completed episode'):
            source.import_youtube('https://youtu.be/abcdefghijk', FakeJob(tmp_path))


def test_disk_budget_failure_prevents_download(tmp_path):
    with patch('yt_dlp.YoutubeDL', FakeDownloader), \
            patch.object(source, 'require_space', side_effect=ValueError('Insufficient disk space')), \
            patch.object(FakeDownloader, 'process_ie_result') as download:
        with pytest.raises(ValueError, match='disk space'):
            source.import_youtube('https://youtu.be/abcdefghijk', FakeJob(tmp_path))
        download.assert_not_called()


def test_audio_only_download_is_not_registered(tmp_path):
    with patch('yt_dlp.YoutubeDL', FakeDownloader), patch.object(source, 'require_space'), \
            patch.object(source, 'probe', return_value={'duration': 120, 'streams': [{'codec_type': 'audio'}]}), \
            patch.object(source, 'register') as register:
        with pytest.raises(ValueError, match='readable video'):
            source.import_youtube('https://youtu.be/abcdefghijk', FakeJob(tmp_path))
        register.assert_not_called()
    assert not (tmp_path / 'youtube').exists()


def test_missing_captions_falls_back_to_transcription(tmp_path):
    (tmp_path / 'assets').mkdir()
    with patch('yt_dlp.YoutubeDL', FakeDownloader), patch.object(source, 'DATA', tmp_path), \
            patch.object(source, 'require_space'), \
            patch.object(source, 'probe', return_value={'duration': 120, 'streams': [{'codec_type': 'video'}]}), \
            patch.object(FakeDownloader, 'info', dict(FakeDownloader.info, subtitles={})), \
            patch.object(source, 'register', side_effect=lambda path, **kwargs: dict(path=str(path), **kwargs)):
        result = source.import_youtube('https://youtu.be/abcdefghijk', FakeJob(tmp_path))
    assert result['cues'] == []
    assert result['transcriptTiming'] is None

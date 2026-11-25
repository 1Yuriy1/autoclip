import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.pipeline.step6_video import VideoGenerator
from backend.services.simple_pipeline_adapter import SimplePipelineAdapter
from backend.utils.output_profile import build_output_profile
from backend.utils.video_processor import VideoProcessor, resolve_reframe


class ShortsOutputTests(unittest.TestCase):
    def test_profile_resolves_to_1080x1920(self):
        profile = build_output_profile('youtube_shorts', 'blur_pad')
        reframe = resolve_reframe(profile)
        self.assertIsNotNone(reframe)
        self.assertEqual((reframe['width'], reframe['height']), (1080, 1920))
        self.assertEqual(reframe['layout'], 'blur_pad')

    def test_original_profile_disables_reframe(self):
        self.assertIsNone(resolve_reframe(build_output_profile('original', 'crop')))

    def test_invalid_shorts_dimensions_are_rejected(self):
        profile = build_output_profile('youtube_shorts', 'crop')
        profile['width'] = 1079
        with self.assertRaises(ValueError):
            resolve_reframe(profile)

    def test_long_clip_is_limited_to_three_minutes(self):
        profile = build_output_profile('youtube_shorts', 'blur_pad')
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            generator = VideoGenerator(
                clips_dir=str(root / 'clips'),
                collections_dir=str(root / 'collections'),
                output_profile=profile,
            )
            clips = generator.prepare_clips([{
                'id': '1',
                'start_time': '00:00:10,000',
                'end_time': '00:04:00,000',
                'generated_title': 'Long clip',
            }])

        self.assertTrue(clips[0]['shorts_trimmed'])
        self.assertEqual(clips[0]['original_end_time'], '00:04:00,000')
        self.assertEqual(clips[0]['end_time'], '00:03:10.000')
        self.assertEqual(clips[0]['duration'], 180.0)

    def test_empty_timeline_falls_back_to_complete_short(self):
        profile = build_output_profile('youtube_shorts', 'blur_pad')
        adapter = SimplePipelineAdapter(
            'test-project',
            'test-task',
            processing_config={
                'output_profile': profile,
                'youtube_info': {'title': 'Source video title'},
            },
        )
        with patch.object(VideoProcessor, 'get_video_info', return_value={'duration': 136.25}):
            clips = adapter._build_shorts_fallback_clip(
                '/tmp/source.mp4',
                [{'title': 'Complete song', 'subtopics': ['Music video']}],
            )

        self.assertEqual(len(clips), 3)
        self.assertEqual(clips[0]['start_time'], '00:00:00.000')
        self.assertEqual(clips[0]['end_time'], '00:00:45.416')
        self.assertEqual(clips[-1]['end_time'], '00:02:16.250')
        self.assertEqual(clips[0]['outline'], 'Source video title — Part 1')
        self.assertTrue(clips[0]['fallback_clip'])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg is required')
    def test_ffmpeg_export_is_valid_9_by_16(self):
        profile = build_output_profile('youtube_shorts', 'crop')
        reframe = resolve_reframe(profile)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / 'source.mp4'
            output = root / 'short.mp4'
            subprocess.run([
                'ffmpeg', '-hide_banner', '-loglevel', 'error',
                '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=24',
                '-f', 'lavfi', '-i', 'sine=frequency=1000:sample_rate=48000',
                '-t', '0.5', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-y', str(source),
            ], check=True)
            self.assertTrue(VideoProcessor.reframe_video(source, output, reframe))
            self.assertEqual(VideoProcessor.validate_youtube_short(output), [])


if __name__ == '__main__':
    unittest.main()


def test_minute_versions_are_additive_ranked_and_idempotent(tmp_path):
    generator = VideoGenerator(
        clips_dir=str(tmp_path / 'clips'), collections_dir=str(tmp_path / 'collections'),
        output_profile=build_output_profile('youtube_shorts', 'blur_pad'),
    )
    clips = [dict(id=str(i), start_time=10, end_time=130, final_score=score,
                  generated_title=f'Clip {i}') for i, score in [(1, .5), (2, .9), (3, .8)]]
    result = generator.add_one_minute_clips(clips)
    assert result[:3] == clips
    assert [c['source_clip_id'] for c in result[3:]] == ['2', '3']
    assert all(c['duration'] == 60 and c['end_time'] == '00:01:10.000' for c in result[3:])
    assert len({c['id'] for c in result}) == 5
    assert generator.add_one_minute_clips(result) == result


def test_minute_version_never_extends_short_source(tmp_path):
    generator = VideoGenerator(
        clips_dir=str(tmp_path / 'clips'), collections_dir=str(tmp_path / 'collections'),
        output_profile=build_output_profile('youtube_shorts'),
    )
    result = generator.add_one_minute_clips([dict(id='1', start_time=0, end_time=25)])
    assert result[-1]['duration'] == 25

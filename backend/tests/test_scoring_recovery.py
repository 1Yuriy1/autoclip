import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend.pipeline.step3_scoring import ClipScorer, ScoringError
from backend.services.simple_pipeline_adapter import SimplePipelineAdapter


class ScoringRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.clips = [
            {'id': '1', 'chunk_index': 0, 'content': ["That's the block. Be cool."],
             'outline': 'Opening', 'start_time': '00:00:08,320', 'end_time': '00:00:36,760'},
            {'id': '2', 'chunk_index': 0, 'content': ['Escape'],
             'outline': 'Chase', 'start_time': '00:00:36,760', 'end_time': '00:01:10,000'},
        ]
        self.scorer = ClipScorer.__new__(ClipScorer)
        self.scorer.recommendation_prompt = 'Evaluate the clips.'
        self.scorer.llm_client = Mock()
        self.valid = [
            {'id': '2', 'final_score': 0.91, 'recommend_reason': 'An exciting chase.'},
            {'id': '1', 'final_score': 0.8, 'recommend_reason': 'A tense opening.'},
        ]

    def test_malformed_response_is_retried_and_matched_by_id(self):
        self.scorer.llm_client.call_with_retry.side_effect = [
            "[{'id': '1', 'final_score': 0.8}]", json.dumps(self.valid),
        ]
        result = self.scorer.score_clips(self.clips)
        self.assertEqual([clip['final_score'] for clip in result], [0.8, 0.91])
        self.assertEqual(result[0]['content'], self.clips[0]['content'])
        self.assertNotIn('final_score', self.clips[0])
        self.assertEqual(self.scorer.llm_client.call_with_retry.call_count, 2)

    def test_exhausted_retries_raise_without_assigning_zero(self):
        self.scorer.llm_client.call_with_retry.return_value = 'not JSON'
        with self.assertRaisesRegex(ScoringError, 'No quality scores were assigned'):
            self.scorer.score_clips(self.clips)
        self.assertEqual(self.scorer.llm_client.call_with_retry.call_count, 3)
        self.assertTrue(all('final_score' not in clip for clip in self.clips))

    def test_invalid_scores_and_incomplete_ids_are_not_accepted(self):
        bad_batches = [[], {}, [self.valid[0]], [self.valid[0], self.valid[0]]]
        for score in [True, -0.1, 1.1, float('nan'), float('inf'), None, '0.8']:
            bad_batches.append([{**self.valid[0], 'final_score': score}, self.valid[1]])
        bad_batches.extend([
            [{**self.valid[0], 'id': '999'}, self.valid[1]],
            [{**self.valid[0], 'recommend_reason': ''}, self.valid[1]],
        ])
        for batch in bad_batches:
            with self.subTest(batch=batch):
                self.scorer.llm_client.call_with_retry.return_value = json.dumps(batch)
                with self.assertRaises(ScoringError):
                    self.scorer._get_llm_evaluation(self.clips)
                self.assertTrue(all('final_score' not in clip for clip in self.clips))

    def test_real_zero_is_preserved_and_code_fence_is_allowed(self):
        self.valid[1]['final_score'] = 0.0
        self.scorer.llm_client.call_with_retry.return_value = '```json\n' + json.dumps(self.valid) + '\n```'
        result = self.scorer._get_llm_evaluation(self.clips)
        self.assertEqual(result[0]['final_score'], 0.0)

    def test_api_failure_is_retried(self):
        self.scorer.llm_client.call_with_retry.side_effect = [TimeoutError(), json.dumps(self.valid)]
        self.assertEqual(len(self.scorer.score_clips(self.clips)), 2)

    def test_missing_chunk_index_is_not_silently_dropped(self):
        del self.clips[0]['chunk_index']
        self.scorer.llm_client.call_with_retry.return_value = json.dumps(self.valid)
        self.assertEqual(len(self.scorer.score_clips(self.clips)), 2)


class PipelineFailureTests(unittest.TestCase):
    def run_pipeline(self, score_result=None, score_error=None, exported=0):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            # A real existing file selects the subtitle path, but all pipeline
            # work is mocked so tests never call an AI provider or encode video.
            subtitle = root / 'input.srt'
            subtitle.touch()
            prefix = 'backend.services.simple_pipeline_adapter.'
            with (patch('backend.core.path_utils.get_project_directory', return_value=root),
                  patch(prefix + 'clear_progress'), patch(prefix + 'emit_progress') as progress,
                  patch(prefix + 'run_step1_outline', return_value=[{'title': 'Test'}]),
                  patch(prefix + 'run_step2_timeline', return_value=[{'id': '1'}]),
                  patch(prefix + 'run_step3_scoring', return_value=score_result, side_effect=score_error),
                  patch(prefix + 'run_step4_title', return_value=[{'id': '1'}]),
                  patch(prefix + 'run_step5_clustering', return_value=[]),
                  patch(prefix + 'run_step6_video', return_value={'clips_generated': exported})):
                result = asyncio.run(SimplePipelineAdapter('test', 'task').process_project_sync(
                    str(root / 'input.mp4'), str(subtitle)))
                self.assertFalse(any(call.args[1] == 'DONE' for call in progress.call_args_list))
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['message'], result['error'])
                return result

    def test_scoring_error_reaches_the_user(self):
        result = self.run_pipeline(score_error=ScoringError('AI scoring failed; please retry.'))
        self.assertIn('AI scoring failed', result['message'])

    def test_no_eligible_clips_is_not_completed(self):
        result = self.run_pipeline(score_result=[])
        self.assertIn('minimum score threshold', result['message'])

    def test_zero_exports_is_not_completed(self):
        result = self.run_pipeline(score_result=[{'id': '1', 'final_score': 0.9}], exported=0)
        self.assertIn('No clips were exported', result['message'])


if __name__ == '__main__':
    unittest.main()

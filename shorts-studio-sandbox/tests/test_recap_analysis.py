from unittest.mock import Mock, patch

import pytest

from studio import recap
from studio.media import Cancelled


def episode_cues():
    return [
        {"start": index * 20, "end": index * 20 + 8,
         "text": f">> Event {index}: Maya found the missing map and decided to bring everyone back safely."}
        for index in range(30)
    ]


@pytest.mark.parametrize("target", [30, 60, 90])
def test_offline_recap_covers_episode_and_respects_speech_and_footage_budgets(target):
    cues = episode_cues()
    plan = recap.build_recap(cues, 600, target, use_provider=False)
    assert plan["analysisMode"] == "extractive"
    assert plan["sourceCoverage"]["analyzedCueCount"] == len(cues)
    assert [beat["key"] for beat in plan["beats"]] == [key for key, _ in recap.BEATS]
    assert sum(beat["duration"] for beat in plan["beats"]) == pytest.approx(target)
    assert plan["wordCount"] <= int(target * 2.2)
    assert plan["beats"][0]["start"] < 120
    assert plan["beats"][-1]["end"] >= 540
    for beat in plan["beats"]:
        assert 0 <= beat["start"] < beat["end"] <= 600
        assert beat["end"] - beat["start"] >= beat["duration"] - .002
        assert ">>" not in beat["text"]
        assert beat["text"].rstrip("…") in beat["evidence"][0]["text"]
    assert any("approximate" in warning for warning in plan["warnings"])


@pytest.mark.parametrize("field,value", [("start", float("nan")), ("end", float("inf")), ("start", -1), ("end", 9999), ("start", 600), ("end", 0)])
def test_invalid_cue_times_cannot_reach_a_render(field, value):
    cues = episode_cues()
    cues[0][field] = value
    with pytest.raises(ValueError):
        recap.build_recap(cues, 600, use_provider=False)


def test_partial_episode_transcript_is_disclosed():
    cues = episode_cues()[12:20]
    plan = recap.build_recap(cues, 600, use_provider=False)
    assert not plan["sourceCoverage"]["hasOpening"]
    assert not plan["sourceCoverage"]["hasEnding"]
    assert any("starts late" in warning for warning in plan["warnings"])
    assert any("resolution may be missing" in warning for warning in plan["warnings"])


def test_youtube_final_caption_overhang_is_clamped_without_losing_last_dialogue():
    duration = 1623.864308
    cues = episode_cues() + [{"start": 1623, "end": 1625.2, "text": "Do you?"}]
    normalized = recap.normalize_transcript(cues, duration)
    assert normalized[-1]["start"] == 1623
    assert normalized[-1]["end"] == duration
    assert normalized[-1]["text"] == "Do you?"
    plan = recap.build_recap(cues, duration, use_provider=False)
    assert plan["sourceCoverage"]["transcriptEnd"] == duration
    assert any("shortened to the video's end" in warning for warning in plan["warnings"])


def test_caption_overhang_larger_than_five_seconds_is_rejected():
    cues = episode_cues() + [{"start": 599, "end": 605.1, "text": "Final words."}]
    with pytest.raises(ValueError, match="ends after the episode"):
        recap.normalize_transcript(cues, 600)


def provider_response():
    return {"title": "The lost map", "beats": [
        {"key": key, "title": label, "narration": f"Maya finds clue number {index}.", "evidenceCueIds": [index]}
        for (key, label), index in zip(recap.BEATS, [0, 7, 14, 21, 29])
    ]}


CONFIG = {"textKey": "test-only", "textUrl": "https://example.test/chat/completions", "textModel": "test"}


def test_provider_timestamps_are_derived_from_actual_cues_and_editable_project_is_canonical():
    response = provider_response()
    response["beats"][0].update(start=-500, end=999999)
    with patch.object(recap, "settings", return_value=CONFIG), patch.object(recap, "_request", return_value=(response, {"total_tokens": 42})):
        plan = recap.build_recap(episode_cues(), 600, 60, asset_id="episode")
    assert plan["analysisMode"] == "provider"
    assert plan["providerUsage"]["total_tokens"] == 42
    assert plan["beats"][0]["start"] >= 0
    assert plan["beats"][0]["end"] < 30
    project = recap.recap_project(plan, captions="clean")
    assert project["format"] == "recap"
    assert project["sourceId"] == "episode"
    assert project["captions"] == "clean"
    assert all(scene["visual"] == "video" for scene in project["scenes"])
    assert all("footage" not in scene and "sourceStart" not in scene for scene in project["scenes"])
    assert [scene["beat"] for scene in project["scenes"]] == [key for key, _ in recap.BEATS]


@pytest.mark.parametrize("problem", ["invented_cue", "long_narration", "missing_ending", "reversed", "missing_beat"])
def test_ungrounded_or_incomplete_provider_output_falls_back_honestly(problem):
    response = provider_response()
    if problem == "invented_cue":
        response["beats"][2]["evidenceCueIds"] = [5000]
    elif problem == "long_narration":
        response["beats"][2]["narration"] = "Words " * 100
    elif problem == "missing_ending":
        response["beats"][-1]["evidenceCueIds"] = [22]
    elif problem == "reversed":
        response["beats"][1]["evidenceCueIds"] = [20]
    else:
        response["beats"].pop()
    with patch.object(recap, "settings", return_value=CONFIG), patch.object(recap, "_request", return_value=(response, {})):
        plan = recap.build_recap(episode_cues(), 600, 30)
    assert plan["analysisMode"] == "extractive"
    assert any("instead" in warning for warning in plan["warnings"])
    assert plan["wordCount"] <= 66


def test_http_auth_failure_does_not_leak_credentials_or_claim_ai_summary():
    reply = Mock(ok=False, status_code=401)
    with patch.object(recap, "settings", return_value=CONFIG), patch.object(recap.requests, "post", return_value=reply) as post:
        plan = recap.build_recap(episode_cues(), 600)
    assert post.call_count == 1
    assert plan["analysisMode"] == "extractive"
    assert any("HTTP 401" in warning for warning in plan["warnings"])
    assert "test-only" not in str(plan)


def test_long_episode_reads_every_transcript_chunk_and_preserves_last_cues():
    cues = episode_cues()
    original_chunks = recap._chunks
    recorded = []

    def fake_request(config, system, payload, job, max_tokens):
        recorded.append(payload)
        if "part" in payload:
            chunk = payload["transcript"]
            return {"events": [{"summary": "Maya found the map.", "evidenceCueIds": [chunk[0]["cueId"], chunk[-1]["cueId"]]}]}, {}
        return provider_response(), {}

    with patch.object(recap, "settings", return_value=CONFIG), patch.object(recap, "_chunks", side_effect=lambda value: original_chunks(value, 700)), patch.object(recap, "_request", side_effect=fake_request):
        plan = recap.build_recap(cues, 600)
    assert plan["analysisMode"] == "provider"
    parts = [request for request in recorded if "part" in request]
    assert len(parts) > 1
    assert [cue["cueId"] for part in parts for cue in part["transcript"]] == list(range(len(cues)))
    assert recorded[-1]["endingTranscript"][-1]["cueId"] == len(cues) - 1


def test_job_cancellation_is_never_converted_into_fallback():
    job = Mock()
    job.check.side_effect = Cancelled("Stopped")
    with pytest.raises(Cancelled):
        recap.build_recap(episode_cues(), 600, job=job)


def test_unknown_duration_and_too_short_transcript_are_rejected():
    with pytest.raises(ValueError, match="30-, 60- or 90-second"):
        recap.build_recap(episode_cues(), 600, 45, use_provider=False)
    with pytest.raises(ValueError, match="five timed"):
        recap.build_recap(episode_cues()[:3], 600, use_provider=False)

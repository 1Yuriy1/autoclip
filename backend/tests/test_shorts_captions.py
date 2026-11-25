from backend.utils.shorts_captions import clip_cues


def test_clip_boundaries_and_overlapping_captions(tmp_path):
    source = tmp_path / 'input.srt'
    source.write_text('''1
00:00:08,000 --> 00:00:12,000
First

2
00:00:11,000 --> 00:00:15,000
Second

3
00:00:20,000 --> 00:00:22,000
Outside
''')
    assert clip_cues(source, 10, 3) == [[0, 1, 'First'], [1, 3, 'Second']]


def test_speaker_markers_are_removed(tmp_path):
    source = tmp_path / 'input.srt'
    source.write_text('1\n00:00:00,000 --> 00:00:03,000\n>> Hello.\n>> Welcome.\n')
    assert clip_cues(source, 0, 3) == [[0, 3, 'Hello. Welcome.']]

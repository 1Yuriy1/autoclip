"""Exercise recap input routing without starting background/provider jobs."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from studio import store


@pytest.fixture
def recap_client(tmp_path, monkeypatch):
    data = tmp_path / 'sandbox-data'
    for name in ('assets', 'renders', 'temp'):
        (data / name).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(store, 'DATA', data)
    monkeypatch.setattr(store, 'DB', data / 'test.sqlite3')
    monkeypatch.setattr(server, 'DATA', data)
    monkeypatch.setattr(server, 'recover', lambda: None)
    with store.connect() as connection:
        connection.execute('CREATE TABLE records (kind TEXT,id TEXT,payload TEXT,updated REAL,PRIMARY KEY(kind,id))')
    submitted = []

    def submit(kind, payload):
        submitted.append((kind, payload))
        return {'id': 'test-job', 'kind': kind, 'payload': payload, 'status': 'queued'}

    monkeypatch.setattr(server, 'submit', submit)
    # Context startup is safe because recover is patched; real render jobs stay untouched.
    with TestClient(server.app) as client:
        yield client, submitted, data


def test_youtube_recap_routes_canonical_link_and_allowed_settings(recap_client):
    client, submitted, _ = recap_client
    response = client.post('/api/recaps', json={
        'youtubeUrl': 'https://youtu.be/abcdefghijk?t=12', 'duration': 60,
        'projectTitle': 'Episode one', 'width': 720, 'autoRender': True,
        'layout': 'blur_pad', 'captions': 'bold', 'untrustedPath': '/etc/passwd',
    })
    assert response.status_code == 200
    kind, payload = submitted[0]
    assert kind == 'recap'
    assert payload['youtubeUrl'] == 'https://www.youtube.com/watch?v=abcdefghijk'
    assert payload['autoRender'] is True
    assert 'untrustedPath' not in payload


@pytest.mark.parametrize('payload', [
    {}, {'assetId': 'abc', 'youtubeUrl': 'https://youtu.be/abcdefghijk'},
    {'youtubeUrl': 'http://127.0.0.1:8000/private'},
    {'youtubeUrl': 'https://youtu.be/abcdefghijk?list=123'},
    {'youtubeUrl': 'https://youtu.be/abcdefghijk', 'duration': 31},
    {'youtubeUrl': 'https://youtu.be/abcdefghijk', 'width': 999},
    {'youtubeUrl': 'https://youtu.be/abcdefghijk', 'layout': 'invalid'},
    {'youtubeUrl': 'https://youtu.be/abcdefghijk', 'captions': 'invalid'},
    ['not', 'an', 'object'],
])
def test_invalid_recap_request_does_not_queue_work(recap_client, payload):
    client, submitted, _ = recap_client
    response = client.post('/api/recaps', json=payload)
    assert response.status_code == 400
    assert response.json()['detail']
    assert submitted == []


def test_uploaded_episode_can_be_selected_for_recap(recap_client, monkeypatch):
    client, submitted, data = recap_client
    monkeypatch.setattr(server, 'require_space', lambda amount: None)
    monkeypatch.setattr(server, 'probe', lambda path: {
        'duration': 1440, 'streams': [{'codec_type': 'video'}, {'codec_type': 'audio'}],
    })
    upload = client.post('/api/upload', files={'file': ('episode.mp4', b'video fixture', 'video/mp4')})
    assert upload.status_code == 200
    asset = upload.json()
    assert asset['mediaType'] == 'video'
    assert asset['duration'] == 1440
    assert 'path' not in asset
    assert store.asset_path(asset['id']).parent == data / 'assets'
    assert client.get('/api/assets/' + asset['id']).content == b'video fixture'
    response = client.post('/api/recaps', json={'assetId': asset['id'], 'duration': 90})
    assert response.status_code == 200
    assert submitted == [('recap', {'assetId': asset['id'], 'duration': 90})]


def test_missing_and_audio_assets_are_rejected(recap_client):
    client, submitted, data = recap_client
    assert client.post('/api/recaps', json={'assetId': 'missing'}).status_code == 400
    audio = data / 'assets' / 'audio.wav'
    audio.write_bytes(b'audio')
    asset = store.register(audio, mediaType='audio', duration=20)
    response = client.post('/api/recaps', json={'assetId': asset['id']})
    assert response.status_code == 400
    assert response.json()['detail'] == 'Choose a video episode'
    assert submitted == []


def test_nonexternal_asset_cannot_escape_sandbox(recap_client):
    client, submitted, data = recap_client
    outside = data.parent / 'outside.mp4'
    outside.write_bytes(b'outside source')
    asset = store.register(outside, mediaType='video', duration=20)
    response = client.post('/api/recaps', json={'assetId': asset['id']})
    assert response.status_code == 400
    assert response.json()['detail'] == 'Invalid asset path'
    assert submitted == []


def test_cross_origin_cannot_start_recap(recap_client):
    client, submitted, _ = recap_client
    response = client.post('/api/recaps', json={'youtubeUrl': 'https://youtu.be/abcdefghijk'},
                           headers={'Origin': 'https://other.example'})
    assert response.status_code == 403
    assert submitted == []

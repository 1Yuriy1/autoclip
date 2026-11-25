import io
from types import SimpleNamespace
from PIL import Image
import pytest
from backend.services import ai_thumbnail
from backend.services.upload_kit import default_kit,thumbnail,validate_kit


def clip():
    return SimpleNamespace(id='test-clip',title='GTA 6: A Pickup Turns Into a Raid',description='A task-force raid.',duration=60,tags=[],clip_metadata={'content':['The task force is on its way.']})


def test_artwork_roundtrip_and_frame_switch(tmp_path,monkeypatch):
    monkeypatch.setattr(ai_thumbnail,'get_data_directory',lambda:tmp_path)
    c=clip();raw=io.BytesIO();Image.new('RGB',(720,1280),'blue').save(raw,format='PNG')
    saved=ai_thumbnail.store_artwork(c,raw.getvalue(),'test')
    kit=default_kit(c)
    assert kit['thumbnailMode']=='ai' and kit['hasArtwork']
    assert thumbnail(c,kit)==saved
    assert validate_kit(kit,60)['thumbnailMode']=='ai'
    ai_thumbnail.store_artwork(c,raw.getvalue(),'test2')
    assert saved.exists() and len(c.clip_metadata['thumbnailArtworkHistory'])==1


def test_reject_invalid_images_and_paths(tmp_path,monkeypatch):
    monkeypatch.setattr(ai_thumbnail,'get_data_directory',lambda:tmp_path)
    c=clip()
    with pytest.raises(ValueError):ai_thumbnail.store_artwork(c,b'not an image','test')
    c.clip_metadata['thumbnailArtwork']={'id':'../../secrets'}
    with pytest.raises(ValueError):ai_thumbnail.artwork_path(c)


def test_prompt_uses_specific_clip_and_no_auto_retry(monkeypatch):
    c=clip();p=ai_thumbnail.prompt_for(c,default_kit(c),'Neon lighting')
    assert 'GTA 6' in p and 'task force' in p and 'Neon lighting' in p
    monkeypatch.setattr(ai_thumbnail,'settings',lambda:{'key':'','model':'gpt-image-2'})
    with pytest.raises(ValueError,match='API_KEY'):ai_thumbnail.generate(c,default_kit(c))


def test_generation_request_contract_without_network(monkeypatch):
    import base64
    import subprocess
    from backend.services import upload_kit
    c=clip();raw=io.BytesIO();Image.new('RGB',(32,48),'red').save(raw,format='PNG')
    monkeypatch.setattr(ai_thumbnail,'settings',lambda:{'key':'test-key','model':'gpt-image-2'})
    monkeypatch.setattr(upload_kit,'video_path',lambda c:'/test/video.mp4')
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:SimpleNamespace(stdout='{"streams":[{"width":720,"height":1280}]}'))
    calls=[]
    def post(url,**kwargs):
        calls.append((url,kwargs))
        return SimpleNamespace(ok=True,json=lambda:{'data':[{'b64_json':base64.b64encode(raw.getvalue()).decode()}]})
    monkeypatch.setattr(ai_thumbnail.requests,'post',post)
    data,model,prompt=ai_thumbnail.generate(c,default_kit(c))
    assert data==raw.getvalue() and model=='gpt-image-2'
    assert len(calls)==1 and calls[0][1]['json']['n']==1
    assert calls[0][1]['json']['size']=='864x1536'
    assert 'task force' in prompt


def test_provider_error_preserves_existing_artwork(monkeypatch):
    import subprocess
    from backend.services import upload_kit
    c=clip();c.clip_metadata['thumbnailArtwork']={'id':'a'*32}
    monkeypatch.setattr(ai_thumbnail,'settings',lambda:{'key':'test-key','model':'gpt-image-2'})
    monkeypatch.setattr(upload_kit,'video_path',lambda c:'/test/video.mp4')
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:SimpleNamespace(stdout='{"streams":[{"width":1280,"height":720}]}'))
    monkeypatch.setattr(ai_thumbnail.requests,'post',lambda *a,**k:SimpleNamespace(ok=False,status_code=401))
    with pytest.raises(ValueError,match='HTTP 401'):ai_thumbnail.generate(c,default_kit(c))
    assert c.clip_metadata['thumbnailArtwork']['id']=='a'*32

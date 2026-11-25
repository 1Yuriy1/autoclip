from types import SimpleNamespace
import pytest
from backend.services.upload_kit import default_kit,validate_kit,thumbnail


def clip():
    return SimpleNamespace(title='A real turning point — 1 minute cut',description='A surprising conversation.',duration=60,tags=['story'],clip_metadata={'content':['>> We have a problem.']})


def test_source_copy_and_saved_edits():
    c=clip();kit=default_kit(c)
    assert kit['title']=='A real turning point'
    assert 'We have a problem.' in kit['description'] and '>>' not in kit['description']
    c.clip_metadata['uploadKit']={'title':'My title'}
    assert default_kit(c)['title']=='My title'


def test_upload_limits_and_invalid_frame():
    kit=default_kit(clip())
    assert validate_kit(kit,60)['title']==kit['title']
    for key,value in [('title','x'*101),('headline',''),('frameTime',float('nan')),('frameTime',60),('tags',['x'*501])]:
        with pytest.raises(ValueError):validate_kit({**kit,key:value},60)


def test_missing_video_has_actionable_error():
    c=clip();c.video_path='/does-not-exist.mp4'
    with pytest.raises(ValueError,match='Render the clip'):thumbnail(c,{**default_kit(c),'thumbnailMode':'frame'})


def test_subject_first_raid_hook_and_complementary_thumbnail():
    c=clip();c.project=SimpleNamespace(name='GTA 6 Official Gameplay Trailer (2026)')
    c.title='Unexpected Tensions Rise as the Task Force Arrives — 1-minute cut'
    c.clip_metadata={'content':["We're here to pick up for Boobie.",'Our friends on the task force are on their way.','We got a situation happening.']}
    kit=default_kit(c)
    assert kit['title']=='GTA 6: A Simple Pickup Turns Into a Raid'
    assert kit['subject']=='GTA 6' and kit['headline']=='THEY’RE HERE'
    assert len(kit['titleOptions'])==3
    assert all(o['title'].startswith('GTA 6: ') for o in kit['titleOptions'])
    assert '#GTA6' in kit['description']
    assert '1-minute cut' not in kit['title']


def test_custom_edits_preserved_until_explicit_refresh():
    c=clip();c.project=SimpleNamespace(name='Suits | Mike closes a deal')
    c.clip_metadata['uploadKit']={'title':'My custom title','subject':'Suits','headline':'THE DEAL'}
    assert default_kit(c)['title']=='My custom title'
    revised=default_kit(c,subject_override='Suits',refresh=True)
    assert revised['title'].startswith('Suits: ')
    assert 'Raid' not in revised['title']


def test_ai_is_default_without_generating_on_read():
    c=clip();kit=default_kit(c)
    assert kit['thumbnailMode']=='ai' and not kit['hasArtwork']
    assert 'thumbnailArtwork' not in c.clip_metadata
    c.clip_metadata['uploadKit']={'thumbnailMode':'frame'}
    assert default_kit(c)['thumbnailMode']=='frame'

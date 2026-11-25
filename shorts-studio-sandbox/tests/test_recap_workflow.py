import copy
from unittest.mock import patch
import pytest
from studio.store import validate_project
from studio.recap_render import scene_captions


def project():
    return {'format':'recap','title':'Episode','sourceId':'source','duration':60,
            'scenes':[{'beat':beat,'text':'These are five clear words.','start':i*100,
                       'end':i*100+12,'duration':12,'visual':'video'}
                      for i,beat in enumerate(['setup','conflict','key_events','climax','resolution'])]}


def test_recap_requires_ending_and_valid_source_ranges():
    p=project()
    assert validate_project(p)['duration']==60
    for bad in (-1,float('nan'),float('inf')):
        broken=copy.deepcopy(p);broken['scenes'][0]['start']=bad
        with pytest.raises(ValueError):validate_project(broken)
    p['scenes'].pop()
    with pytest.raises(ValueError,match='resolution'):validate_project(p)


def test_caption_timeline_covers_all_beats_without_speaker_markers():
    p=project();p['scenes'][0]['text']='>> These are five clear words.'
    cues=scene_captions(p['scenes'])
    assert len(cues)==5 and cues[0]['start']==0 and cues[-1]['end']==60
    assert all('>>' not in cue['text'] for cue in cues)
    assert all(a['end']==b['start'] for a,b in zip(cues,cues[1:]))


def test_recap_recovery_reuses_existing_child_export():
    from studio.jobs import create_recap
    class Job:
        id='parent'
        record={'recapProject':project()}
        def check(self):pass
        def update(self,**values):self.record.update(values)
    job=Job()
    with patch('studio.jobs.listing',return_value=[{'id':'existing','payload':{'recapParentId':'parent'}}]), patch('studio.jobs.submit') as submit:
        result=create_recap({'autoRender':True},job)
    assert result['renderJobId']=='existing'
    submit.assert_not_called()


def test_recap_draft_does_not_enqueue_export():
    from studio.jobs import create_recap
    class Job:
        id='parent'
        record={'recapProject':project()}
        def check(self):pass
    with patch('studio.jobs.submit') as submit:
        result=create_recap({'autoRender':False},Job())
    assert result['renderJobId'] is None
    submit.assert_not_called()

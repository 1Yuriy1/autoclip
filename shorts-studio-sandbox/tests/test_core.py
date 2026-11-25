import tempfile
from pathlib import Path
from studio.media import clean, parse_srt, select_highlights, srt_text
from studio.store import validate_project

def test_speaker_markers_and_srt_roundtrip():
    cues=parse_srt('1\n00:00:01,000 --> 00:00:03,000\n>> Hello there.\n')
    assert cues==[{'start':1.0,'end':3.0,'text':'Hello there.'}]
    assert '>>' not in srt_text(cues)

def test_highlights_end_on_complete_sentence_and_do_not_overlap():
    cues=[]
    for i,text in enumerate(['Start here.','This is context.','Here is why.','The result matters.','New story.','Another detail.','It ends.']):
        cues.append({'start':i*8,'end':i*8+7,'text':text})
    clips=select_highlights(cues,30,2)
    assert len(clips)==2
    assert all(c['end']-c['start']<=30 and c['text'].endswith('.') for c in clips)
    assert max(clips[0]['start'],clips[1]['start'])>=min(clips[0]['end'],clips[1]['end'])

def test_project_validation_preserves_animation_and_rejects_bad_clip():
    p=validate_project({'format':'story','title':'A','duration':15,'scenes':[{'title':'Hi','text':'There','visual':'character'}]})
    assert p['format']=='story'
    try:validate_project({'format':'clip','duration':10,'start':12,'end':2,'scenes':[{}]})
    except ValueError as e:assert 'boundaries' in str(e)
    else:assert False

def test_offline_explainer_uses_supplied_facts():
    from studio.story import draft
    p=draft({'format':'explainer','idea':'How rain forms','sourceNotes':'Water evaporates from the surface. Vapor cools and condenses into droplets.','duration':30,'palette':'mint','captions':'clean'})
    text=' '.join(s['text'] for s in p['scenes'])
    assert 'Water evaporates' in text and 'habit' not in text

def test_short_variant_preserves_ending_and_sentences():
    from studio.story import shorten
    p={'duration':60,'scenes':[{'title':str(i),'text':'A full sentence. Another whole sentence.','duration':20} for i in range(4)]}
    short=shorten(p,15)
    assert len(short['scenes'])==3 and short['scenes'][-1]['title']=='3'
    assert all(s['text'].endswith('.') for s in short['scenes'])

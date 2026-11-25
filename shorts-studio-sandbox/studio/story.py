"""Offline scripts grounded in supplied text, with explicit limits."""
import re
from .store import validate_project

def sentences(text):return [x.strip() for x in re.split(r'(?<=[.!?])\s+|\n+',text) if x.strip()]

def shorten(p,duration):
    p=dict(p);scenes=[dict(s) for s in p['scenes']];budget=max(8,int(duration*2.1))
    # Preserve the opening and conclusion; choose the strongest middle example.
    if duration<=15 and len(scenes)>3:scenes=[scenes[0],max(scenes[1:-1],key=lambda s:sum(w in s.get('text','').lower() for w in ['example','because','imagine','when'])),scenes[-1]]
    remaining=budget
    for i,s in enumerate(scenes):
        allowance=max(3,remaining//(len(scenes)-i));choices=sentences(s.get('text',''));text=''
        for sentence in choices:
            if len((text+' '+sentence).split())>allowance:break
            text=(text+' '+sentence).strip()
        if not text:
            # Do not cut a spoken sentence mid-thought: use a complete short title.
            text=s.get('title','').strip().rstrip('.!?')+'.'
        s['text']=text;s['duration']=max(1,len(text.split())/2.1);remaining-=len(text.split())
    p.update(scenes=scenes,duration=duration)
    return p

def draft(data):
    p=dict(data);idea=str(p.get('idea','')).strip();notes=sentences(str(p.get('sourceNotes','')))
    if not idea:raise ValueError('Enter a topic or premise')
    if p.get('format')=='explainer':
        if len(notes)<2:raise ValueError('For a topic-specific offline explainer, add at least two factual sentences in Source notes. Or connect the AI text provider.')
        facts=[n for n in notes if not n.startswith(('http://','https://'))]
        if len(facts)<2:raise ValueError('Add factual sentences, not only source links.')
        p['scenes']=[{'title':idea,'text':f'What should you know about {idea.rstrip(".?!")}?','visual':'orbits'},*({'title':f'Key idea {i+1}','text':fact,'visual':['steps','rings','orbits'][i%3]} for i,fact in enumerate(facts[:3])),{'title':'The takeaway','text':facts[-1],'visual':'rings'}]
        p['researchStatus']='source-notes-provided'
    elif p.get('format')=='story':
        name=p.get('characterName') or 'Pip'
        p['scenes']=[{'title':idea,'text':f'{name} had one goal: {idea.rstrip(".?!")}.','visual':'character'},{'title':'The first try failed','text':f'{name} rushed forward, but the path ended at a locked gate.','visual':'character'},{'title':'A different approach','text':f'Instead of pushing harder, {name} noticed a small bell and rang it. A friend opened the gate.','visual':'character'},{'title':'Help opened the way','text':f'{name} smiled. The next step was easier together.','visual':'character'}]
    else:p['scenes']=[{'title':idea,'text':'','visual':'rings'}]
    p=shorten(p,float(p.get('duration',30)));p['title']=idea;p.pop('id',None);return validate_project(p)

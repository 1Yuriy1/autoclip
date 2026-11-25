import json, shutil, threading, time, traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .store import DATA, put, get, listing, uid, require_space, validate_project, asset_path, register
from .media import Cancelled, run, FFMPEG, probe, render_animation, render_clip, srt_text
POOL=ThreadPoolExecutor(max_workers=1,thread_name_prefix='studio-render')
CANCEL={};ACTIVE=set();LOCK=threading.Lock()
class Job:
    def __init__(self,id):self.id=id;self.record=get('jobs',id);self.temp=DATA/'temp'/id;self.temp.mkdir(exist_ok=True)
    def check(self):
        if CANCEL.get(self.id):raise Cancelled('Cancelled by user')
    def update(self,**values):self.record.update(values);self.record=put('jobs',self.record,self.id)
    def progress(self,p,message):self.check();self.update(progress=round(p,1),message=message)

def submit(kind,payload):
    id=uid();r=put('jobs',dict(id=id,kind=kind,payload=payload,status='queued',progress=0,message='Queued',created=time.time()));schedule(id);return r

def schedule(id):
    with LOCK:
        if id in ACTIVE:return
        ACTIVE.add(id);CANCEL[id]=False
    POOL.submit(work,id)

def retry(id):
    r=get('jobs',id)
    if r['status'] not in ('failed','cancelled','interrupted'):raise ValueError('Only stopped jobs can be retried')
    r.update(status='queued',error=None,message='Retry queued');put('jobs',r,id);schedule(id);return r

def cancel(id):
    r=get('jobs',id)
    if r['status'] in ('queued','running'):CANCEL[id]=True
    return {'ok':True}

def transcribe(payload,job):
    from faster_whisper import WhisperModel
    from .store import ROOT
    paths=list((ROOT.parent/'data/whisper-models').glob('hub/models--Systran--faster-whisper-base/snapshots/*'))
    if not paths:raise ValueError('Local Whisper base model is not installed. Import an SRT transcript instead.')
    job.progress(10,'Loading local speech recognition');model=WhisperModel(str(paths[0]),device='cpu',compute_type='int8')
    path=asset_path(payload['assetId']);segments,info=model.transcribe(str(path),word_timestamps=True,beam_size=3)
    cues=[]
    for s in segments:
        job.check();cues.append({'start':s.start,'end':s.end,'text':s.text.strip(),'words':[{'start':w.start,'end':w.end,'text':w.word.strip()} for w in (s.words or [])]});job.progress(min(95,s.end/max(1,info.duration)*100),'Transcribing speech locally')
    a=get('assets',payload['assetId']);a['cues']=cues;a['transcriptTiming']='word-aligned';put('assets',a,a['id']);return {'assetId':a['id'],'cues':cues}

class ProgressStage:
    """Map reusable transcription/analysis progress into a single recap job."""
    def __init__(self,job,start,end):self.job=job;self.start=start;self.end=end
    def __getattr__(self,name):return getattr(self.job,name)
    def progress(self,p,message):self.job.progress(self.start+(self.end-self.start)*max(0,min(100,p))/100,message)

def create_recap(payload,job):
    from .recap import build_recap, recap_project
    from .recap_source import import_youtube
    if job.record.get('recapProject'):
        project=job.record['recapProject']
    else:
        asset_id=job.record.get('sourceAssetId') or payload.get('assetId')
        if asset_id:
            asset=get('assets',asset_id);asset_path(asset_id)
        else:
            asset=import_youtube(payload.get('youtubeUrl',''),ProgressStage(job,0,25))
        if asset.get('mediaType')!='video':raise ValueError('Choose a video episode')
        job.update(sourceAssetId=asset['id'])
        if not asset.get('cues'):
            transcribe({'assetId':asset['id']},ProgressStage(job,25,60))
            asset=get('assets',asset['id'])
        job.progress(62,'Reading the full episode, including its ending')
        plan=build_recap(asset['cues'],float(asset.get('duration') or probe(asset_path(asset['id']))['duration']),
                         payload.get('duration',60),title=payload.get('projectTitle') or asset['name'],
                         asset_id=asset['id'],job=ProgressStage(job,62,92))
        project=recap_project(plan,asset['id'])
        project.update(voiceEnabled=True,layout=payload.get('layout','blur_pad'),
                       voice=payload.get('voice','Samantha'),alignCaptions=True,
                       captions=payload.get('captions','bold'),palette='mint',recapJobId=job.id)
        project=put('projects',validate_project(project))
        job.update(recapProject=project)
    job.check()
    render_id=job.record.get('renderJobId')
    if payload.get('autoRender',True) and not render_id:
        # Reuse a queued export after recovery if shutdown happened between saves.
        existing=next((r for r in listing('jobs') if r.get('payload',{}).get('recapParentId')==job.id),None)
        render=existing or submit('render',{'project':project,'width':payload.get('width',720),'recapParentId':job.id})
        render_id=render['id'];job.update(renderJobId=render_id)
    return {'project':project,'renderJobId':render_id,'assetId':project['sourceId']}

def work(id):
    job=Job(id)
    try:
        job.check();job.update(status='running',message='Starting',error=None)
        kind=job.record['kind'];payload=job.record['payload']
        if kind=='script':
            from .providers import generate_script
            result=generate_script(payload,job)
        elif kind=='ai-shot':
            from .providers import ai_shot
            require_space(40*1024**2);result=ai_shot(payload,job)
        elif kind=='transcribe':result=transcribe(payload,job)
        elif kind=='recap':result=create_recap(payload,job)
        elif kind=='render':
            p=validate_project(payload['project']);width=int(payload.get('width',720))
            if width not in (360,720,1080):raise ValueError('Unsupported resolution')
            require_space(int(p['duration']*width/720*700000)+15*1024**2)
            out=DATA/'renders'/(id+'.mp4')
            try:
                if p['format']=='recap':
                    from .recap_render import render_recap
                    cues=render_recap(p,job,out,width)
                else:cues=render_clip(p,job,out,width) if p['format']=='clip' else render_animation(p,job,out,width)
                job.check();info=probe(out)
                if not info['streams'] or abs(info['duration']-p['duration'])>.25:raise ValueError('Rendered duration did not match the project')
                srt=DATA/'renders'/(id+'.srt');srt.write_text(srt_text(cues))
                thumb=DATA/'renders'/(id+'.jpg');run([FFMPEG,'-v','error','-ss',str(min(1,p['duration']/2)),'-i',str(out),'-frames:v','1','-vf','scale=180:320','-y',str(thumb)],job)
                result={'url':f'/media/{id}.mp4','srtUrl':f'/media/{id}.srt','thumbnail':f'/media/{id}.jpg','duration':info['duration'],'width':width,'title':p['title'],'projectId':p.get('id'),'project':p,'bytes':out.stat().st_size}
            except Exception:
                out.unlink(missing_ok=True);raise
        else:raise ValueError('Unknown job type')
        job.update(status='completed',progress=100,message='Complete',result=result,finished=time.time())
    except Cancelled:job.update(status='cancelled',message='Cancelled',finished=time.time())
    except Exception as e:job.update(status='failed',message='Job failed',error=str(e)[:2000],finished=time.time())
    finally:
        shutil.rmtree(job.temp,ignore_errors=True)
        with LOCK:ACTIVE.discard(id)

def recover():
    for r in listing('jobs'):
        if r['status'] in ('running','queued'):
            if r['kind']=='ai-shot' and not r.get('providerTaskId'):
                r.update(status='interrupted',message='Submission status unknown. Check provider dashboard before retrying.');put('jobs',r,r['id'])
            else:
                r.update(status='queued',message='Resuming after restart');put('jobs',r,r['id']);schedule(r['id'])

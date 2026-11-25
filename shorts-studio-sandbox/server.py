"""Run with ../.venv/bin/python server.py. All writes stay in workspace/."""
import json, mimetypes, os, re, shutil, sqlite3, time
from pathlib import Path
from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from studio.store import ROOT, DATA, get, put, listing, delete, uid, register, public_asset, asset_path, free_bytes, require_space, validate_project
from studio.media import probe, parse_srt, select_highlights, voices, suggest_crop
from studio.jobs import submit, cancel, retry, recover
from studio.providers import public_settings, update_settings
app=FastAPI(title='Frame Lab Sandbox',docs_url='/api/docs')
@app.middleware('http')
async def local_only(request,call_next):
    origin=request.headers.get('origin','')
    if request.method not in ('GET','HEAD','OPTIONS') and origin and origin not in ('http://127.0.0.1:8317','http://localhost:8317'):
        return JSONResponse({'detail':'Cross-origin writes are not allowed'},403)
    try:return await call_next(request)
    except ValueError as e:return JSONResponse({'detail':str(e)},400)
@app.exception_handler(ValueError)
async def invalid(request,exc):return JSONResponse({'detail':str(exc)},400)
@app.get('/api/status')
def status():return {'freeMB':round(free_bytes()/1024**2),'providers':public_settings(),'voices':voices(),'version':2,'isolated':True}
@app.get('/api/projects')
def projects():return listing('projects')
@app.put('/api/projects')
async def save_project(request:Request):
    p=validate_project(await request.json())
    if p.get('id'):
        try:
            previous=get('projects',p['id'])
            comparable=lambda x:{k:v for k,v in x.items() if k not in ('updated',)}
            if comparable(previous)!=comparable(p):put('versions',{'projectId':p['id'],'project':previous})
        except ValueError:pass
    return put('projects',p)
@app.get('/api/projects/{id}/versions')
def versions(id:str):return [v for v in listing('versions') if v['projectId']==id][:30]

@app.delete('/api/projects/{id}')
def archive_project(id:str):
    p=get('projects',id);p['archived']=True;return put('projects',p,id)
@app.post('/api/local-story')
async def local_story(request:Request):
    from studio.story import draft
    return draft(await request.json())
@app.get('/api/series')
def series():return listing('series')
@app.put('/api/series')
async def save_series(request:Request):
    p=await request.json();p={k:v for k,v in p.items() if k in ('id','name','voice','palette','characterName','characterColor','referenceId','captionStyle')}
    if not str(p.get('name','')).strip():raise ValueError('Series name is required')
    return put('series',p)
@app.get('/api/assets')
def assets():return [public_asset(a) for a in listing('assets')]
@app.get('/api/assets/{id}')
def asset(id:str):return FileResponse(asset_path(id))
@app.post('/api/upload')
async def upload(file:UploadFile=File(...)):
    ext=Path(file.filename or '').suffix.lower()
    if ext not in ('.mp4','.mov','.mkv','.webm','.mp3','.wav','.m4a','.aiff','.png','.jpg','.jpeg','.webp','.srt'):raise ValueError('Unsupported file type')
    target=DATA/'assets'/(uid()+ext);size=0
    try:
        with target.open('wb') as f:
            while chunk:=await file.read(1024*1024):
                size+=len(chunk)
                if size>2*1024**3:raise ValueError('Maximum upload size is 2 GB')
                require_space(len(chunk));f.write(chunk)
        typ='image' if ext in ('.png','.jpg','.jpeg','.webp') else 'transcript' if ext=='.srt' else 'media'
        extra={}
        if typ=='media':extra.update(probe(target));typ='video' if any(s['codec_type']=='video' for s in extra['streams']) else 'audio'
        if typ=='transcript':extra['cues']=parse_srt(target.read_text(encoding='utf-8-sig'))
        if typ=='image':
            from PIL import Image
            with Image.open(target) as im:im.verify()
        return public_asset(register(target,file.filename,mediaType=typ,**extra))
    except Exception:target.unlink(missing_ok=True);raise
@app.get('/api/original-sources')
def originals():
    result=[]
    for p in (ROOT.parent/'data/projects').glob('*/raw/input.mp4'):
        result.append({'id':p.parent.parent.name,'name':p.parent.parent.name,'hasTranscript':(p.parent/'input.srt').exists(),'bytes':p.stat().st_size})
    return result
@app.post('/api/import-original/{id}')
def import_original(id:str):
    if not re.fullmatch(r'[0-9a-f-]{36}',id):raise ValueError('Invalid source identifier')
    p=(ROOT.parent/'data/projects'/id/'raw/input.mp4').resolve()
    if not p.is_relative_to((ROOT.parent/'data/projects').resolve()) or not p.exists():raise ValueError('Source not found')
    for a in listing('assets'):
        if a.get('external') and a['path']==str(p):return public_asset(a)
    info=probe(p);srt=p.parent/'input.srt';cues=parse_srt(srt.read_text(encoding='utf-8-sig')) if srt.exists() else []
    return public_asset(register(p,'AutoClip source '+id[:8],external=True,mediaType='video',cues=cues,**info))
@app.put('/api/assets/{id}/transcript')
async def transcript(id:str,request:Request):
    p=await request.json();a=get('assets',id)
    if p.get('srt') is not None:cues=parse_srt(str(p['srt']))
    else:cues=p.get('cues',[])
    if not isinstance(cues,list) or len(cues)>50000:raise ValueError('Invalid transcript')
    for c in cues:
        if float(c['start'])<0 or float(c['end'])<=float(c['start']) or not isinstance(c['text'],str):raise ValueError('Invalid transcript timestamps')
    a['cues']=sorted(cues,key=lambda c:float(c['start']));a['transcriptTiming']='imported';return public_asset(put('assets',a,id))
@app.post('/api/highlights')
async def highlights(request:Request):
    p=await request.json();a=get('assets',p['assetId']);target=float(p.get('duration',60))
    if target not in (15,30,60):raise ValueError('Use a 15-, 30- or 60-second target')
    selected=select_highlights(a.get('cues',[]),target,max(1,min(5,int(p.get('count',2)))))
    result=[]
    for i,c in enumerate(selected):
        title=' '.join(c['text'].split()[:9]);project={'format':'clip','title':title,'idea':title,'duration':c['end']-c['start'],'start':c['start'],'end':c['end'],'sourceId':a['id'],'cues':a['cues'],'palette':'mint','captions':'clean','layout':'blur_pad','cropX':.5,'selectionReason':c['reason'],'scenes':[{'title':title,'text':c['text'][:1800],'visual':'video'}]}
        result.append(put('projects',validate_project(project)))
    return result
@app.post('/api/suggest-crop')
async def crop_suggestion(request:Request):
    p=await request.json();a=asset_path(p['assetId']);temp=DATA/'temp'/('crop-'+uid())
    try:return suggest_crop(a,float(p.get('start',0)),float(p.get('end',10)),temp)
    finally:shutil.rmtree(temp,ignore_errors=True)
@app.get('/api/jobs')
def jobs():return listing('jobs')[:200]
@app.get('/api/jobs/{id}')
def job(id:str):return get('jobs',id)
@app.post('/api/jobs')
async def enqueue(request:Request):
    p=await request.json();kind=p.get('kind');payload=p.get('payload',{})
    if kind not in ('render','script','transcribe','ai-shot'):raise ValueError('Unknown job type')
    if kind=='render':payload['project']=validate_project(payload['project'])
    return submit(kind,payload)
@app.post('/api/recaps')
async def episode_recap(request:Request):
    from studio.recap_source import validate_youtube_url
    p=await request.json()
    if not isinstance(p,dict):raise ValueError('Provide a recap request')
    if bool(p.get('assetId'))==bool(p.get('youtubeUrl')):raise ValueError('Choose one uploaded video or YouTube link')
    if p.get('duration',60) not in (30,60,90):raise ValueError('Choose a 30-, 60- or 90-second recap')
    if p.get('width',720) not in (360,720,1080):raise ValueError('Unsupported resolution')
    if p.get('assetId'):
        a=get('assets',p['assetId']);asset_path(a['id'])
        if a.get('mediaType')!='video':raise ValueError('Choose a video episode')
    else:p['youtubeUrl']=validate_youtube_url(p['youtubeUrl'])
    if p.get('layout','blur_pad') not in ('blur_pad','crop'):raise ValueError('Unknown recap framing')
    if p.get('captions','bold') not in ('bold','clean','none'):raise ValueError('Unknown caption style')
    return submit('recap',{k:v for k,v in p.items() if k in ('assetId','youtubeUrl','duration','width','projectTitle','autoRender','voice','layout','captions')})
@app.post('/api/jobs/{id}/cancel')
def cancel_job(id:str):return cancel(id)
@app.post('/api/jobs/{id}/retry')
def retry_job(id:str):return retry(id)
@app.post('/api/variants')
async def variants(request:Request):
    p=await request.json();project=validate_project(p['project']);durations=p.get('durations',[15,30,60]);results=[]
    if len(durations)>3 or any(d not in [15,30,60] for d in durations):raise ValueError('Invalid duration variants')
    hooks=p.get('hooks',[])[:2]
    if hooks and project['format']=='clip':raise ValueError('Use alternate source openings for clip hook variants')
    for duration in durations:
        variant=json.loads(json.dumps(project));variant.pop('id',None);variant['title']=project['title']+f' · {duration}s';variant['duration']=duration;variant['experimentGroup']=project.get('id') or project['title']
        if project['format']=='clip':
            cues=[c for c in project.get('cues',[]) if float(c['start'])>=project['start']]
            chosen=select_highlights(cues,duration,1)[0];variant.update(start=chosen['start'],end=chosen['end'],duration=chosen['end']-chosen['start'])
        if project['format']!='clip':
            from studio.story import shorten
            variant=shorten(variant,duration)
        variant=put('projects',validate_project(variant));results.append(submit('render',{'project':variant,'width':p.get('width',720)}))
    for i,hook in enumerate(hooks):
        variant=json.loads(json.dumps(project));variant.pop('id',None);variant['title']=project['title']+f' · Hook {i+1}';variant['experimentGroup']=project.get('id') or project['title'];variant['scenes'][0]['title']=str(hook)[:180];variant['scenes'][0]['text']=str(hook)[:1800]
        if variant['format']=='clip':raise ValueError('Hook text variants are for narrated projects; select alternate source openings for clips.')
        variant=put('projects',validate_project(variant));results.append(submit('render',{'project':variant,'width':p.get('width',720)}))
    return results
@app.get('/api/metrics')
def metrics():return listing('metrics')
@app.put('/api/metrics')
async def save_metrics(request:Request):
    p=await request.json()
    if p.get('platform') not in ('YouTube','TikTok','Instagram'):raise ValueError('Choose a platform')
    for key in ('views','shares','followers','avgWatch','duration'):
        p[key]=float(p.get(key,0))
        if p[key]<0:raise ValueError('Metrics cannot be negative')
    p['completion']=float(p.get('completion',0))
    if not 0<=p['completion']<=100:raise ValueError('Completion must be a percentage')
    return put('metrics',p)
@app.get('/api/providers')
def providers():return public_settings()
@app.put('/api/providers')
async def configure(request:Request):return update_settings(await request.json())
@app.get('/media/{filename}')
def media(filename:str):
    if not re.fullmatch(r'[a-f0-9]{32}\.(mp4|srt|jpg)',filename):raise ValueError('Invalid render identifier')
    p=DATA/'renders'/filename
    if not p.is_file():raise ValueError('Render not found')
    return FileResponse(p,headers={'Cache-Control':'no-cache'})
@app.get('/')
def index():return FileResponse(ROOT/'index.html',headers={'Cache-Control':'no-store'})
@app.get('/{filename}')
def static(filename:str):
    if filename not in ('app.js','studio.js','style.css','research.json','recap.js','recap.css'):raise HTTPException(404)
    return FileResponse(ROOT/filename,headers={'Cache-Control':'no-cache'})
@app.on_event('startup')
def startup():recover()
if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=int(os.getenv('FRAME_LAB_PORT','8317')))

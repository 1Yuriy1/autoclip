import json, math, os, re, shutil, sqlite3, threading, time, uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DATA=Path(os.getenv('FRAME_LAB_DATA',str(ROOT/'workspace'))).resolve()
DATA.mkdir(parents=True,exist_ok=True)
for name in ('assets','renders','temp'): (DATA/name).mkdir(exist_ok=True)
DB=DATA/'studio.sqlite3'
LOCK=threading.RLock()
def connect():
    c=sqlite3.connect(DB,timeout=30); c.row_factory=sqlite3.Row; return c
with connect() as c:
    c.execute('CREATE TABLE IF NOT EXISTS records (kind TEXT,id TEXT,payload TEXT,updated REAL,PRIMARY KEY(kind,id))')
def uid():return uuid.uuid4().hex

def put(kind,payload,id=None):
    id=id or payload.get('id') or uid(); payload=dict(payload,id=id,updated=time.time())
    with LOCK,connect() as c:c.execute('INSERT OR REPLACE INTO records VALUES(?,?,?,?)',(kind,id,json.dumps(payload),payload['updated']))
    return payload

def get(kind,id):
    with connect() as c:r=c.execute('SELECT payload FROM records WHERE kind=? AND id=?',(kind,id)).fetchone()
    if not r:raise ValueError(f'{kind.rstrip("s").capitalize()} not found')
    return json.loads(r['payload'])

def listing(kind):
    with connect() as c:return [json.loads(r['payload']) for r in c.execute('SELECT payload FROM records WHERE kind=? ORDER BY updated DESC',(kind,))]

def delete(kind,id):
    with LOCK,connect() as c:c.execute('DELETE FROM records WHERE kind=? AND id=?',(kind,id))

def asset_path(id):
    a=get('assets',id); p=Path(a['path']).resolve()
    if not a.get('external') and not p.is_relative_to(DATA):raise ValueError('Invalid asset path')
    if not p.is_file():raise ValueError('Asset file is missing')
    return p

def public_asset(a):return {k:v for k,v in a.items() if k!='path'}

def register(path,name=None,external=False,**extra):
    p=Path(path).resolve()
    return put('assets',dict(name=name or p.name,path=str(p),size=p.stat().st_size,external=external,url='',**extra))

def free_bytes():return shutil.disk_usage(DATA).free

def require_space(bytes_needed):
    if free_bytes()<bytes_needed+50*1024**2:raise ValueError(f'Insufficient disk space. Need about {round((bytes_needed+50*1024**2)/1024**2)} MB free before this job can run.')

FORMATS={'explainer','story','loop','clip','recap'}
VISUALS={'orbits','steps','rings','character','image','video'}
def validate_project(p):
    if not isinstance(p,dict):raise ValueError('Project must be an object')
    if p.get('format') not in FORMATS:raise ValueError('Unsupported format')
    p=dict(p); p['title']=str(p.get('title') or p.get('idea') or 'Untitled')[:180]; p['idea']=str(p.get('idea',''))[:2000]
    p['duration']=float(p.get('duration',30))
    if not 1<=p['duration']<=180:raise ValueError('Duration must be between 1 and 180 seconds')
    if p.get('palette','mint') not in {'mint','sunset','blue'}:raise ValueError('Unknown palette')
    if p.get('captions','clean') not in {'clean','bold','none'}:raise ValueError('Unknown caption style')
    scenes=p.get('scenes',[])
    if not isinstance(scenes,list) or not 1<=len(scenes)<=24:raise ValueError('Use 1–24 scenes')
    for s in scenes:
        if not isinstance(s,dict):raise ValueError('Invalid scene')
        for k,limit in [('title',180),('text',1800)]:
            if not isinstance(s.get(k,''),str) or len(s.get(k,''))>limit:raise ValueError(f'Scene {k} is too long')
        if s.get('visual','orbits') not in VISUALS:raise ValueError('Unknown scene visual')
        if not 0<float(s.get('duration',p['duration']/len(scenes)))<=180:raise ValueError('Invalid scene duration')
    if p.get('format')=='clip':
        start=float(p.get('start',0));end=float(p.get('end',start+p['duration']))
        if start<0 or end<=start or end-start>180:raise ValueError('Invalid clip boundaries')
        p['start'],p['end'],p['duration']=start,end,end-start
    if p['format']=='recap':
        if p['duration'] not in (30,60,90):raise ValueError('Recaps must be 30, 60 or 90 seconds')
        if not p.get('sourceId'):raise ValueError('A recap needs a source video')
        expected=['setup','conflict','key_events','climax','resolution']
        if len(scenes)!=5 or [s.get('beat') for s in scenes]!=expected:raise ValueError('A recap needs setup, conflict, key events, climax and resolution in order')
        for scene in scenes:
            start=float(scene.get('start',-1));end=float(scene.get('end',-1))
            if not math.isfinite(start) or not math.isfinite(end) or start<0 or end<=start:raise ValueError('Invalid recap footage range')
            if not scene.get('text','').strip():raise ValueError('Every story beat needs narration')
            scene['start'],scene['end']=start,end
        if p.get('layout','blur_pad') not in ('blur_pad','crop'):raise ValueError('Unknown recap framing')
    return p

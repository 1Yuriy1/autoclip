"""Editable upload copy and source-grounded thumbnail designs for every clip."""
import hashlib
import io
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps, ImageStat
from ..core.path_utils import get_data_directory


def clean(value):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]*>|>>\s*', '', str(value or ''))).strip()


def subject_for(clip):
    project = getattr(clip, 'project', None)
    source = clean(getattr(project, 'name', '') or getattr(project, 'title', '') or (clip.clip_metadata or {}).get('source_title', ''))
    combined = source + ' ' + clean(clip.title)
    if re.search(r'\b(?:GTA\s*(?:6|VI)|Grand Theft Auto\s*(?:6|VI))\b', combined, re.I):return 'GTA 6'
    if not source:return ''
    return re.split(r'\s*[|:—]\s*|\s+-\s+|\s+(?:Official|Gameplay|Season|Episode)\b', source, maxsplit=1, flags=re.I)[0].strip()[:60]


def packaging(clip, subject):
    original = re.sub(r'\s*[—–-]\s*1[- ]minute cut\s*$', '', clean(clip.title), flags=re.I)
    content = (clip.clip_metadata or {}).get('content', [])
    if isinstance(content, str):content = [content]
    quotes = [clean(v) for v in content if isinstance(v,str) and clean(v)]
    evidence = ' '.join(quotes).lower()
    prefix = subject + ': ' if subject else ''
    lead = re.split(r'[:—]|\s+(?:as|amidst|with)\s+', original, maxsplit=1, flags=re.I)[0]
    if subject:lead = re.sub(r'^' + re.escape(subject) + r'\s*[:—-]?\s*', '', lead, flags=re.I)
    if 'task force' in evidence:
        options = [
            ('Searchable', 'The Task Force Raid', 'TASK FORCE RAID'),
            ('Story hook', 'A Simple Pickup Turns Into a Raid' if 'pick up' in evidence or 'pick up' in original.lower() or 'pick' in evidence else 'The Task Force Just Showed Up', "THEY’RE HERE"),
            ('Dialogue hook', '“We Got a Situation”' if 'situation' in evidence else 'The Task Force Is on Its Way', 'A SITUATION')]
        reason = 'The transcript mentions the task force and its arrival; the hook uses that concrete event.'
    elif 'police' in evidence and any(v in evidence for v in ['run','go','escape','drive']):
        options = [('Searchable','The Police Escape','POLICE ESCAPE'),('Story hook','The Police Arrive. Now What?','NOW WHAT?'),('Curiosity','Getting Away From the Police','GET OUT')]
        reason = 'The source dialogue mentions police and movement away from the scene.'
    else:
        words=lead.split()[:5]
        while len(words)>1 and words[-1].lower() in {'a','an','the','of','to','and','in','at','for'}:words.pop()
        headline=' '.join(words).upper()[:60] or 'THE MOMENT'
        options=[('Searchable',lead or original,headline),('Scene hook',(lead or original)+' — The Scene',headline),('Full context',original,headline)]
        reason='Uses the existing clip topic. Add a more specific event in the editable title when the transcript is sparse.'
    result=[]
    for label,title,headline in options:
        if subject and title.lower().startswith(subject.lower()):title=title[len(subject):].lstrip(': —-')
        title=prefix+title
        if len(title)>100:title=title[:97].rsplit(' ',1)[0]+'…'
        if not any(v['title']==title for v in result):result.append({'label':label,'title':title,'headline':headline,'reason':reason})
    return result,quotes


def default_kit(clip, subject_override=None, refresh=False):
    meta=clip.clip_metadata or {};saved=meta.get('uploadKit', {})
    subject=clean(subject_override if subject_override is not None else saved.get('subject') or subject_for(clip))[:60]
    options,quotes=packaging(clip,subject)
    chosen=next((o for o in options if o['label']=='Story hook'),options[0])
    description=chosen['title']+'\n\n'+clean(clip.description)
    if quotes:
        ranked=sorted(quotes,key=lambda q:sum(term in q.lower() for term in ['task force','situation','police','escape','finally','because']),reverse=True)
        description+='\n\nFrom the scene: “'+ranked[0][:240]+'”'
    hashtag=re.sub(r'[^a-zA-Z0-9]','',subject)
    tags=list(dict.fromkeys(([subject] if subject else [])+(['Grand Theft Auto VI','GTA 6 gameplay'] if subject=='GTA 6' else [])+[clean(t) for t in (clip.tags or []) if isinstance(t,str)]))[:12]
    if hashtag:description+='\n\n#'+hashtag
    if 0<(clip.duration or 0)<=180:description+=(' ' if hashtag else '\n\n')+'#Shorts'
    kit={'subject':subject,'title':chosen['title'],'description':description[:5000], 'tags':tags,'headline':chosen['headline'],
         'frameTime':max(0,round(float(clip.duration or 1)*.35,1)), 'copyMode':'Subject-first, source-grounded suggestions'}
    if not refresh:kit.update(saved)
    kit.setdefault('thumbnailMode','ai')
    kit['hasArtwork']=bool(meta.get('thumbnailArtwork'))
    kit.update(titleOptions=options,packagingVersion=2)
    return kit


def validate_kit(data, duration):
    if not isinstance(data, dict):raise ValueError('Upload details must be an object')
    result = {}
    for key, limit in [('title',100),('description',5000),('headline',60)]:
        value=data.get(key,'')
        if not isinstance(value,str) or len(value)>limit:raise ValueError(f'{key.capitalize()} must be at most {limit} characters')
        if key!='description' and not value.strip():raise ValueError(f'{key.capitalize()} is required')
        result[key]=value.strip()
    tags=data.get('tags',[])
    if not isinstance(tags,list) or any(not isinstance(t,str) for t in tags) or len(','.join(tags))>500:raise ValueError('Tags must be under 500 characters')
    result['tags']=[clean(t) for t in tags if clean(t)]
    seconds=float(data.get('frameTime',0))
    if not 0<=seconds<max(.1,float(duration or 1)):raise ValueError('Choose a thumbnail frame within the clip')
    subject=data.get('subject','')
    if not isinstance(subject,str) or len(subject)>60:raise ValueError('Main subject must be at most 60 characters')
    result['subject']=clean(subject)
    mode=data.get('thumbnailMode','ai')
    if mode not in ('frame','ai'):raise ValueError('Choose video frame or AI artwork.')
    result['thumbnailMode']=mode
    result['frameTime']=seconds
    return result


def video_path(clip):
    path=Path(clip.video_path or '')
    if not path.is_file():raise ValueError('The exported video is missing. Render the clip before downloading its upload kit.')
    return path


def _font(size):
    for name in ['/System/Library/Fonts/Supplemental/Arial Bold.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf']:
        if Path(name).exists():return ImageFont.truetype(name,size)
    return ImageFont.load_default(size=size)


def thumbnail(clip, kit):
    if kit.get('thumbnailMode')=='ai':
        from .ai_thumbnail import artwork_path
        return artwork_path(clip)
    source=video_path(clip)
    key=hashlib.sha256(json.dumps(['v4',kit.get('subject',''),str(source),source.stat().st_mtime_ns,kit['headline'],kit['frameTime']]).encode()).hexdigest()
    folder=get_data_directory()/'upload-kits'/str(clip.id)
    folder.mkdir(parents=True,exist_ok=True)
    out=folder/(key+'.jpg')
    if out.exists():return out
    ffmpeg=shutil.which('ffmpeg') or 'ffmpeg'
    # Use the matching unpadded source frame when the original is available.
    original=get_data_directory()/'projects'/str(clip.project_id)/'raw/input.mp4'
    position=kit['frameTime']
    if original.is_file():
        timing=(clip.clip_metadata or {}).get('start_time',clip.start_time)
        if isinstance(timing,str) and ':' in timing:
            parts=[float(v) for v in timing.replace(',', '.').split(':')]
            offset=sum(v*m for v,m in zip(parts,[3600,60,1]))
        else:offset=float(timing or 0)
        source=original;position+=offset
    result=subprocess.run([ffmpeg,'-v','error','-ss',str(position),'-i',str(source),'-frames:v','1','-vf','scale=1280:-2','-f','image2pipe','-vcodec','mjpeg','pipe:1'],capture_output=True,timeout=45)
    if result.returncode or not result.stdout:raise ValueError('Could not extract this thumbnail frame. Choose an earlier frame.')
    with Image.open(io.BytesIO(result.stdout)) as raw:
        frame=raw.convert('RGB')
    # Rendered Shorts are vertical even when their original footage is wide.
    info=subprocess.run([shutil.which('ffprobe') or 'ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height','-of','json',str(video_path(clip))],capture_output=True,text=True,timeout=15)
    stream=json.loads(info.stdout)['streams'][0]
    width,height=(720,1280) if stream['height']>stream['width'] else (1280,720)
    canvas=ImageOps.fit(frame,(width,height)).filter(ImageFilter.GaussianBlur(20))
    canvas=ImageEnhance.Brightness(canvas).enhance(.45)
    foreground=ImageOps.fit(frame,(width,height))
    foreground=ImageEnhance.Brightness(ImageOps.autocontrast(foreground,cutoff=1)).enhance(1.12)
    foreground=ImageEnhance.Contrast(foreground).enhance(1.15)
    foreground=ImageEnhance.Color(foreground).enhance(1.2)
    canvas.paste(foreground,((width-foreground.width)//2,(height-foreground.height)//2))
    overlay=Image.new('RGBA',canvas.size)
    d=ImageDraw.Draw(overlay)
    for y in range(height):
        alpha=int(235*max(0,(y-height*.36)/(height*.64)))
        d.line((0,y,width,y),fill=(7,10,17,alpha))
    canvas=Image.alpha_composite(canvas.convert('RGBA'),overlay)
    d=ImageDraw.Draw(canvas)
    if kit.get('subject'):
        badge=kit['subject'].upper();face=_font(46)
        while d.textlength(badge,font=face)>width-100 and face.size>18:face=_font(face.size-2)
        badge_width=d.textlength(badge,font=face)+40
        d.rounded_rectangle((32,32,32+badge_width,108),radius=10,fill='#ffdf42')
        d.text((52,42),badge,font=face,fill='#080a10')
    text=clean(kit['headline']).upper()
    for size in range(100,35,-2):
        face=_font(size);lines=[];line=''
        for word in text.split():
            trial=(line+' '+word).strip()
            if d.textlength(trial,font=face)>width-140 and line:lines.append(line);line=word
            else:line=trial
        if line:lines.append(line)
        if len(lines)<=3 and max(d.textlength(s,font=face) for s in lines)<=width-140:break
    y=height-60-len(lines)*size*1.1
    d.rounded_rectangle((32,y-24,44,height-46),radius=6,fill='#ffdf42')
    for i,line in enumerate(lines):
        d.text((64,y+i*size*1.1),line,font=face,fill='#ffdf42' if i==len(lines)-1 else 'white',stroke_width=5,stroke_fill='#080a10')
    d.rectangle((0,0,width-1,height-1),outline='#ffdf42',width=9)
    with tempfile.NamedTemporaryFile(dir=folder,suffix='.jpg',delete=False) as tmp:
        temp=Path(tmp.name)
    try:
        canvas.convert('RGB').save(temp,quality=90,optimize=True)
        temp.replace(out)
    finally:temp.unlink(missing_ok=True)
    return out

import json, math, re, shutil, subprocess, time
from pathlib import Path
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont, ImageOps
from .store import asset_path, DATA, ROOT
FFMPEG=shutil.which('ffmpeg') or 'ffmpeg'; FFPROBE=shutil.which('ffprobe') or 'ffprobe'
class Cancelled(Exception):pass

def run(cmd,job,timeout=1200):
    log=job.temp/'process.log'
    with log.open('w+') as f:
        proc=subprocess.Popen(cmd,stdout=f,stderr=f)
        try:
            started=time.time()
            while proc.poll() is None:
                job.check()
                if time.time()-started>timeout:raise ValueError('Media process timed out')
                time.sleep(.15)
            if proc.returncode:
                f.seek(0);text=f.read()[-1800:]
                if 'No space left' in text:raise ValueError('Disk filled during rendering. Free space and retry; source files were preserved.')
                raise ValueError('Media processing failed: '+text)
        finally:
            if proc.poll() is None:proc.terminate();proc.wait(timeout=10)

def probe(path):
    p=subprocess.run([FFPROBE,'-v','error','-show_format','-show_streams','-of','json',str(path)],capture_output=True,text=True,timeout=30)
    if p.returncode:raise ValueError('Cannot read this media file')
    d=json.loads(p.stdout);return dict(duration=float(d.get('format',{}).get('duration',0)),streams=d.get('streams',[]))

def suggest_crop(path,start,end,temp):
    """Estimate the active subject's horizontal center from sampled edge energy."""
    from PIL import ImageFilter, ImageStat
    temp=Path(temp);temp.mkdir(parents=True,exist_ok=True)
    span=max(1,float(end)-float(start));pattern=temp/'subject-%02d.jpg'
    result=subprocess.run([FFMPEG,'-v','error','-ss',str(start),'-i',str(path),'-t',str(span),'-vf',f'fps={min(1,8/span)},scale=360:-2','-frames:v','8','-y',str(pattern)],capture_output=True,text=True,timeout=60)
    if result.returncode:raise ValueError('Could not analyze source framing')
    samples=sorted(temp.glob('subject-*.jpg'))
    detector=ROOT/'bin/faces'
    if detector.exists() and samples:
        detected=subprocess.run([str(detector),*[str(p) for p in samples]],capture_output=True,text=True,timeout=45)
        if detected.returncode==0:
            faces=json.loads(detected.stdout);centers=sorted(f['x'] for f in faces if 'x' in f)
            if centers:return {'cropX':round(centers[len(centers)//2],3),'method':'Apple Vision face detection; largest face across sampled frames','facesFound':len(centers)}
    centers=[]
    for p in samples:
        with Image.open(p) as im:
            edge=im.convert('L').filter(ImageFilter.FIND_EDGES);w,h=edge.size;scores=[]
            for i in range(12):
                box=(i*w//12,h//8,(i+1)*w//12,h*7//8);energy=ImageStat.Stat(edge.crop(box)).mean[0]
                # Center preference stabilizes noisy backgrounds while motion/detail still wins.
                scores.append(energy*(.75+.25*(1-abs((i+.5)/12-.5)*2)))
            centers.append((max(range(12),key=lambda i:scores[i])+.5)/12)
    if not centers:return {'cropX':.5,'method':'center fallback; no readable frames','facesFound':0}
    centers.sort();return {'cropX':round(centers[len(centers)//2],3),'method':'detail-based fallback; no faces detected','facesFound':0}

@lru_cache(maxsize=50)
def font(size,bold=True):
    for p in (["/System/Library/Fonts/Supplemental/Arial Bold.ttf","/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"] if bold else ["/System/Library/Fonts/Supplemental/Arial.ttf","/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]):
        if Path(p).exists():return ImageFont.truetype(p,int(size))
    return ImageFont.load_default(size=int(size))

def clean(text):return re.sub(r'\s+',' ',re.sub(r'<[^>]*>|>>\s*','',text)).strip()

def parse_srt(text):
    import pysrt
    return [{'start':s.start.ordinal/1000,'end':s.end.ordinal/1000,'text':clean(s.text)} for s in pysrt.from_string(text) if clean(s.text)]

def srt_text(cues):
    def stamp(t):
        ms=round(max(0,t)*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
        return f'{h:02}:{m:02}:{s:02},{ms:03}'
    return '\n\n'.join(f'{i+1}\n{stamp(c["start"])} --> {stamp(c["end"])}\n{clean(c["text"])}' for i,c in enumerate(cues))+'\n'

def select_highlights(cues,target=60,count=2):
    """Select non-overlapping complete utterance windows; never exceed target."""
    if not cues:raise ValueError('A transcript is required to find complete stories')
    candidates=[]
    for i,c in enumerate(cues):
        if i and not re.search(r'[.!?]["\']?$',cues[i-1]['text'].strip()):continue
        start=max(0,float(c['start']));end=start;texts=[]
        for s in cues[i:]:
            if float(s['end'])-start>target:break
            texts.append(s['text'])
            if re.search(r'[.!?]["\']?$',s['text'].strip()):end=float(s['end'])
        if end-start<min(8,target*.4):continue
        text=' '.join(s['text'] for s in cues[i:] if float(s['end'])<=end)
        score=(end-start)/target+sum(w in text.lower() for w in ['why','how','because','but','finally','imagine','secret','never'])*.18
        candidates.append({'start':start,'end':end,'text':text,'score':score,'reason':'Starts after a sentence boundary and ends on a complete utterance.'})
    chosen=[]
    for c in sorted(candidates,key=lambda x:x['score'],reverse=True):
        if not any(max(c['start'],x['start'])<min(c['end'],x['end']) for x in chosen):chosen.append(c)
        if len(chosen)>=count:break
    if not chosen:raise ValueError('No complete sentence window fits this length. Try a longer target or edit the transcript.')
    return chosen

PALETTES={'mint':('#14231f','#c9efaa','#5cae94'),'sunset':('#291c30','#ffbb8f','#b179c9'),'blue':('#111f38','#a9d5ff','#5a7bfa')}
def wrapped(draw,text,face,max_width):
    lines=[];line=''
    for word in clean(text).split():
        candidate=(line+' '+word).strip()
        if draw.textlength(candidate,font=face)>max_width and line:lines.append(line);line=word
        else:line=candidate
    if line:lines.append(line)
    return lines

def label(draw,text,xy,width,size,color,height=200,bold=True):
    while size>=12:
        f=font(size,bold);lines=wrapped(draw,text,f,width)
        if len(lines)*size*1.25<=height:break
        size-=2
    for i,line in enumerate(lines):draw.text((xy[0],xy[1]+i*size*1.25),line,fill=color,font=f,anchor='mt')

@lru_cache(maxsize=20)
def image_asset(id):
    with Image.open(asset_path(id)) as im:return im.convert('RGB').copy()

def frame(project,scene,t,duration,w,h,index):
    bg,accent,secondary=PALETTES.get(project.get('palette'),PALETTES['mint']);im=Image.new('RGB',(w,h),bg);d=ImageDraw.Draw(im);scale=w/720
    visual=scene.get('visual','orbits');asset=scene.get('assetId')
    if asset and visual=='image':
        src=image_asset(asset);zoom=1+.08*t/max(.01,duration);pic=ImageOps.fit(src,(round(w*zoom),round(h*zoom)))
        im.paste(pic,((w-pic.width)//2,(h-pic.height)//2));shade=Image.new('RGBA',(w,h),(0,0,0,95));im=Image.alpha_composite(im.convert('RGBA'),shade).convert('RGB');d=ImageDraw.Draw(im)
    else:
        cx=w/2;cy=h*.51;a=t/max(.01,duration)*2*math.pi
        if visual=='steps':
            for i in range(5):
                bh=(60+i*40+math.sin(a+i)*15)*scale;x=cx+(-230+i*96)*scale;y=cy+130*scale
                d.rounded_rectangle((x,y-bh,x+72*scale,y),radius=12*scale,fill=accent if i%2==0 else secondary)
        elif visual=='character':
            cy+=math.sin(a)*20*scale;color=project.get('characterColor',accent)
            if not re.fullmatch(r'#[0-9a-fA-F]{6}',color):color=accent
            d.ellipse((cx-140*scale,cy+150*scale,cx+140*scale,cy+185*scale),fill=secondary)
            d.rounded_rectangle((cx-100*scale,cy-140*scale,cx+100*scale,cy+145*scale),radius=55*scale,fill=color)
            for dx in [-38,38]:d.ellipse((cx+(dx-10)*scale,cy-50*scale,cx+(dx+10)*scale,cy-20*scale),fill=bg)
            d.arc((cx-28*scale,cy-5*scale,cx+28*scale,cy+45*scale),0,180,fill=bg,width=max(2,round(6*scale)))
            for sign in [-1,1]:d.line((cx+sign*90*scale,cy+25*scale,cx+sign*160*scale,cy+(math.sin(a)*35-20)*scale),fill=color,width=round(20*scale))
            if project.get('characterName'):label(d,project['characterName'],(cx,cy+205*scale),w*.8,round(23*scale),accent,height=50*scale)
        elif visual=='rings':
            for i in range(5,0,-1):
                rx=(35+i*29)*scale;ry=rx*(.65+.25*math.cos(a));d.ellipse((cx-rx,cy-ry,cx+rx,cy+ry),outline=accent if i%2 else secondary,width=max(2,round(14*scale)))
        else:
            r=180*scale;d.ellipse((cx-r,cy-r,cx+r,cy+r),outline=secondary,width=2)
            d.rounded_rectangle((cx-80*scale,cy-80*scale,cx+80*scale,cy+80*scale),radius=40*scale,fill=accent)
            for i in range(3):
                x=cx+math.cos(a+i*2*math.pi/3)*r;y=cy+math.sin(a+i*2*math.pi/3)*r;rr=(22+i*8)*scale;d.ellipse((x-rr,y-rr,x+rr,y+rr),fill=accent if i%2 else secondary)
    d.text((w*.075,h*.055),project.get('seriesName','FRAME LAB').upper()[:35],font=font(max(10,round(18*scale))),fill=accent)
    label(d,scene.get('title',''),(w/2,h*.135),w*.83,round(58*scale),accent,height=h*.18)
    if project.get('captions','clean')!='none':
        words=clean(scene.get('text','')).split();groups=[' '.join(words[i:i+7]) for i in range(0,len(words),7)]
        text=groups[min(len(groups)-1,int(t/max(.01,duration)*len(groups)))] if groups else ''
        if text:
            if project.get('captions')=='bold':d.rounded_rectangle((w*.055,h*.752,w*.945,h*.88),radius=15*scale,fill=accent)
            label(d,text,(w/2,h*.79),w*.82,round(38*scale),bg if project.get('captions')=='bold' else 'white',height=h*.10)
    if scene.get('transition')=='fade':
        opacity=min(1,t/.3,max(0,(duration-t)/.3));im=Image.blend(Image.new('RGB',(w,h),bg),im,opacity)
    return im


def voices():
    if not shutil.which('say'):return []
    r=subprocess.run(['say','-v','?'],capture_output=True,text=True,timeout=10)
    return [line.split('  ')[0].strip() for line in r.stdout.splitlines() if 'en_' in line][:40]

def narration(project,job,duration,scenes):
    if project.get('audioId'):return asset_path(project['audioId'])
    if not project.get('voiceEnabled',True):return None
    if not shutil.which('say'):raise ValueError('Local narration is unavailable on this machine. Upload an audio file or turn narration off.')
    voice=project.get('voice','Samantha');allowed=voices()
    if voice not in allowed:voice=allowed[0] if allowed else ''
    files=[]
    for i,s in enumerate(scenes):
        job.check();seconds=float(s['duration']);text=clean(s.get('text',''));wav=job.temp/f'voice-{i}.wav'
        if text:
            script=job.temp/f'script-{i}.txt';script.write_text(text);raw=job.temp/f'voice-{i}.aiff'
            cmd=['say','-r','165','-f',str(script),'-o',str(raw)]
            if voice:cmd+=['-v',voice]
            run(cmd,job);actual=probe(raw)['duration'];rate=max(.5,min(2,actual/max(.5,seconds-.15)))
            if actual/seconds>2:raise ValueError(f'Scene {i+1} has too much narration. Shorten its text or increase its duration.')
            run([FFMPEG,'-v','error','-i',str(raw),'-af',f'atempo={rate},apad','-t',str(seconds),'-ar','44100','-ac','1','-y',str(wav)],job);raw.unlink(missing_ok=True)
        else:run([FFMPEG,'-v','error','-f','lavfi','-i','anullsrc=r=44100:cl=mono','-t',str(seconds),'-y',str(wav)],job)
        files.append(wav);job.progress(8+12*(i+1)/len(scenes),'Preparing narration')
    manifest=job.temp/'audio.txt';manifest.write_text('\n'.join(f"file '{p.name}'" for p in files));out=job.temp/'narration.wav'
    run([FFMPEG,'-v','error','-f','concat','-safe','0','-i',str(manifest),'-c','copy','-y',str(out)],job)
    return out


def timeline(project):
    scenes=[dict(s) for s in project['scenes']];weights=[float(s.get('duration',project['duration']/len(scenes))) for s in scenes];total=sum(weights)
    for s,w in zip(scenes,weights):s['duration']=w/total*project['duration']
    return scenes


def align_audio(audio,job):
    from faster_whisper import WhisperModel
    paths=list((ROOT.parent/'data/whisper-models').glob('hub/models--Systran--faster-whisper-base/snapshots/*'))
    if not paths:raise ValueError('Aligned captions require the local Whisper model. Disable caption alignment to use scene timing.')
    job.progress(18,'Aligning captions to speech')
    model=WhisperModel(str(paths[0]),device='cpu',compute_type='int8')
    segments,_=model.transcribe(str(audio),word_timestamps=True,beam_size=3)
    words=[]
    for segment in segments:
        job.check()
        words.extend({'start':w.start,'end':w.end,'text':clean(w.word)} for w in segment.words or [] if clean(w.word))
    cues=[]
    for i in range(0,len(words),5):
        group=words[i:i+5];cues.append({'start':group[0]['start'],'end':group[-1]['end'],'text':' '.join(w['text'] for w in group)})
    return cues

def render_animation(project,job,out,width=720):
    scenes=timeline(project);duration=project['duration'];fps=24;height=width*16//9
    audio=narration(project,job,duration,scenes);aligned=align_audio(audio,job) if audio and project.get('alignCaptions',True) and project.get('captions')!='none' else None;raw=job.temp/'silent.mp4';log=job.temp/'encode.log'
    with log.open('w') as err:
        proc=subprocess.Popen([FFMPEG,'-v','error','-f','rawvideo','-pix_fmt','rgb24','-s',f'{width}x{height}','-r',str(fps),'-i','pipe:0','-an','-c:v','libx264','-preset','veryfast','-crf','23','-threads','2','-pix_fmt','yuv420p','-y',str(raw)],stdin=subprocess.PIPE,stderr=err)
        try:
            offsets=[];cur=0
            for s in scenes:offsets.append(cur);cur+=s['duration']
            readers={}
            try:
                for n in range(math.ceil(duration*fps)):
                    job.check();t=n/fps;i=max(j for j,v in enumerate(offsets) if v<=t);s=scenes[i];local=t-offsets[i]
                    if s.get('visual')=='video' and s.get('assetId'):
                        if i not in readers:
                            readers[i]=subprocess.Popen([FFMPEG,'-v','error','-stream_loop','-1','-i',str(asset_path(s['assetId'])),'-vf',f'scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps={fps}','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
                        buf=readers[i].stdout.read(width*height*3)
                        if len(buf)!=width*height*3:raise ValueError('Scene video could not be decoded')
                        im=Image.frombytes('RGB',(width,height),buf);d=ImageDraw.Draw(im)
                        label(d,s.get('title',''),(width/2,height*.13),width*.8,width//14,'white',height=height*.2)
                        if project.get('captions')!='none':
                            words=clean(s.get('text','')).split();groups=[' '.join(words[k:k+7]) for k in range(0,len(words),7)];text=groups[min(len(groups)-1,int(local/s['duration']*len(groups)))] if groups else ''
                            d.rounded_rectangle((width*.04,height*.75,width*.96,height*.89),radius=10,fill='#101713');label(d,text,(width/2,height*.78),width*.84,width//20,'white',height=height*.10)
                    else:
                        rendered_scene=s
                        if aligned is not None:
                            cue=next((c for c in aligned if c['start']<=t<c['end']),None)
                            rendered_scene=dict(s,text=cue['text'] if cue else '')
                        im=frame(project,rendered_scene,local,s['duration'],width,height,i)
                    proc.stdin.write(im.tobytes())
                    if n%fps==0:job.progress(20+65*t/duration,'Rendering scenes')
            finally:
                for r in readers.values():r.terminate();r.stdout.close();r.wait(timeout=10)
            proc.stdin.close();proc.wait(timeout=90)
            if proc.returncode:raise ValueError('Video encoder failed: '+log.read_text()[-500:])
        finally:
            if proc.poll() is None:proc.terminate();proc.wait(timeout=10)
    job.progress(90,'Mixing audio and finalizing MP4')
    if project.get('musicId'):
        music=asset_path(project['musicId']);gain=max(0,min(.5,float(project.get('musicVolume',.15))))
        if audio:
            filters=f'[1:a]apad,asplit=2[voice][control];[2:a]volume={gain}[music];[music][control]sidechaincompress=threshold=0.025:ratio=8:attack=20:release=350[duck];[voice][duck]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[a]'
            run([FFMPEG,'-v','error','-i',str(raw),'-i',str(audio),'-stream_loop','-1','-i',str(music),'-filter_complex',filters,'-map','0:v','-map','[a]','-c:v','copy','-c:a','aac','-t',str(duration),'-movflags','+faststart','-y',str(out)],job)
        else:
            run([FFMPEG,'-v','error','-i',str(raw),'-stream_loop','-1','-i',str(music),'-map','0:v','-map','1:a','-af',f'volume={gain}','-c:v','copy','-c:a','aac','-t',str(duration),'-movflags','+faststart','-y',str(out)],job)
    elif audio:
        run([FFMPEG,'-v','error','-i',str(raw),'-i',str(audio),'-map','0:v','-map','1:a','-c:v','copy','-af','apad,loudnorm=I=-16:TP=-1.5:LRA=11','-c:a','aac','-b:a','128k','-t',str(duration),'-movflags','+faststart','-y',str(out)],job)
    else:shutil.move(raw,out)
    cues=[];cur=0
    for s in scenes:
        if clean(s.get('text','')):cues.append({'start':cur,'end':cur+s['duration'],'text':clean(s['text'])})
        cur+=s['duration']
    return aligned if aligned is not None else cues


def burn_clip_captions(video,cues,project,job,out,width=720):
    """PNG overlay stream works without libass; one small image per cue/gap."""
    height=width*16//9;duration=project['duration'];band=round(height*.24);entries=[];position=0
    def picture(text,seconds):
        if seconds<=.001:return
        im=Image.new('RGBA',(width,band));d=ImageDraw.Draw(im)
        if text:
            if project.get('captions')=='bold':d.rounded_rectangle((width*.04,band*.1,width*.96,band*.9),radius=12,fill=PALETTES[project.get('palette','mint')][1])
            f=font(max(18,round(width*.045)));lines=wrapped(d,text,f,width*.82);labeltext='\n'.join(lines)
            d.multiline_text((width/2,band/2),labeltext,font=f,fill='#14231f' if project.get('captions')=='bold' else 'white',anchor='mm',align='center',stroke_width=0 if project.get('captions')=='bold' else max(1,width//360),stroke_fill='black')
        name=f'caption-{len(entries)}.png';im.save(job.temp/name);entries.append((name,seconds))
    for i,c in enumerate(cues):
        start=max(position,c['start']);end=min(duration,c['end'],cues[i+1]['start'] if i+1<len(cues) else duration)
        if end<=start:continue
        picture('',start-position);picture(c['text'],end-start);position=end
    picture('',duration-position)
    if not entries:shutil.move(video,out);return
    manifest=job.temp/'captions.txt';manifest.write_text(''.join(f"file '{n}'\nduration {s:.6f}\n" for n,s in entries)+f"file '{entries[-1][0]}'\n")
    run([FFMPEG,'-v','error','-i',str(video),'-f','concat','-safe','0','-i',str(manifest),'-filter_complex',f'[0:v][1:v]overlay=0:{round(height*.66)}[v]','-map','[v]','-map','0:a?','-c:v','libx264','-preset','veryfast','-crf','23','-threads','2','-pix_fmt','yuv420p','-c:a','aac','-t',str(duration),'-movflags','+faststart','-y',str(out)],job)


def render_clip(project,job,out,width=720):
    src=asset_path(project['sourceId']);info=probe(src);height=width*16//9;start=project['start'];duration=project['duration']
    if start+duration>info['duration']+.1:raise ValueError('Clip extends past the source video')
    center=max(0,min(1,float(project.get('cropX',.5))));layout=project.get('layout','crop')
    if layout=='blur_pad':
        vf=f'[0:v]split[b][f];[b]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},gblur=sigma=20[b2];[f]scale={width}:{height}:force_original_aspect_ratio=decrease[f2];[b2][f2]overlay=(W-w)/2:(H-h)/2,setsar=1[v]'
        args=['-filter_complex',vf,'-map','[v]','-map','0:a?']
    else:args=['-vf',f'scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}:(iw-ow)*{center}:(ih-oh)/2,setsar=1']
    raw=job.temp/'clean.mp4';job.progress(15,'Cutting source at sentence boundaries')
    run([FFMPEG,'-v','error','-ss',str(start),'-i',str(src),'-t',str(duration)]+args+['-c:v','libx264','-preset','veryfast','-crf','23','-threads','2','-pix_fmt','yuv420p','-c:a','aac','-af','loudnorm=I=-16:TP=-1.5:LRA=11','-y',str(raw)],job)
    cues=[]
    for c in project.get('cues',[]):
        a=max(0,float(c['start'])-start);b=min(duration,float(c['end'])-start)
        if b>a:cues.append({'start':a,'end':b,'text':clean(c['text'])})
    job.progress(65,'Adding synchronized captions')
    if cues and project.get('captions')!='none':burn_clip_captions(raw,cues,project,job,out,width)
    else:shutil.move(raw,out)
    return cues

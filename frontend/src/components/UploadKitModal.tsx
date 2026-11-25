import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Input, InputNumber, Modal, Space, Spin, Typography, message } from 'antd'
import { CopyOutlined, DownloadOutlined, SaveOutlined } from '@ant-design/icons'
import axios from 'axios'

type TitleOption = {label:string;title:string;headline:string;reason:string}
type Kit = { thumbnailMode?:'frame'|'ai'; hasArtwork?:boolean; subject?:string; titleOptions?:TitleOption[]; title: string; description: string; tags: string[]; headline: string; frameTime: number }
type Props = { clipId: string; duration: number; open: boolean; onClose: () => void; onDownload: () => void }
export default function UploadKitModal({clipId,duration,open,onClose,onDownload}: Props) {
  const [kit,setKit]=useState<Kit | null>(null)
  const [loading,setLoading]=useState(false)
  const [saving,setSaving]=useState(false)
  const [dirty,setDirty]=useState(false)
  const [version,setVersion]=useState(0)
  const [imageError,setImageError]=useState(false)
  const [error,setError]=useState('')
  const [imageConfigured,setImageConfigured]=useState(false)
  const [generating,setGenerating]=useState(false)
  const [direction,setDirection]=useState('Cinematic, dramatic lighting, expressive close-up, vivid colors, bold readable text.')
  const [imagePrompt,setImagePrompt]=useState('')
  const fileInput=useRef<HTMLInputElement>(null)
  const generationInFlight=useRef(false)
  const base=`/api/v1/clips/${encodeURIComponent(clipId)}/upload-kit`
  useEffect(()=>{
    if(!open)return
    let active=true;setLoading(true);setError('');setKit(null);setImageError(false)
    axios.get(base+'/ai').then(r=>{if(active){setImageConfigured(r.data.configured);setImagePrompt(r.data.prompt)}}).catch(()=>{})
    axios.get(base).then(r=>{if(active){setKit(r.data);setDirty(false);setVersion(Date.now())}})
      .catch(e=>{if(active)setError(e.response?.data?.detail || 'Could not load upload details.')})
      .finally(()=>{if(active)setLoading(false)})
    return()=>{active=false}
  },[open,base])
  const change=(key:keyof Kit,value:string|string[]|number)=>{setKit(k=>k?{...k,[key]:value}:k);setDirty(true)}
  const save=async()=>{
    if(!kit)return false
    setSaving(true)
    try {await axios.put(base,kit);setDirty(false);setVersion(Date.now());setImageError(false);message.success('Upload kit saved');return true}
    catch(e:any){message.error(e.response?.data?.detail || 'Could not save upload kit');return false}
    finally{setSaving(false)}
  }
  const suggest=async()=>{
    if(!kit)return
    setSaving(true)
    try {const r=await axios.post(base+'/suggest',{subject:kit.subject});setKit(r.data);setDirty(true);message.success('New subject-first suggestions ready. Save to update the thumbnail.')}
    catch(e:any){message.error(e.response?.data?.detail || 'Could not create suggestions')}
    finally{setSaving(false)}
  }
  const generateImage=async()=>{
    if(generationInFlight.current)return
    generationInFlight.current=true
    if(dirty && !(await save())){generationInFlight.current=false;return}
    setGenerating(true)
    try {const r=await axios.post(base+'/ai',{direction},{timeout:270000});setKit(r.data);setDirty(false);setVersion(Date.now());setImageError(false);message.success('AI thumbnail ready')}
    catch(e:any){message.error(e.response?.data?.detail || 'Image request interrupted. Check the saved thumbnail before trying again; the request may still be running.')}
    finally{setGenerating(false);generationInFlight.current=false}
  }
  const uploadArtwork=async(file:File)=>{
    if(file.size>20*1024*1024){message.error('Use an image under 20 MB');return}
    if(dirty && !(await save()))return
    setSaving(true)
    try {const form=new FormData();form.append('file',file);const r=await axios.post(base+'/artwork',form);setKit(r.data);setDirty(false);setVersion(Date.now());setImageError(false)}
    catch(e:any){message.error(e.response?.data?.detail || 'Could not upload artwork')}
    finally{setSaving(false);if(fileInput.current)fileInput.current.value=''}
  }
  const chooseThumbnail=async(mode:'frame'|'ai')=>{
    if(!kit)return
    const next={...kit,thumbnailMode:mode};setSaving(true)
    try{await axios.put(base,next);setKit(next);setDirty(false);setVersion(Date.now());setImageError(false)}
    catch{message.error('Could not switch thumbnails')}
    finally{setSaving(false)}
  }
  const download=async(path:string)=>{
    if(dirty && !(await save()))return
    const link=document.createElement('a');link.href=base+path;link.download='';document.body.appendChild(link);link.click();link.remove()
  }
  const copy=async(text:string)=>{try{await navigator.clipboard.writeText(text);message.success('Copied')}catch{message.info('Select the text and copy it manually.')}}
  return <Modal open={open} onCancel={onClose} title="YouTube upload kit" width={900} footer={null} destroyOnClose>
    {loading?<Spin/>:error?<Alert type="error" message={error}/>:kit&&<fieldset disabled={generating} style={{border:0,padding:0,margin:0}}>
      <Typography.Paragraph>Lead with the game, show or main topic, then give viewers one concrete reason to watch.</Typography.Paragraph>
      <div style={{color:'var(--ac-ink, #1f2937)',marginBottom:8}}><label style={{color:"#374151",fontWeight:600}} htmlFor="upload-subject">Main subject / franchise</label></div>
      <Space.Compact style={{width:'100%',marginBottom:16}}>
        <Input id="upload-subject" placeholder="e.g. GTA 6, Suits, Minecraft" value={kit.subject || ''} maxLength={60} onChange={e=>change('subject',e.target.value)}/>
        <Button loading={saving} onClick={suggest}>Refresh suggestions</Button>
      </Space.Compact>
      <Space direction="vertical" style={{width:'100%',marginBottom:16}}>
        {kit.titleOptions?.map(option=><Button key={option.title} style={{height:'auto',whiteSpace:'normal',textAlign:'left',padding:'10px 14px'}} onClick={()=>{setKit({...kit,title:option.title,headline:option.headline});setDirty(true)}}>
          <strong>{option.label}</strong> · {option.title}<br/><span style={{fontSize:12}}>Thumbnail: {option.headline}</span>
        </Button>)}
      </Space>
      <Typography.Paragraph type="secondary">Choose a title + thumbnail pair to test. These are suggestions, not measured winners. <a href="https://support.google.com/youtube/answer/12340300?hl=en" target="_blank" rel="noreferrer">YouTube’s title guidance</a></Typography.Paragraph>
      <label style={{color:"#374151",fontWeight:600}} htmlFor="upload-title">Title</label>
      <Input id="upload-title" value={kit.title} maxLength={100} showCount onChange={e=>change('title',e.target.value)}/>
      <Button type="link" icon={<CopyOutlined/>} onClick={()=>copy(kit.title)}>Copy title</Button>
      <div><label style={{color:"#374151",fontWeight:600}} htmlFor="upload-description">Description</label></div>
      <Input.TextArea id="upload-description" rows={5} value={kit.description} maxLength={5000} showCount onChange={e=>change('description',e.target.value)}/>
      <Button type="link" icon={<CopyOutlined/>} onClick={()=>copy(kit.description)}>Copy description</Button>
      <div><label style={{color:"#374151",fontWeight:600}} htmlFor="upload-tags">Tags (comma separated)</label></div>
      <Input id="upload-tags" value={kit.tags.join(', ')} onChange={e=>change('tags',e.target.value.split(',').map(t=>t.trim()))}/>
      <Typography.Title level={5}>Thumbnail</Typography.Title>
      <Space wrap style={{marginBottom:12}}>
        <Button disabled={generating||saving} type={kit.thumbnailMode==='ai'?'default':'primary'} onClick={()=>chooseThumbnail('frame')}>Video frame</Button>
        <Button disabled={generating||saving} type={kit.thumbnailMode==='ai'?'primary':'default'} onClick={()=>chooseThumbnail('ai')}>AI artwork (default)</Button>
      </Space>
      <div style={{padding:16,border:'1px solid #d9d9d9',borderRadius:12,marginBottom:16}}>
        <label style={{color:'#374151',fontWeight:600}} htmlFor="thumbnail-direction">AI art direction</label>
        <Input.TextArea id="thumbnail-direction" rows={2} maxLength={1000} value={direction} onChange={e=>setDirection(e.target.value)} disabled={generating}/>
        <Space wrap style={{marginTop:12}}>
          <Button type="primary" loading={generating} disabled={!imageConfigured||saving} onClick={generateImage}>{generating?'Creating artwork…':kit.hasArtwork?'Generate another AI thumbnail':'Generate AI thumbnail'}</Button>
          <Button disabled={generating||saving} onClick={()=>fileInput.current?.click()}>Upload artwork</Button>
          <Button onClick={()=>copy(imagePrompt)}>Copy AI brief</Button>
          <input ref={fileInput} hidden type="file" accept="image/png,image/jpeg,image/webp" onChange={e=>{if(e.target.files?.[0])uploadArtwork(e.target.files[0])}}/>
        </Space>
        <Typography.Paragraph type="secondary" style={{marginBottom:0,marginTop:8}}>{imageConfigured?'Generates one image using your configured image API account; provider charges apply.':'In-app generation needs AUTOCLIP_IMAGE_API_KEY or OPENAI_API_KEY in the local .env file. You can upload artwork created in Codex.'} Your subject, title and clip dialogue guide the artwork. Images are created only when you click Generate.</Typography.Paragraph>
        {kit.thumbnailMode==='ai'&&kit.hasArtwork&&<Typography.Paragraph style={{marginBottom:0}}>AI artwork is selected. Its text is part of the picture; generate a new version after changing the headline.</Typography.Paragraph>}
      </div>
      <Space wrap style={{marginBottom:16}}>
        <div><label style={{color:"#374151",fontWeight:600}} htmlFor="upload-headline">Headline</label><Input id="upload-headline" value={kit.headline} maxLength={60} onChange={e=>change('headline',e.target.value)}/></div>
        {kit.thumbnailMode==='frame'&&<div><label style={{color:"#374151",fontWeight:600}} htmlFor="upload-frame">Frame at (seconds)</label><br/><InputNumber id="upload-frame" min={0} max={Math.max(0,duration-.1)} step={.5} value={kit.frameTime} onChange={v=>change('frameTime',v??0)}/></div>}
        <Button icon={<SaveOutlined/>} loading={saving} onClick={save}>Save & update preview</Button>
      </Space>
      {kit.thumbnailMode==='ai'&&!kit.hasArtwork?<div style={{padding:32,border:'2px dashed #cbd5e1',borderRadius:12,textAlign:'center',background:'#f8fafc'}}>
        <Typography.Title level={5}>Create this video’s AI thumbnail</Typography.Title>
        <Typography.Paragraph>A cinematic image around {kit.subject || 'your video’s subject'} and its main moment. Nothing is generated until you click.</Typography.Paragraph>
        <Button type="primary" loading={generating} disabled={!imageConfigured||saving} onClick={generateImage}>Generate this thumbnail</Button>
      </div>:imageError?<Alert type="warning" message="Thumbnail unavailable. Make sure this clip has finished exporting, or choose an earlier frame."/>:
        <img src={`${base}/thumbnail?v=${version}`} alt="Upload thumbnail preview" onError={()=>setImageError(true)} style={{width:'100%',maxWidth:640,maxHeight:540,objectFit:'contain',objectPosition:'left',display:'block',borderRadius:12}}/>}
      <Typography.Paragraph type="secondary">JPEG matched to the video’s orientation. Upload it under Thumbnail in YouTube Studio when custom thumbnails are available for your account. {dirty?'Unsaved changes — update the preview to see them.':''}</Typography.Paragraph>
      <Space wrap>
        <Button type="primary" icon={<DownloadOutlined/>} onClick={onDownload}>Download video</Button>
        <Button disabled={kit.thumbnailMode==='ai'&&!kit.hasArtwork} icon={<DownloadOutlined/>} onClick={()=>download('/thumbnail?download=true')}>Download thumbnail</Button>
        <Button icon={<DownloadOutlined/>} onClick={()=>download('/details')}>Download upload details</Button>
      </Space>
    </fieldset>}
  </Modal>
}

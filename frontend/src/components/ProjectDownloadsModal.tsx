import { useEffect, useState } from 'react'
import { Alert, Button, List, Modal, Spin } from 'antd'
import axios from 'axios'
import UploadKitModal from './UploadKitModal'

type Item = {id:string;title:string;duration:number;video_path?:string}
export default function ProjectDownloadsModal({projectId,open,onClose}:{projectId:string;open:boolean;onClose:()=>void}) {
  const [items,setItems]=useState<Item[]>([])
  const [loading,setLoading]=useState(false)
  const [error,setError]=useState('')
  const [selected,setSelected]=useState<Item|null>(null)
  useEffect(()=>{
    if(!open)return
    let active=true;setLoading(true);setError('')
    ;(async()=>{
      const all:Item[]=[];let page=1
      while(true){
        const response=await axios.get('/api/v1/clips/',{params:{project_id:projectId,page,size:100}})
        if(!active)return
        all.push(...response.data.items)
        if(!response.data.pagination.has_next)break
        page++
      }
      if(active)setItems(all)
    })().catch(()=>{if(active)setError('Could not load the project videos. Please try again.')}).finally(()=>{if(active)setLoading(false)})
    return()=>{active=false}
  },[projectId,open])
  const url=(id:string)=>`/api/v1/projects/${encodeURIComponent(projectId)}/download?clip_id=${encodeURIComponent(id)}`
  const download=(id:string)=>{const a=document.createElement('a');a.href=url(id);a.download='';document.body.appendChild(a);a.click();a.remove()}
  return <div onClick={e=>e.stopPropagation()}>
    <Modal open={open} onCancel={onClose} title="Download videos & upload kits" footer={null} width={740}>
      {loading?<Spin/>:error?<Alert type="error" message={error}/>:<List dataSource={items} locale={{emptyText:'No exported clips yet.'}} renderItem={item=><List.Item actions={[
        <Button key="video" href={url(item.id)} download disabled={!item.video_path}>Download MP4</Button>,
        <Button key="kit" onClick={()=>setSelected(item)}>Upload kit</Button>
      ]}><List.Item.Meta title={item.title} description={`${item.duration} seconds`}/></List.Item>}/>}
    </Modal>
    {selected&&<UploadKitModal open={!!selected} clipId={selected.id} duration={selected.duration} onClose={()=>setSelected(null)} onDownload={()=>download(selected.id)}/>}
  </div>
}

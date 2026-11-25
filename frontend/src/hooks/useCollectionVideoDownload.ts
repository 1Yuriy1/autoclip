import { useState } from 'react'
import { message } from 'antd'
import { projectApi } from '../services/api'

export const useCollectionVideoDownload = () => {
  const [isGenerating, setIsGenerating] = useState(false)

  const generateAndDownloadCollectionVideo = async (
    projectId: string, 
    collectionId: string,
    _collectionTitle: string
  ) => {
    if (isGenerating) return

    setIsGenerating(true)
    
    try {
      // 直接按用户当前调整的顺序生成合集视频
      message.info("Generating the collection video in your selected order...")
      
      // 生成合集视频（按用户调整的顺序）
      await projectApi.generateCollectionVideo(projectId, collectionId)
      
      // 等待1秒让后端完成文件生成，然后下载
      message.success("Collection video generated. Downloading...")
      
      setTimeout(async () => {
        try {
          await projectApi.downloadVideo(projectId, undefined, collectionId)
          message.success("Collection video downloaded.")
        } catch (downloadError) {
          console.error("Download failed:", downloadError)
          message.error("Download failed. Please try again later.")
        }
      }, 1000)
      
    } catch (error) {
      console.error('生成合集视频失败:', error)
      message.error("Could not generate the collection video.")
    } finally {
      setIsGenerating(false)
    }
  }

  return {
    isGenerating,
    generateAndDownloadCollectionVideo
  }
} 
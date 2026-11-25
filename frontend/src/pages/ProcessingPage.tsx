import React, { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Layout, Card, Progress, Steps, Typography, Button, Alert, Space, Spin, message } from 'antd'
import { CheckCircleOutlined, LoadingOutlined, ExclamationCircleOutlined, ArrowLeftOutlined } from '@ant-design/icons'
import { projectApi } from '../services/api'
import { useProjectStore } from '../store/useProjectStore'

const { Content } = Layout
const { Title, Text } = Typography
const { Step } = Steps

interface ProcessingStatus {
  status: 'processing' | 'completed' | 'error'
  current_step: number
  total_steps: number
  step_name: string
  progress: number
  error_message?: string
}

const ProcessingPage: React.FC = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { currentProject, setCurrentProject } = useProjectStore()
  const [status, setStatus] = useState<ProcessingStatus | null>(null)
  const [loading, setLoading] = useState(true)

  const steps = [
    { title: "Outline extraction", description: "Extracting a structured outline from the transcript" },
    { title: "Timing detection", description: "Finding topic time ranges from SRT captions" },
    { title: "Content scoring", description: "Evaluating clip quality and sharing potential" },
    { title: "Title generation", description: "Creating engaging titles for top clips" },
    { title: "Topic grouping", description: "Grouping related clips into collections" },
    { title: "Video clipping", description: "Creating clips and collection videos with FFmpeg" }
  ]

  useEffect(() => {
    if (!id) return
    
    loadProject()
    const interval = setInterval(checkStatus, 2000) // 每2秒检查一次状态
    
    return () => clearInterval(interval)
  }, [id])

  const loadProject = async () => {
    if (!id) return
    
    try {
      const project = await projectApi.getProject(id)
      setCurrentProject(project)
      
      // 如果项目已完成，直接跳转到详情页
      if (project.status === 'completed') {
        navigate(`/project/${id}`)
        return
      }
      
      // 如果项目状态是等待处理，开始处理
      if (project.status === 'pending') {
        await startProcessing()
      }
    } catch (error) {
      message.error("Could not load projects.")
      console.error('Load project error:', error)
    } finally {
      setLoading(false)
    }
  }

  const startProcessing = async () => {
    if (!id) return
    
    try {
      await projectApi.startProcessing(id)
      message.success('开始处理项目')
    } catch (error) {
      message.error("Could not start processing.")
      console.error('Start processing error:', error)
    }
  }

  const checkStatus = async () => {
    if (!id) return
    
    try {
      const statusData = await projectApi.getProcessingStatus(id)
      setStatus(statusData)
      
      // 如果处理完成，跳转到项目详情页
      if (statusData.status === 'completed') {
        message.success('🎉 视频处理完成！正在跳转到结果页面...')
        setTimeout(() => {
          navigate(`/project/${id}`)
        }, 2000)
      }
      
      // 如果处理失败，显示详细错误信息
      if (statusData.status === 'error') {
        const errorMsg = statusData.error_message || '处理过程中发生未知错误'
        message.error(`处理失败: ${errorMsg}`)
        
        // 提供重试选项
        message.info('您可以返回首页重新上传文件或联系技术支持', 5)
      }
      
    } catch (error: any) {
      console.error('Check status error:', error)
      
      // 根据错误类型提供不同的处理建议
      if (error.response?.status === 404) {
        message.error('项目不存在或已被删除')
        setTimeout(() => navigate('/'), 2000)
      } else if (error.code === 'ECONNABORTED') {
        message.warning('网络连接超时，正在重试...')
      } else {
        message.error('获取处理状态失败，请刷新页面重试')
      }
    }
  }

  const getStepStatus = (stepIndex: number) => {
    if (!status) return 'wait'
    
    if (status.status === 'error') {
      return stepIndex < status.current_step ? 'finish' : 'error'
    }
    
    if (stepIndex < status.current_step) return 'finish'
    if (stepIndex === status.current_step) return 'process'
    return 'wait'
  }

  const getStepIcon = (stepIndex: number) => {
    const stepStatus = getStepStatus(stepIndex)
    
    if (stepStatus === 'finish') return <CheckCircleOutlined />
    if (stepStatus === 'process') return <LoadingOutlined />
    if (stepStatus === 'error') return <ExclamationCircleOutlined />
    return null
  }

  if (loading) {
    return (
      <Content style={{ padding: '24px', display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '400px' }}>
        <Spin size="large" tip="加载中..." />
      </Content>
    )
  }

  return (
    <Content style={{ padding: '24px', maxWidth: '1000px', margin: '0 auto' }}>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Title level={2}>视频处理进度</Title>
          <Button 
            icon={<ArrowLeftOutlined />} 
            onClick={() => navigate('/')}
          >
            Back to home
          </Button>
        </div>

        {currentProject && (
          <Card>
            <Title level={4}>{currentProject.name}</Title>
            <Text type="secondary">项目ID: {currentProject.id}</Text>
          </Card>
        )}

        {status?.status === 'error' && (
          <Alert
            message="Processing failed"
            description={
              <div>
                <p>{status.error_message || '处理过程中发生未知错误'}</p>
                <p style={{ marginTop: '8px', fontSize: '12px', color: '#666' }}>
                  可能的原因：文件格式不支持、文件损坏、网络问题或服务器错误
                </p>
              </div>
            }
            type="error"
            showIcon
            action={
              <Space>
                <Button size="small" onClick={() => window.location.reload()}>
                  Refresh page
                </Button>
                <Button size="small" onClick={() => navigate('/')}>
                  Back to home
                </Button>
              </Space>
            }
          />
        )}

        {status && status.status === 'processing' && (
          <Card title="处理进度">
            <Space direction="vertical" size="large" style={{ width: '100%' }}>
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                  <Text strong>Overall progress</Text>
                  <Text>{Math.round(status.progress)}%</Text>
                </div>
                <Progress 
                  percent={status.progress} 
                  status="active"
                  strokeColor={{
                    '0%': '#108ee9',
                    '100%': '#87d068',
                  }}
                />
              </div>

              <div>
                <Text strong>当前步骤: </Text>
                <Text>{status.step_name}</Text>
              </div>

              <Steps 
                direction="vertical" 
                current={status.current_step}
                status="process"
              >
                {steps.map((step, index) => (
                  <Step
                    key={index}
                    title={step.title}
                    description={step.description}
                    status={getStepStatus(index)}
                    icon={getStepIcon(index)}
                  />
                ))}
              </Steps>
            </Space>
          </Card>
        )}

        {status?.status === 'completed' && (
          <Alert
            message="Processing complete"
            description="视频已成功处理完成，正在跳转到项目详情页..."
            type="success"
            showIcon
          />
        )}
      </Space>
    </Content>
  )
}

export default ProcessingPage
import React, { useState, useEffect } from 'react'
import { Layout, Card, Form, Input, Button, Typography, Space, Alert, Divider, Row, Col, Tabs, message, Select, Tag, Switch } from 'antd'
import { KeyOutlined, SaveOutlined, ApiOutlined, SettingOutlined, InfoCircleOutlined, UserOutlined, RobotOutlined, SoundOutlined, PoweroffOutlined } from '@ant-design/icons'
import { settingsApi } from '../services/api'
import BilibiliManager from '../components/BilibiliManager'
import SpeechRecognitionConfig from '../components/SpeechRecognitionConfig'
import { isDesktopMode } from '../utils/desktopMode'
import { trackApiKeyConfigured } from '../analytics/events'
import { isAnalyticsEnabled, setAnalyticsEnabled } from '../analytics/posthog'
import './SettingsPage.css'

const { Content } = Layout
const { Title, Text, Paragraph } = Typography
const { TabPane } = Tabs

const SettingsPage: React.FC = () => {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [showBilibiliManager, setShowBilibiliManager] = useState(false)
  const [currentProvider, setCurrentProvider] = useState<any>({})
  const [selectedProvider, setSelectedProvider] = useState('dashscope')
  const [analyticsOn, setAnalyticsOn] = useState(isAnalyticsEnabled())

  // 提供商配置
  const providerConfig = {
    dashscope: {
      name: "Alibaba Qwen",
      icon: <RobotOutlined />,
      color: '#1890ff',
      description: "Alibaba Cloud Qwen models",
      apiKeyField: 'dashscope_api_key',
      placeholder: "Enter your Qwen API key"
    },
    openai: {
      name: 'OpenAI',
      icon: <RobotOutlined />,
      color: '#52c41a',
      description: "OpenAI GPT models",
      apiKeyField: 'openai_api_key',
      placeholder: "Enter your OpenAI API key"
    },
    gemini: {
      name: 'Google Gemini',
      icon: <RobotOutlined />,
      color: '#faad14',
      description: "Google Gemini models",
      apiKeyField: 'gemini_api_key',
      placeholder: "Enter your Gemini API key"
    },
    siliconflow: {
      name: "SiliconFlow",
      icon: <RobotOutlined />,
      color: '#722ed1',
      description: "SiliconFlow model service",
      apiKeyField: 'siliconflow_api_key',
      placeholder: "Enter your SiliconFlow API key"
    }
  }

  // 加载数据
  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    try {
      // 检查是否在Desktop模式下运行
      const isDesktop = await isDesktopMode()
      
      if (isDesktop) {
        // Desktop模式：调用完整的API
        const [settings, models, provider] = await Promise.allSettled([
          settingsApi.getSettings(),
          settingsApi.getAvailableModels(),
          settingsApi.getCurrentProvider()
        ])
        
        // 检查是否有失败的请求
        const failedRequests = [settings, models, provider].filter(result => result.status === 'rejected')
        if (failedRequests.length > 0) {
          console.warn('部分API请求失败:', failedRequests.map(r => (r as PromiseRejectedResult).reason))
        }
        
        // 处理设置数据
        const settingsData = settings.status === 'fulfilled' ? settings.value : {}
        
        // 处理模型数据
        const modelsData = models.status === 'fulfilled' ? models.value.models : {}
        
        // 处理提供商数据
        const providerData = provider.status === 'fulfilled'
          ? provider.value
          : { available: false, provider: 'dashscope', display_name: "Alibaba Qwen", model: 'qwen-plus' }
        const providerName = providerData.provider || 'dashscope'
        setCurrentProvider(providerData)
        
        // 将嵌套的settings结构转换为扁平结构
        const flatSettings = {
          llm_provider: providerName, // 使用实际的提供商
          dashscope_api_key: settingsData.api?.api_keys?.dashscope || '',
          openai_api_key: settingsData.api?.api_keys?.openai || '',
          gemini_api_key: settingsData.api?.api_keys?.gemini || '',
          siliconflow_api_key: settingsData.api?.api_keys?.siliconflow || '',
          jimeng_access_key: settingsData.api?.api_keys?.jimeng_access || '',
          jimeng_secret_key: settingsData.api?.api_keys?.jimeng_secret || '',
          model_name: settingsData.api?.api_model || 'qwen-plus',
          chunk_size: settingsData.processing?.processing_chunk_size || 5000,
          min_score_threshold: settingsData.processing?.processing_min_score || 0.7,
          max_clips_per_collection: settingsData.processing?.processing_max_clips || 5
        }
        
        setSelectedProvider(providerName)
        
        // 设置表单初始值
        form.setFieldsValue(flatSettings)
        console.log('Desktop模式 - 设置表单值:', flatSettings)
        console.log('可用模型:', modelsData)
        console.log('当前提供商:', providerData)
      } else {
        // Web模式：使用默认配置，不调用Desktop API
        console.log('Web模式 - 使用默认配置')
        
        const flatSettings = {
          llm_provider: 'dashscope',
          dashscope_api_key: '',
          openai_api_key: '',
          gemini_api_key: '',
          siliconflow_api_key: '',
          jimeng_access_key: '',
          jimeng_secret_key: '',
          model_name: 'qwen-plus',
          chunk_size: 5000,
          min_score_threshold: 0.7,
          max_clips_per_collection: 5
        }
        
        setSelectedProvider('dashscope')
        form.setFieldsValue(flatSettings)
        
        // 设置默认模型数据
        setCurrentProvider({
          available: false,
          provider: 'dashscope',
          display_name: "Alibaba Qwen",
          model: 'qwen-plus'
        })
      }
    } catch (error) {
      console.error('加载数据失败:', error)
    }
  }

  // 保存配置
  const handleSave = async (values: any) => {
    try {
      setLoading(true)
      
      // 检查是否在Desktop模式下运行
      const isDesktop = await isDesktopMode()
      
      if (!isDesktop) {
        // Web模式：只显示提示，不实际保存
        message.info("Settings cannot be saved in web mode. Use the desktop app for full functionality.")
        setLoading(false)
        return
      }
      
      // 先获取现有配置，避免清空已有的API key
      let existingSettings = null
      try {
        existingSettings = await settingsApi.getSettings()
      } catch (error) {
        console.warn('获取现有配置失败，将使用默认配置:', error)
      }
      
      // 获取现有的API keys，只更新有值的字段
      const existingApiKeys = existingSettings?.api?.api_keys || {}
      
      // 转换扁平数据为后端期望的嵌套结构
      const backendSettings = {
        basic: {
          app_name: "AutoClip Desktop",
          app_version: "1.0.0",
          debug_mode: false,
          auto_start: true
        },
        service: {
          host: "127.0.0.1",
          port: 8000,
          max_memory_usage: 2048
        },
        api: {
          api_keys: {
            // 只更新有值的API key，保持现有的值
            dashscope: values.dashscope_api_key || existingApiKeys.dashscope || "",
            openai: values.openai_api_key || existingApiKeys.openai || "",
            gemini: values.gemini_api_key || existingApiKeys.gemini || "",
            siliconflow: values.siliconflow_api_key || existingApiKeys.siliconflow || "",
            jimeng_access: values.jimeng_access_key || existingApiKeys.jimeng_access || "",
            jimeng_secret: values.jimeng_secret_key || existingApiKeys.jimeng_secret || ""
          },
          api_model: values.model_name || "qwen-plus",
          api_max_tokens: 4096,
          api_timeout: 30
        },
        processing: {
          processing_chunk_size: values.chunk_size || 5000,
          processing_min_score: values.min_score_threshold || 0.7,
          processing_max_clips: values.max_clips_per_collection || 5,
          processing_max_retries: 3
        },
        logs: {
          log_level: "INFO",
          log_retention_days: 7
        },
        paths: {
          data_directory: "/Users/zhoukk/Library/Application Support/AutoClip",
          cache_directory: "/Users/zhoukk/Library/Application Support/AutoClip/cache",
          temp_directory: "/Users/zhoukk/Library/Application Support/AutoClip/temp"
        }
      }
      
      await settingsApi.updateSettings(backendSettings)
      message.success("Settings saved!")

      // 埋点：记录配置了哪个 provider 的 key（不传 key 明文）
      const apiKeyField = providerConfig[selectedProvider as keyof typeof providerConfig]?.apiKeyField
      if (apiKeyField) {
        trackApiKeyConfigured({
          provider: selectedProvider,
          hasKey: !!values[apiKeyField],
        })
      }

      await loadData() // 重新加载数据
    } catch (error: any) {
      message.error("Save failed:" + (error.message || "Unknown error"))
    } finally {
      setLoading(false)
    }
  }

  // 测试API密钥
  const handleTestApiKey = async () => {
    const apiKey = form.getFieldValue(providerConfig[selectedProvider as keyof typeof providerConfig].apiKeyField)
    
    if (!apiKey || apiKey.trim() === '') {
      message.error("Enter an API key first.")
      return
    }

    try {
      setLoading(true)
      const result = await settingsApi.testApiKey(selectedProvider, apiKey)
      if (result.success) {
        message.success("API key test succeeded!")
      } else {
        message.error("API key test failed:" + (result.error || "Unknown error"))
      }
    } catch (error: any) {
      message.error("Test failed:" + (error.message || "Unknown error"))
    } finally {
      setLoading(false)
    }
  }

  // 提供商切换
  const handleProviderChange = (provider: string) => {
    setSelectedProvider(provider)
    form.setFieldsValue({ llm_provider: provider })
  }

  return (
    <Content className="settings-page">
      <div className="settings-container">
        <Title level={2} className="settings-title">
          <SettingOutlined /> Settings
        </Title>
        
        <Tabs defaultActiveKey="api" className="settings-tabs">
          <TabPane tab="AI model" key="api">
            <Card title="AI model" className="settings-card">
              <Alert
                message="Multiple AI providers"
                description="AutoClip supports multiple AI providers, so you can choose the service and model that best fit your needs."
                type="info"
                showIcon
                className="settings-alert"
              />
              
              <Form
                form={form}
                layout="vertical"
                className="settings-form"
                onFinish={handleSave}
                initialValues={{
                  llm_provider: 'dashscope',
                  model_name: 'qwen-plus',
                  chunk_size: 5000,
                  min_score_threshold: 0.7,
                  max_clips_per_collection: 5
                }}
              >
                {/* 当前提供商状态 */}
                {currentProvider.available && (
                  <Alert
                    message={`Currently using: ${currentProvider.display_name} - ${currentProvider.model}`}
                    type="success"
                    showIcon
                    style={{ marginBottom: 24 }}
                  />
                )}

                {/* 提供商选择 */}
                <Form.Item
                  label="Choose an AI provider"
                  name="llm_provider"
                  className="form-item"
                  rules={[{ required: true, message: "Choose an AI provider" }]}
                >
                  <Select
                    value={selectedProvider}
                    onChange={handleProviderChange}
                    className="settings-input"
                    placeholder="Choose an AI provider"
                  >
                    {Object.entries(providerConfig).map(([key, config]) => (
                      <Select.Option key={key} value={key}>
                        <Space>
                          <span style={{ color: config.color }}>{config.icon}</span>
                          <span>{config.name}</span>
                          <Tag color={config.color}>{config.description}</Tag>
                        </Space>
                      </Select.Option>
                    ))}
                  </Select>
                </Form.Item>

                {/* 动态API密钥输入 */}
                <Form.Item
                  label={`${providerConfig[selectedProvider as keyof typeof providerConfig].name} API Key`}
                  name={providerConfig[selectedProvider as keyof typeof providerConfig].apiKeyField}
                  className="form-item"
                  rules={[
                    { required: true, message: "Enter an API key" },
                    { min: 10, message: "The API key must be at least 10 characters." }
                  ]}
                >
                  <Input.Password
                    placeholder={providerConfig[selectedProvider as keyof typeof providerConfig].placeholder}
                    prefix={<KeyOutlined />}
                    className="settings-input"
                  />
                </Form.Item>

                {/* 模型选择 - 改进版本 */}
                <Form.Item
                  label="Choose a model"
                  name="model_name"
                  className="form-item"
                  rules={[{ required: true, message: "Enter or choose a model" }]}
                  extra="Enter a model name or choose a commonly used model."
                >
                  <Select
                    className="settings-input"
                    placeholder="Enter or choose a model"
                    showSearch
                    allowClear
                    mode="tags"
                    dropdownRender={(menu) => (
                      <div>
                        {menu}
                        <Divider style={{ margin: '8px 0' }} />
                        <div style={{ padding: '0 8px 4px' }}>
                          <Text type="secondary" style={{ fontSize: '12px' }}>
                            Common models by provider
                          </Text>
                        </div>
                      </div>
                    )}
                  >
                    {/* 通义千问模型 */}
                    <Select.OptGroup label="Qwen (DashScope)">
                      <Select.Option value="qwen-plus">qwen-plus (Qwen Plus)</Select.Option>
                      <Select.Option value="qwen-turbo">qwen-turbo (Qwen Turbo)</Select.Option>
                      <Select.Option value="qwen-max">qwen-max (Qwen Max)</Select.Option>
                      <Select.Option value="qwen-long">qwen-long (Qwen Long Context)</Select.Option>
                    </Select.OptGroup>
                    
                    {/* OpenAI模型 */}
                    <Select.OptGroup label="OpenAI">
                      <Select.Option value="gpt-4o">gpt-4o (GPT-4 Omni)</Select.Option>
                      <Select.Option value="gpt-4o-mini">gpt-4o-mini (GPT-4 Omni Mini)</Select.Option>
                      <Select.Option value="gpt-4-turbo">gpt-4-turbo (GPT-4 Turbo)</Select.Option>
                      <Select.Option value="gpt-4">gpt-4 (GPT-4)</Select.Option>
                      <Select.Option value="gpt-3.5-turbo">gpt-3.5-turbo (GPT-3.5 Turbo)</Select.Option>
                    </Select.OptGroup>
                    
                    {/* Google Gemini模型 */}
                    <Select.OptGroup label="Google Gemini">
                      <Select.Option value="gemini-1.5-pro">gemini-1.5-pro (Gemini 1.5 Pro)</Select.Option>
                      <Select.Option value="gemini-1.5-flash">gemini-1.5-flash (Gemini 1.5 Flash)</Select.Option>
                      <Select.Option value="gemini-pro">gemini-pro (Gemini Pro)</Select.Option>
                    </Select.OptGroup>
                    
                    {/* 硅基流动模型 */}
                    <Select.OptGroup label="SiliconFlow">
                      <Select.Option value="deepseek-chat">deepseek-chat (DeepSeek Chat)</Select.Option>
                      <Select.Option value="deepseek-coder">deepseek-coder (DeepSeek Coder)</Select.Option>
                      <Select.Option value="qwen-plus">qwen-plus (Qwen Plus)</Select.Option>
                      <Select.Option value="qwen-turbo">qwen-turbo (Qwen Turbo)</Select.Option>
                    </Select.OptGroup>
                    
                  </Select>
                </Form.Item>

                <Form.Item className="form-item">
                  <Space>
                    <Button
                      type="default"
                      icon={<ApiOutlined />}
                      className="test-button"
                      onClick={handleTestApiKey}
                      loading={loading}
                    >
                      Test connection
                    </Button>
                  </Space>
                </Form.Item>

                <Divider className="settings-divider" />

                <Title level={4} className="section-title">Model settings</Title>
                
                <Row gutter={16}>
                  <Col span={12}>
                    <Form.Item
                      label="Text chunk size"
                      name="chunk_size"
                      className="form-item"
                    >
                      <Input 
                        type="number" 
                        placeholder="5000" 
                        addonAfter="characters"
                        className="settings-input"
                      />
                    </Form.Item>
                  </Col>
                </Row>

                <Row gutter={16}>
                  <Col span={12}>
                    <Form.Item
                      label="Minimum score threshold"
                      name="min_score_threshold"
                      className="form-item"
                    >
                      <Input 
                        type="number" 
                        step="0.1" 
                        min="0" 
                        max="1" 
                        placeholder="0.7" 
                        className="settings-input"
                      />
                    </Form.Item>
                  </Col>
                  <Col span={12}>
                    <Form.Item
                      label="Maximum clips per collection"
                      name="max_clips_per_collection"
                      className="form-item"
                    >
                      <Input 
                        type="number" 
                        placeholder="5" 
                        addonAfter="clips"
                        className="settings-input"
                      />
                    </Form.Item>
                  </Col>
                </Row>

                <Form.Item className="form-item">
                  <Button
                    type="primary"
                    htmlType="submit"
                    icon={<SaveOutlined />}
                    size="large"
                    className="save-button"
                    loading={loading}
                  >
                    Save settings
                  </Button>
                </Form.Item>
              </Form>
            </Card>

            <Card title="Help" className="settings-card">
              <Space direction="vertical" size="large" className="instructions-space">
                <div className="instruction-item">
                  <Title level={5} className="instruction-title">
                    <InfoCircleOutlined /> 1. Choose an AI provider
                  </Title>
                  <Paragraph className="instruction-text">
                    Supported AI providers:
                    <br />• <Text strong>Alibaba Qwen</Text>: get an API key from the Alibaba Cloud console
                    <br />• <Text strong>OpenAI</Text>: get an API key from platform.openai.com
                    <br />• <Text strong>Google Gemini</Text>: get an API key from ai.google.dev
                    <br />• <Text strong>SiliconFlow</Text>: get an API key from docs.siliconflow.cn
                  </Paragraph>
                </div>
                
                <div className="instruction-item">
                  <Title level={5} className="instruction-title">
                    <InfoCircleOutlined /> 2. Configuration options
                  </Title>
                  <Paragraph className="instruction-text">
                    • <Text strong>Text chunk size</Text>: affects speed and accuracy; 5,000 characters is recommended<br />
                    • <Text strong>Score threshold</Text>: only clips above this score are kept<br />
                    • <Text strong>Collection clip count</Text>: controls the number of clips in each themed collection
                  </Paragraph>
                </div>
                
                <div className="instruction-item">
                  <Title level={5} className="instruction-title">
                    <InfoCircleOutlined /> 3. Test the connection
                  </Title>
                  <Paragraph className="instruction-text">
                    Test your API key before saving to make sure the service is working.
                  </Paragraph>
                </div>
              </Space>
            </Card>
          </TabPane>

          <TabPane 
            tab={
              <span>
                <SoundOutlined />
                Speech transcription
              </span>
            } 
            key="speech"
          >
            <Card title="Speech transcription" className="settings-card">
              <Alert
                message="Speech recognition service"
                description="Configure speech transcription for caption generation and speech recognition. Local Whisper models and several cloud APIs are supported."
                type="info"
                showIcon
                className="settings-alert"
              />
              
              <SpeechRecognitionConfig
                onConfigChange={(config) => {
                  console.log('语音配置已更新:', config)
                  // 移除重复的成功提示，SpeechRecognitionConfig内部已经处理
                }}
              />
            </Card>
          </TabPane>

          <TabPane 
            tab={
              <span>
                <SettingOutlined />
                App settings
              </span>
            } 
            key="app"
          >
            <Card title="App settings" className="settings-card">
              <Alert
                message="App behavior"
                description="Configure startup behavior and system integration."
                type="info"
                showIcon
                className="settings-alert"
              />
              
              <AppSettings />
            </Card>

            <Card title="Privacy and data" className="settings-card" style={{ marginTop: 16 }}>
              <Alert
                message="Usage analytics"
                description="To improve AutoClip, we collect anonymous usage data such as feature usage and export success or failure. We never collect your videos, transcript text, or API keys. You can turn this off at any time."
                type="info"
                showIcon
                className="settings-alert"
              />
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 16 }}>
                <div>
                  <Text strong>Allow anonymous usage analytics</Text>
                  <Paragraph type="secondary" style={{ margin: '4px 0 0' }}>
                    No usage data is sent when this is disabled.
                  </Paragraph>
                </div>
                <Switch
                  checked={analyticsOn}
                  onChange={(checked) => {
                    setAnalyticsEnabled(checked)
                    setAnalyticsOn(checked)
                    message.success(checked ? "Anonymous usage analytics enabled." : "Anonymous usage analytics disabled.")
                  }}
                />
              </div>
            </Card>
          </TabPane>

          <TabPane tab="Bilibili" key="bilibili">
            <Card title="Bilibili accounts" className="settings-card">
              <div style={{ textAlign: 'center', padding: '40px 20px' }}>
                <div style={{ marginBottom: '24px' }}>
                  <UserOutlined style={{ fontSize: '48px', color: '#1890ff', marginBottom: '16px' }} />
                  <Title level={3} style={{ color: 'var(--ac-ink)', margin: '0 0 8px 0' }}>
                    Bilibili accounts
                  </Title>
                  <Text type="secondary" style={{ color: '#b0b0b0', fontSize: '16px' }}>
                    Manage multiple Bilibili accounts and publish clips quickly.
                  </Text>
                </div>
                
                <Space size="large">
                  <Button
                    type="primary"
                    size="large"
                    icon={<UserOutlined />}
                    onClick={() => message.info("Coming soon", 3)}
                    style={{
                      borderRadius: '8px',
                      background: 'linear-gradient(45deg, #1890ff, #36cfc9)',
                      border: 'none',
                      fontWeight: 500,
                      height: '48px',
                      padding: '0 32px',
                      fontSize: '16px'
                    }}
                  >
                    Manage Bilibili accounts
                  </Button>
                </Space>
                
                <div style={{ marginTop: '32px', textAlign: 'left', maxWidth: '600px', margin: '32px auto 0' }}>
                  <Title level={4} style={{ color: 'var(--ac-ink)', marginBottom: '16px' }}>
                    Features
                  </Title>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: '16px' }}>
                    <div style={{ 
                      padding: '16px', 
                      background: 'rgba(255,255,255,0.05)', 
                      borderRadius: '8px',
                      border: '1px solid #404040'
                    }}>
                      <Text strong style={{ color: '#1890ff' }}>Multiple accounts</Text>
                      <br />
                      <Text type="secondary" style={{ color: '#b0b0b0' }}>
                        Add and switch between multiple Bilibili accounts.
                      </Text>
                    </div>
                    <div style={{ 
                      padding: '16px', 
                      background: 'rgba(255,255,255,0.05)', 
                      borderRadius: '8px',
                      border: '1px solid #404040'
                    }}>
                      <Text strong style={{ color: '#52c41a' }}>Secure sign-in</Text>
                      <br />
                      <Text type="secondary" style={{ color: '#b0b0b0' }}>
                        Import cookies for a reliable sign-in experience.
                      </Text>
                    </div>
                    <div style={{ 
                      padding: '16px', 
                      background: 'rgba(255,255,255,0.05)', 
                      borderRadius: '8px',
                      border: '1px solid #404040'
                    }}>
                      <Text strong style={{ color: '#faad14' }}>Quick publishing</Text>
                      <br />
                      <Text type="secondary" style={{ color: '#b0b0b0' }}>
                        Publish from a clip page by selecting an account.
                      </Text>
                    </div>
                    <div style={{ 
                      padding: '16px', 
                      background: 'rgba(255,255,255,0.05)', 
                      borderRadius: '8px',
                      border: '1px solid #404040'
                    }}>
                      <Text strong style={{ color: '#722ed1' }}>Batch management</Text>
                      <br />
                      <Text type="secondary" style={{ color: '#b0b0b0' }}>
                        Upload multiple clips in a batch.
                      </Text>
                    </div>
                  </div>
                </div>
              </div>
            </Card>
          </TabPane>
        </Tabs>

        {/* B站管理弹窗 */}
        <BilibiliManager
          visible={showBilibiliManager}
          onClose={() => setShowBilibiliManager(false)}
          onUploadSuccess={() => {
            message.success("Done")
          }}
        />
      </div>
    </Content>
  )
}

// 应用设置组件
const AppSettings: React.FC = () => {
  const [autostartEnabled, setAutostartEnabled] = useState(false)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    checkAutostartStatus()
  }, [])

  const checkAutostartStatus = async () => {
    try {
      const isDesktop = await isDesktopMode()
      if (isDesktop) {
        const { invoke } = await import('@tauri-apps/api/core')
        const enabled = await invoke('is_autostart_enabled')
        setAutostartEnabled(Boolean(enabled))
      }
    } catch (error) {
      console.error('检查自动启动状态失败:', error)
    }
  }

  const handleAutostartToggle = async (enabled: boolean) => {
    const isDesktop = await isDesktopMode()
    if (!isDesktop) {
      message.error("This feature is available only in the desktop app.")
      return
    }

    setLoading(true)
    try {
      const { invoke } = await import('@tauri-apps/api/core')
      
      if (enabled) {
        await invoke('enable_autostart')
        message.success("Launch at startup enabled.")
      } else {
        await invoke('disable_autostart')
        message.success("Launch at startup disabled.")
      }
      
      setAutostartEnabled(enabled)
    } catch (error) {
      console.error('切换自动启动状态失败:', error)
      message.error(`Action failed: ${error}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <Row gutter={[16, 16]}>
        <Col span={24}>
          <Card 
            size="small" 
            style={{ 
              background: 'rgba(255,255,255,0.05)', 
              border: '1px solid #404040',
              marginBottom: '16px'
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', marginBottom: '8px' }}>
                  <PoweroffOutlined style={{ color: '#1890ff', marginRight: '8px' }} />
                  <Text strong style={{ color: 'var(--ac-ink)' }}>Launch at startup</Text>
                </div>
                <Text type="secondary" style={{ color: '#b0b0b0' }}>
                  When enabled, AutoClip starts automatically with your system.
                </Text>
              </div>
              <Switch
                checked={autostartEnabled}
                onChange={handleAutostartToggle}
                loading={loading}
                checkedChildren="On"
                unCheckedChildren="Off"
              />
            </div>
          </Card>
        </Col>
      </Row>
      
      <Alert
        message="Note"
        description="Launch at startup is available only in the desktop app. When enabled, AutoClip starts with your system and remains accessible from the system tray."
        type="info"
        showIcon
        style={{ marginTop: '16px' }}
      />
    </div>
  )
}

export default SettingsPage

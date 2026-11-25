/**
 * 投稿相关API服务
 */

import api from './api'

// 类型定义
export interface BilibiliAccount {
  id: string
  username: string
  nickname?: string
  status: string
  is_default: boolean
  created_at: string
}

export interface UploadRequest {
  clip_ids: string[]
  account_id: string
  title: string
  description: string
  tags: string[]
  partition_id: number
}

export interface UploadRecord {
  id: string | number
  task_id?: string
  project_id?: string
  account_id: string | number
  clip_id: string
  title: string
  description?: string
  tags?: string
  partition_id: number
  video_path?: string
  bv_id?: string
  av_id?: string
  status: string
  error_message?: string
  progress: number
  file_size?: number
  upload_duration?: number
  created_at: string
  updated_at: string
  account_username?: string
  account_nickname?: string
  project_name?: string
}

export interface UploadStatus {
  id: string
  status: string
  bvid?: string
  error_message?: string
  created_at: string
}

// B站分区信息 - 根据官方API文档更新，一级主分区
export const BILIBILI_PARTITIONS = [
  { id: 1, name: "Animation" },
  { id: 4, name: "Gaming" },
  { id: 8, name: "Remixes & memes" },
  { id: 3, name: "Music" },
  { id: 129, name: "Dance" },
  { id: 181, name: "Film & TV" },
  { id: 5, name: "Entertainment" },
  { id: 36, name: "Education" },
  { id: 188, name: "Tech & gadgets" },
  { id: 202, name: "News" },
  { id: 76, name: "Food" },
  { id: 138, name: "Short dramas" },
  { id: 176, name: "Automotive" },
  { id: 155, name: "Fashion & beauty" },
  { id: 235, name: "Sports" },
  { id: 75, name: "Animals" },
  { id: 21, name: "vlog" },
  { id: 162, name: "Art" },
  { id: 207, name: "Artificial intelligence" },
  { id: 208, name: "Home & property" },
  { id: 209, name: "Outdoor lifestyle" },
  { id: 164, name: "Fitness" },
  { id: 161, name: "Crafts" },
  { id: 165, name: "Travel" },
  { id: 158, name: "Rural life" },
  { id: 159, name: "Parenting" },
  { id: 160, name: "Healthy" },
  { id: 163, name: "Relationships" },
  { id: 22, name: "Hobbies" },
  { id: 23, name: "Life skills" }
]

// 投稿API
export const uploadApi = {
  // 账号管理
  createAccount: async (username: string, password: string, nickname?: string, cookieContent?: string): Promise<BilibiliAccount> => {
    return api.post('/upload/accounts', { username, password, nickname, cookie_content: cookieContent })
  },

  // 获取支持的登录方式
  getLoginMethods: async (): Promise<{methods: Array<{
    id: string,
    name: string,
    description: string,
    icon: string,
    recommended: boolean,
    risk_level: string
  }>}> => {
    return api.get('/upload/login-methods')
  },

  // 账号密码登录
  passwordLogin: async (username: string, password: string, nickname?: string): Promise<BilibiliAccount> => {
    return api.post('/upload/password-login', { username, password, nickname })
  },

  // Cookie导入登录
  cookieLogin: async (cookies: Record<string, string>, nickname?: string): Promise<BilibiliAccount> => {
    return api.post('/upload/cookie-login', { cookies, nickname })
  },

  // 第三方登录
  thirdPartyLogin: async (type: 'wechat' | 'qq', nickname?: string): Promise<{login_url: string, message: string}> => {
    return api.post('/upload/third-party-login', { type, nickname })
  },

  startQRLogin: async (nickname?: string): Promise<{session_id: string, status: string, message: string}> => {
    return api.post('/upload/qr-login', { nickname })
  },

  checkQRLoginStatus: async (sessionId: string): Promise<{session_id: string, status: string, message: string, qr_code?: string}> => {
    return api.get(`/upload/qr-login/${sessionId}`)
  },

  completeQRLogin: async (sessionId: string, nickname?: string): Promise<BilibiliAccount> => {
    return api.post(`/upload/qr-login/${sessionId}/complete`, { nickname })
  },

  getAccounts: async (): Promise<BilibiliAccount[]> => {
    return api.get('/upload/accounts')
  },

  deleteAccount: async (accountId: string): Promise<void> => {
    return api.delete(`/upload/accounts/${accountId}`)
  },

  checkAccountStatus: async (accountId: string): Promise<{is_valid: boolean, message: string}> => {
    return api.post(`/upload/accounts/${accountId}/check`)
  },

  // 投稿管理
  createUploadTask: async (projectId: string, uploadData: UploadRequest): Promise<{message: string, record_id: string, clip_count: number}> => {
    return api.post(`/upload/projects/${projectId}/upload`, uploadData)
  },

  retryUploadTask: async (recordId: string): Promise<{message: string}> => {
    return api.post(`/upload/records/${recordId}/retry`)
  },

  cancelUploadTask: async (recordId: string): Promise<{message: string}> => {
    return api.post(`/upload/records/${recordId}/cancel`)
  },

  getUploadRecords: async (projectId?: string): Promise<UploadRecord[]> => {
    const params = projectId ? { project_id: projectId } : {}
    return api.get('/upload/records', { params })
  },

  getUploadRecord: async (recordId: string): Promise<UploadStatus> => {
    return api.get(`/upload/records/${recordId}`)
  },

  getBilibiliAccounts: async (): Promise<BilibiliAccount[]> => {
    return api.get('/upload/accounts')
  },

  // 投稿任务管理
  retryUpload: async (recordId: string | number): Promise<{message: string}> => {
    return api.post(`/upload/records/${recordId}/retry`)
  },

  cancelUpload: async (recordId: string | number): Promise<{message: string}> => {
    return api.post(`/upload/records/${recordId}/cancel`)
  },

  deleteUpload: async (recordId: string | number): Promise<{message: string}> => {
    return api.delete(`/upload/records/${recordId}`)
  }
}

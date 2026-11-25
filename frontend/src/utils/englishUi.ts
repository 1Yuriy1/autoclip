// Translate backend-owned display labels only. Never apply these mappings to
// project names, video titles, transcripts, or other user content.
export const categoryLabels: Record<string, { name: string; description: string }> = {
  default: { name: 'General', description: 'General video content' },
  knowledge: { name: 'Education', description: 'Science, technology, history, and culture' },
  entertainment: { name: 'Entertainment', description: 'Gaming, music, movies, and shows' },
  business: { name: 'Business & finance', description: 'Business, entrepreneurship, and investing' },
  experience: { name: 'Personal experience', description: 'Life skills, food, travel, and practical advice' },
  opinion: { name: 'Commentary', description: 'Opinions, current events, and social topics' },
  speech: { name: 'Talks & interviews', description: 'Speeches, interviews, and conversations' },
  commentary: { name: 'Explainers', description: 'Explanations and analysis' },
}

export const whisperLabels: Record<string, { description: string; accuracy: string; speed: string }> = {
  tiny: { description: 'Fastest, with lower accuracy. Good for quick previews.', accuracy: 'Lower', speed: 'Fastest' },
  base: { description: 'Balanced speed and accuracy for everyday use.', accuracy: 'Moderate', speed: 'Fast' },
  small: { description: 'Better accuracy for important content.', accuracy: 'Good', speed: 'Moderate' },
  medium: { description: 'High accuracy for professional use.', accuracy: 'High', speed: 'Slower' },
  'large-v3': { description: 'Highest accuracy.', accuracy: 'Highest', speed: 'Slowest' },
}

const systemMessages: Record<string, string> = {
  '视频处理流水线': 'Video processing pipeline',
  '视频处理流水线完成': 'Video processing complete',
  '大纲提取': 'Outline extraction',
  '时间定位': 'Timing detection',
  '内容评分': 'Content scoring',
  '标题生成': 'Title generation',
  '主题聚类': 'Topic grouping',
  '视频切割': 'Video clipping',
  '正在准备安装…': 'Preparing installation…',
  '正在安装依赖…': 'Installing dependencies…',
  '正在安装中': 'Installation in progress',
  '正在安装中，无法卸载': 'Cannot uninstall while installation is in progress',
  '安装完成': 'Installation complete',
  '已安装': 'Installed',
  '已开始安装': 'Installation started',
  '已卸载': 'Uninstalled',
  '已卸载 Whisper 运行时': 'Whisper runtime uninstalled',
  '没有内容可处理': 'No content to process',
  '准备处理': 'Preparing to process',
  '处理完成': 'Processing complete',
  '处理失败': 'Processing failed',
  '等待处理': 'Waiting to process',
}

export function englishSystemText(value: string | null | undefined): string {
  if (!value) return ''
  if (systemMessages[value]) return systemMessages[value]
  return value
    .replace(/^安装失败（pip 退出码 (\d+)）$/, 'Installation failed (pip exit code $1)')
    .replace(/^安装异常:\s*/, 'Installation error: ')
}

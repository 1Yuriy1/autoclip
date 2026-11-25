"""
视频处理工具
"""
import subprocess
import json
import logging
import re
from typing import List, Dict, Optional
from pathlib import Path
from .ffmpeg_utils import get_ffmpeg_path, get_ffprobe_path

# 修复导入问题
try:
    from ..core.shared_config import CLIPS_DIR, COLLECTIONS_DIR
except ImportError:
    # 如果相对导入失败，尝试绝对导入
    import sys
    from pathlib import Path
    backend_path = Path(__file__).parent.parent
    if str(backend_path) not in sys.path:
        sys.path.insert(0, str(backend_path))
    from ..core.shared_config import CLIPS_DIR, COLLECTIONS_DIR

logger = logging.getLogger(__name__)

SHORTS_ASPECT_ALIASES = {'9:16', '9/16', 'vertical', 'portrait', 'shorts', 'short', 'youtube_shorts'}
SHORTS_LAYOUTS = {'crop', 'blur_pad'}
YOUTUBE_SHORTS_MAX_DURATION_SECONDS = 180.0

# 短视频/竖屏输出配置（读取失败时降级为 None，保持原有横屏行为）
try:
    from ..core.config import settings as _settings
except Exception:  # pragma: no cover
    _settings = None


def resolve_reframe(output_profile: Optional[Dict] = None) -> Optional[Dict]:
    """解析竖屏输出配置。

    项目级 ``output_profile`` 优先于进程环境配置，确保桌面后台线程和
    Celery worker 对同一个项目使用完全相同的导出参数。
    """
    if output_profile is not None:
        output_format = str(output_profile.get('format', '') or '').strip().lower()
        aspect = str(output_profile.get('aspect_ratio', '') or '').strip().lower()
        if not aspect:
            aspect = '9:16' if output_format in SHORTS_ASPECT_ALIASES else 'original'
        layout = str(output_profile.get('layout', 'blur_pad') or 'blur_pad').strip().lower()
        width = int(output_profile.get('width', 1080) or 1080)
        height = int(output_profile.get('height', 1920) or 1920)
        max_duration = float(
            output_profile.get('max_duration_seconds', YOUTUBE_SHORTS_MAX_DURATION_SECONDS)
            or YOUTUBE_SHORTS_MAX_DURATION_SECONDS
        )
    else:
        if _settings is None:
            return None
        aspect = str(getattr(_settings, 'clip_aspect_ratio', 'original') or 'original').strip().lower()
        layout = str(getattr(_settings, 'short_form_layout', 'crop') or 'crop').strip().lower()
        width = int(getattr(_settings, 'short_form_width', 1080) or 1080)
        height = int(getattr(_settings, 'short_form_height', 1920) or 1920)
        max_duration = YOUTUBE_SHORTS_MAX_DURATION_SECONDS

    if aspect not in SHORTS_ASPECT_ALIASES:
        return None

    layout_aliases = {'blur': 'blur_pad', 'pad': 'blur_pad'}
    layout = layout_aliases.get(layout, layout)
    if layout not in SHORTS_LAYOUTS:
        raise ValueError(f"不支持的竖屏排版: {layout}. 可选值: crop, blur_pad")
    if width <= 0 or height <= 0 or width % 2 or height % 2:
        raise ValueError("竖屏输出宽高必须是正偶数")
    if abs((width / height) - (9 / 16)) > 0.001:
        raise ValueError(f"YouTube Shorts 输出尺寸必须是 9:16，当前为 {width}x{height}")
    if not 1 <= max_duration <= YOUTUBE_SHORTS_MAX_DURATION_SECONDS:
        raise ValueError("Shorts 最大时长必须在 1 到 180 秒之间")

    return {
        'enabled': True,
        'layout': layout,
        'width': width,
        'height': height,
        'max_duration_seconds': max_duration,
    }


# Backward-compatible alias for the first vertical-output implementation.
_resolve_reframe = resolve_reframe


class VideoProcessor:
    """视频处理工具类"""
    
    def __init__(self, clips_dir: Optional[str] = None, collections_dir: Optional[str] = None):
        # 强制使用传入的项目特定路径，不使用全局路径作为后备
        if not clips_dir:
            raise ValueError("clips_dir 参数是必需的，不能使用全局路径")
        if not collections_dir:
            raise ValueError("collections_dir 参数是必需的，不能使用全局路径")
        
        self.clips_dir = Path(clips_dir)
        self.collections_dir = Path(collections_dir)
    
    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """
        清理文件名，移除或替换不合法的字符
        
        Args:
            filename: 原始文件名
            
        Returns:
            清理后的文件名
        """
        # 移除或替换不合法的字符
        # Windows和Unix系统都不允许的字符: < > : " | ? * \ /
        # 替换为下划线
        sanitized = re.sub(r'[<>:"|?*\\/]', '_', filename)
        
        # 移除前后空格和点
        sanitized = sanitized.strip(' .')
        
        # 限制长度，避免文件名过长
        if len(sanitized) > 100:
            sanitized = sanitized[:100]
        
        # 确保文件名不为空
        if not sanitized:
            sanitized = "untitled"
            
        return sanitized
    
    @staticmethod
    def convert_srt_time_to_ffmpeg_time(srt_time: str) -> str:
        """
        将SRT时间格式转换为FFmpeg时间格式
        
        Args:
            srt_time: SRT时间格式 (如 "00:00:06,140" 或 "00:00:06.140")
            
        Returns:
            FFmpeg时间格式 (如 "00:00:06.140")
        """
        # 将逗号替换为点
        return srt_time.replace(',', '.')
    
    @staticmethod
    def convert_seconds_to_ffmpeg_time(seconds: float) -> str:
        """
        将秒数转换为FFmpeg时间格式
        
        Args:
            seconds: 秒数
            
        Returns:
            FFmpeg时间格式 (如 "00:00:06.140")
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        milliseconds = int((seconds % 1) * 1000)
        
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{milliseconds:03d}"
    
    @staticmethod
    def convert_ffmpeg_time_to_seconds(time_str: str) -> float:
        """
        将FFmpeg时间格式转换为秒数
        
        Args:
            time_str: FFmpeg时间格式 (如 "00:00:06.140")
            
        Returns:
            秒数
        """
        try:
            # 处理毫秒部分
            if '.' in time_str:
                time_part, ms_part = time_str.split('.')
                milliseconds = int(ms_part)
            else:
                time_part = time_str
                milliseconds = 0
            
            # 解析时分秒
            h, m, s = map(int, time_part.split(':'))
            
            return h * 3600 + m * 60 + s + milliseconds / 1000
        except Exception as e:
            logger.error(f"时间格式转换失败: {time_str}, 错误: {e}")
            return 0.0
    
    @staticmethod
    def _build_reframe_ffmpeg_args(reframe: Dict) -> List[str]:
        """构建竖屏重构的 FFmpeg 参数（滤镜 + 重新编码）。

        - layout='crop'：缩放铺满后居中裁剪到目标尺寸（真·全屏竖屏，会裁掉左右）。
        - layout='blur_pad'：保留完整画面按宽度适配，上下用放大模糊的背景填充。
        """
        w = int(reframe.get('width', 1080))
        h = int(reframe.get('height', 1920))
        layout = str(reframe.get('layout', 'crop')).lower()

        # 重新编码参数：H.264 + AAC，保证各平台兼容
        encode = [
            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
            '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '160k',
            '-movflags', '+faststart',
        ]

        if layout in ('blur_pad', 'blur', 'pad'):
            filter_complex = (
                f"[0:v]split=2[bg][fg];"
                f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},gblur=sigma=25[bgb];"
                f"[fg]scale={w}:{h}:force_original_aspect_ratio=decrease[fgs];"
                f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1[v]"
            )
            return ['-filter_complex', filter_complex, '-map', '[v]', '-map', '0:a?'] + encode

        # 默认 crop：先放大到能覆盖目标尺寸，再居中裁剪
        vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"
        return ['-vf', vf] + encode

    @staticmethod
    def extract_clip(input_video: Path, output_path: Path,
                    start_time: str, end_time: str,
                    reframe: Optional[Dict] = None) -> bool:
        """
        从视频中提取指定时间段的片段

        Args:
            input_video: 输入视频路径
            output_path: 输出视频路径
            start_time: 开始时间 (格式: "00:01:25,140")
            end_time: 结束时间 (格式: "00:02:53,500")
            reframe: 竖屏重构配置（{'enabled','layout','width','height'}）。
                     为 None 或未启用时保持原有横屏(流复制)行为。

        Returns:
            是否成功
        """
        try:
            # 确保输出目录存在
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 转换时间格式：从SRT格式转换为FFmpeg格式
            ffmpeg_start_time = VideoProcessor.convert_srt_time_to_ffmpeg_time(start_time)
            ffmpeg_end_time = VideoProcessor.convert_srt_time_to_ffmpeg_time(end_time)
            
            # 计算持续时间
            start_seconds = VideoProcessor.convert_ffmpeg_time_to_seconds(ffmpeg_start_time)
            end_seconds = VideoProcessor.convert_ffmpeg_time_to_seconds(ffmpeg_end_time)
            duration = end_seconds - start_seconds
            
            # 构建优化的FFmpeg命令
            # 使用 -ss 在输入前进行精确定位，使用 -t 指定持续时间
            ffmpeg_bin = get_ffmpeg_path()
            cmd = [
                ffmpeg_bin,
                '-ss', ffmpeg_start_time,  # 在输入前定位，更精确
                '-i', str(input_video),
                '-t', str(duration),  # 使用持续时间而不是绝对结束时间
            ]

            if reframe and reframe.get('enabled'):
                # 竖屏短视频：应用重构滤镜并重新编码
                cmd += VideoProcessor._build_reframe_ffmpeg_args(reframe)
                logger.info(
                    f"竖屏输出已启用: layout={reframe.get('layout')} "
                    f"{reframe.get('width')}x{reframe.get('height')}"
                )
            else:
                # 保持源比例：直接流复制，速度最快、无质量损失
                cmd += ['-c:v', 'copy', '-c:a', 'copy']

            cmd += [
                '-avoid_negative_ts', 'make_zero',
                '-y',  # 覆盖输出文件
                str(output_path)
            ]
            
            # 执行命令
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
            
            if result.returncode == 0:
                logger.info(f"成功提取视频片段: {output_path} ({ffmpeg_start_time} -> {ffmpeg_end_time}, 时长: {duration:.2f}秒)")
                return True
            else:
                logger.error(f"提取视频片段失败: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"视频处理异常: {str(e)}")
            return False

    @staticmethod
    def reframe_video(input_video: Path, output_path: Path, reframe: Dict) -> bool:
        """将完整视频转换为统一的 9:16 输出，供导出和上传工具复用。"""
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            cmd = [get_ffmpeg_path(), '-i', str(input_video)]
            cmd += VideoProcessor._build_reframe_ffmpeg_args(reframe)
            cmd += ['-y', str(output_path)]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
            )
            if result.returncode == 0:
                return True
            logger.error(f"竖屏视频转换失败: {result.stderr}")
            return False
        except Exception as exc:
            logger.error(f"竖屏视频转换异常: {exc}")
            return False

    @staticmethod
    def validate_youtube_short(video_path: Path, max_duration_seconds: float = YOUTUBE_SHORTS_MAX_DURATION_SECONDS) -> List[str]:
        """返回 Shorts 兼容性错误；空列表表示文件可安全进入上传流程。"""
        info = VideoProcessor.get_video_info(video_path)
        if not info:
            return ['无法读取视频信息']

        errors = []
        duration = float(info.get('duration', 0) or 0)
        if duration <= 0:
            errors.append('视频时长无效')
        elif duration > max_duration_seconds + 0.05:
            errors.append(f'视频时长 {duration:.2f}s 超过 Shorts 上限 {max_duration_seconds:.0f}s')

        video_stream = next(
            (stream for stream in info.get('streams', []) if stream.get('codec_type') == 'video'),
            None,
        )
        if not video_stream:
            errors.append('缺少视频流')
            return errors

        width = int(video_stream.get('width', 0) or 0)
        height = int(video_stream.get('height', 0) or 0)
        if width <= 0 or height <= 0:
            errors.append('视频尺寸无效')
        elif abs((width / height) - (9 / 16)) > 0.01:
            errors.append(f'视频不是 9:16（当前 {width}x{height}）')

        if video_stream.get('codec_name') != 'h264':
            errors.append('视频编码不是 H.264')
        if video_stream.get('pix_fmt') != 'yuv420p':
            errors.append('像素格式不是 yuv420p')
        return errors
    
    @staticmethod
    def create_collection(clips_list: List[Path], output_path: Path) -> bool:
        """
        将多个视频片段拼接成合集
        
        Args:
            clips_list: 视频片段路径列表
            output_path: 输出合集路径
            
        Returns:
            是否成功
        """
        try:
            # 验证输入参数
            if not clips_list:
                logger.error("clips_list为空，无法创建合集")
                return False
            
            # 验证所有视频文件是否存在
            valid_clips = []
            for clip_path in clips_list:
                if not clip_path.exists():
                    logger.warning(f"视频文件不存在，跳过: {clip_path}")
                    continue
                valid_clips.append(clip_path)
            
            if not valid_clips:
                logger.error("没有有效的视频文件，无法创建合集")
                return False
            
            # 确保输出目录存在
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 创建concat文件
            concat_file = output_path.parent / "concat_list.txt"
            
            with open(concat_file, 'w', encoding='utf-8') as f:
                for clip_path in valid_clips:
                    # 使用绝对路径并转义单引号
                    abs_path = clip_path.absolute()
                    escaped_path = str(abs_path).replace("'", "'\"'\"'")
                    f.write(f"file '{escaped_path}'\n")
            
            # 验证concat文件内容
            if concat_file.stat().st_size == 0:
                logger.error("concat文件为空，无法创建合集")
                concat_file.unlink(missing_ok=True)
                return False
            
            # 构建FFmpeg命令 - 使用H.264编码确保兼容性
            ffmpeg_bin = get_ffmpeg_path()
            cmd = [
                ffmpeg_bin,
                '-f', 'concat',
                '-safe', '0',
                '-i', str(concat_file),
                '-c:v', 'libx264',  # 使用H.264视频编码
                '-preset', 'ultrafast',  # 使用最快的编码预设
                '-crf', '28',  # 稍微降低质量以加快编码速度
                '-c:a', 'aac',  # 使用AAC音频编码
                '-b:a', '128k',  # 音频比特率
                '-movflags', '+faststart',  # 优化网络播放
                '-y',
                str(output_path)
            ]
            
            logger.info(f"执行FFmpeg命令: {' '.join(cmd)}")
            
            # 执行命令
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
            
            # 清理临时文件
            concat_file.unlink(missing_ok=True)
            
            if result.returncode == 0:
                logger.info(f"成功创建合集: {output_path}")
                return True
            else:
                logger.error(f"创建合集失败: {result.stderr}")
                logger.error(f"FFmpeg stdout: {result.stdout}")
                return False
                
        except Exception as e:
            logger.error(f"视频拼接异常: {str(e)}")
            return False
    
    @staticmethod
    def extract_thumbnail(video_path: Path, output_path: Path, time_offset: int = 5) -> bool:
        """
        从视频中提取缩略图
        
        Args:
            video_path: 视频文件路径
            output_path: 输出缩略图路径
            time_offset: 提取时间点（秒）
            
        Returns:
            是否成功
        """
        try:
            # 确保输出目录存在
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 构建FFmpeg命令
            cmd = [
                'ffmpeg',
                '-i', str(video_path),
                '-ss', str(time_offset),
                '-vframes', '1',
                '-q:v', '2',  # 高质量
                '-y',  # 覆盖输出文件
                str(output_path)
            ]
            
            # 执行命令
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
            
            if result.returncode == 0 and output_path.exists():
                logger.info(f"成功提取缩略图: {output_path}")
                return True
            else:
                logger.error(f"提取缩略图失败: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"提取缩略图异常: {str(e)}")
            return False
    
    @staticmethod
    def get_video_info(video_path: Path) -> Dict:
        """
        获取视频信息
        
        Args:
            video_path: 视频文件路径
            
        Returns:
            视频信息字典
        """
        try:
            ffprobe_bin = get_ffprobe_path()
            cmd = [
                ffprobe_bin,
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-show_streams',
                str(video_path)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
            
            if result.returncode == 0:
                info = json.loads(result.stdout)
                return {
                    'duration': float(info['format']['duration']),
                    'size': int(info['format']['size']),
                    'bitrate': int(info['format']['bit_rate']),
                    'streams': info['streams']
                }
            else:
                logger.error(f"获取视频信息失败: {result.stderr}")
                return {}
                
        except Exception as e:
            logger.error(f"获取视频信息异常: {str(e)}")
            return {}
    
    def batch_extract_clips(self, input_video: Path, clips_data: List[Dict],
                            output_profile: Optional[Dict] = None) -> List[Path]:
        """
        批量提取视频片段
        
        Args:
            input_video: 输入视频路径
            clips_data: 片段数据列表，每个元素包含id、title、start_time、end_time
            
        Returns:
            成功提取的片段路径列表
        """
        successful_clips = []

        # 解析一次竖屏重构配置，应用到本批次所有切片
        reframe = resolve_reframe(output_profile)
        if reframe:
            logger.info(
                f"本批次将输出竖屏短视频: {reframe['width']}x{reframe['height']} "
                f"(layout={reframe['layout']})"
            )

        for clip_data in clips_data:
            clip_id = clip_data['id']
            title = clip_data.get('title', f"片段_{clip_id}")
            start_time = clip_data['start_time']
            end_time = clip_data['end_time']
            
            # 处理时间格式 - 如果是秒数，转换为SRT格式
            if isinstance(start_time, (int, float)):
                start_time = VideoProcessor.convert_seconds_to_ffmpeg_time(start_time)
            if isinstance(end_time, (int, float)):
                end_time = VideoProcessor.convert_seconds_to_ffmpeg_time(end_time)
            
            # 使用标题作为文件名，并清理不合法的字符
            # 在文件名中包含clip_id，便于后续合集拼接时查找
            safe_title = VideoProcessor.sanitize_filename(title)
            output_path = self.clips_dir / f"{clip_id}_{safe_title}.mp4"
            
            logger.info(f"提取切片 {clip_id}: {start_time} -> {end_time}, 输出: {output_path}")
            
            if VideoProcessor.extract_clip(input_video, output_path, start_time, end_time, reframe=reframe):
                if reframe:
                    from .shorts_captions import burn_captions
                    srt_path = input_video.parent / 'input.srt'
                    if not srt_path.exists():
                        srt_path = self.clips_dir.parent.parent / 'raw' / 'input.srt'
                    if srt_path.exists():
                        burn_captions(
                            output_path, srt_path,
                            VideoProcessor.convert_ffmpeg_time_to_seconds(start_time.replace(',', '.')),
                        )
                successful_clips.append(output_path)
                logger.info(f"切片 {clip_id} 提取成功")
            else:
                logger.error(f"切片 {clip_id} 提取失败")
        
        return successful_clips
    
    def create_collections_from_metadata(self, collections_data: List[Dict]) -> List[Dict]:
        """
        根据元数据创建合集
        
        Args:
            collections_data: 合集数据列表
            
        Returns:
            成功创建的合集信息列表，包含视频路径和缩略图路径
        """
        successful_collections = []
        
        for collection_data in collections_data:
            collection_id = collection_data['id']
            collection_title = collection_data.get('collection_title', f'合集_{collection_id}')
            clip_ids = collection_data['clip_ids']
            
            # 构建片段路径列表
            clips_list = []
            for clip_id in clip_ids:
                # 查找对应的切片文件
                # 新的文件名格式是: {clip_id}_{title}.mp4
                clip_path = self.clips_dir / f"{clip_id}_*.mp4"
                found_clips = list(self.clips_dir.glob(f"{clip_id}_*.mp4"))
                
                if found_clips:
                    found_clip = found_clips[0]  # 取第一个匹配的文件
                    clips_list.append(found_clip)
                    logger.info(f"找到合集 {collection_id} 的切片: {found_clip.name}")
                else:
                    logger.warning(f"未找到合集 {collection_id} 的切片 {clip_id}")
            
            if clips_list:
                # 使用collection_title作为文件名，并清理不合法的字符
                safe_title = VideoProcessor.sanitize_filename(collection_title)
                output_path = self.collections_dir / f"{safe_title}.mp4"
                
                if VideoProcessor.create_collection(clips_list, output_path):
                    # 生成合集缩略图
                    thumbnail_path = None
                    try:
                        thumbnail_filename = f"{collection_id}_{safe_title}_thumbnail.jpg"
                        thumbnail_path = self.collections_dir / thumbnail_filename
                        
                        # 从视频中提取缩略图（第2秒的帧）
                        thumbnail_success = VideoProcessor.extract_thumbnail(output_path, thumbnail_path, time_offset=2)
                        if thumbnail_success:
                            logger.info(f"合集 {collection_id} 缩略图生成成功: {thumbnail_path}")
                        else:
                            logger.warning(f"合集 {collection_id} 缩略图生成失败")
                            thumbnail_path = None
                    except Exception as e:
                        logger.error(f"生成合集 {collection_id} 缩略图时出错: {e}")
                        thumbnail_path = None
                    
                    # 返回包含视频路径和缩略图路径的信息
                    collection_info = {
                        'collection_id': collection_id,
                        'video_path': str(output_path),
                        'thumbnail_path': str(thumbnail_path) if thumbnail_path else None,
                        'title': collection_title
                    }
                    successful_collections.append(collection_info)
                    logger.info(f"成功创建合集 {collection_id}: {output_path}")
            else:
                logger.warning(f"合集 {collection_id} 没有找到任何有效的切片文件")
        
        return successful_collections

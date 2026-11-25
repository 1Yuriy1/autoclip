"""Project-level video output profiles shared by API and pipeline code."""

from typing import Any, Dict, Optional


OUTPUT_FORMATS = {'original', 'youtube_shorts'}
SHORTS_LAYOUTS = {'crop', 'blur_pad'}


def build_output_profile(output_format: str = 'youtube_shorts',
                         layout: str = 'blur_pad') -> Dict[str, Any]:
    output_format = str(output_format or 'youtube_shorts').strip().lower()
    layout = str(layout or 'blur_pad').strip().lower()
    if output_format not in OUTPUT_FORMATS:
        raise ValueError(f"不支持的输出格式: {output_format}")
    if layout not in SHORTS_LAYOUTS:
        raise ValueError(f"不支持的 Shorts 排版: {layout}")

    if output_format == 'original':
        return {
            'format': 'original',
            'aspect_ratio': 'original',
        }

    return {
        'format': 'youtube_shorts',
        'aspect_ratio': '9:16',
        'layout': layout,
        'width': 1080,
        'height': 1920,
        'max_duration_seconds': 180,
        'target_duration_seconds': 60,
    }


def get_output_profile(processing_config: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not processing_config:
        return None
    profile = processing_config.get('output_profile')
    return profile if isinstance(profile, dict) else None

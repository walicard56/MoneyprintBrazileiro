"""Final video composition, adapted from MoneyPrinterV2's YouTube.combine().

Takes per-scene images, a voiceover track, optional music and subtitles, and
writes a vertical MP4. MoviePy / ImageMagick are imported lazily.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class RenderConfig:
    width: int = 1080
    height: int = 1920
    fps: int = 30
    threads: int = 2
    font_path: str = ""
    subtitle_fontsize: int = 100
    subtitle_color: str = "#FFFF00"
    subtitle_stroke_color: str = "black"
    subtitle_stroke_width: int = 5
    music_volume: float = 0.1
    imagemagick_path: str = ""
    max_subtitle_chars: int = 10
    extra: dict = field(default_factory=dict)


@dataclass
class SceneClip:
    image_path: str
    duration: float


def render_video(
    scenes: list[SceneClip],
    voice_path: str,
    output_path: str,
    *,
    music_path: str | None = None,
    subtitle_path: str | None = None,
    config: RenderConfig | None = None,
) -> str:
    """Compose the final vertical video and return its path.

    Raises ImportError if MoviePy is unavailable, or ValueError if there are no
    usable image clips.
    """
    cfg = config or RenderConfig()
    if not scenes:
        raise ValueError("No scenes with images to render.")

    from moviepy.editor import (  # type: ignore
        AudioFileClip,
        CompositeAudioClip,
        CompositeVideoClip,
        ImageClip,
        TextClip,
        afx,
        concatenate_videoclips,
    )
    from moviepy.video.fx.all import crop  # type: ignore

    if cfg.imagemagick_path:
        from moviepy.config import change_settings  # type: ignore

        change_settings({"IMAGEMAGICK_BINARY": cfg.imagemagick_path})

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    voice_clip = AudioFileClip(voice_path)
    max_duration = voice_clip.duration
    w, h = cfg.width, cfg.height
    target_ratio = w / h

    clips = []
    tot_dur = 0.0
    valid = [s for s in scenes if s.image_path and os.path.exists(s.image_path)]
    if not valid:
        raise ValueError("None of the scene images exist on disk.")

    while tot_dur < max_duration:
        for scene in valid:
            clip = ImageClip(scene.image_path)
            clip.duration = max(0.5, scene.duration)
            clip = clip.set_fps(cfg.fps)
            if round(clip.w / clip.h, 4) < target_ratio:
                clip = crop(
                    clip,
                    width=clip.w,
                    height=round(clip.w / target_ratio),
                    x_center=clip.w / 2,
                    y_center=clip.h / 2,
                )
            else:
                clip = crop(
                    clip,
                    width=round(target_ratio * clip.h),
                    height=clip.h,
                    x_center=clip.w / 2,
                    y_center=clip.h / 2,
                )
            clip = clip.resize((w, h))
            clips.append(clip)
            tot_dur += clip.duration
            if tot_dur >= max_duration:
                break

    final_clip = concatenate_videoclips(clips).set_fps(cfg.fps)

    # Subtitles (optional).
    subtitles = None
    if subtitle_path and os.path.exists(subtitle_path) and cfg.font_path:
        try:
            from moviepy.video.tools.subtitles import SubtitlesClip  # type: ignore

            def generator(txt: str):
                return TextClip(
                    txt,
                    font=cfg.font_path,
                    fontsize=cfg.subtitle_fontsize,
                    color=cfg.subtitle_color,
                    stroke_color=cfg.subtitle_stroke_color,
                    stroke_width=cfg.subtitle_stroke_width,
                    size=(w, h),
                    method="caption",
                )

            subtitles = SubtitlesClip(subtitle_path, generator).set_pos(
                ("center", "center")
            )
        except Exception:  # noqa: BLE001 - render without subs on any failure
            subtitles = None

    # Audio mix: voice + optional music at reduced volume.
    audio_tracks = [voice_clip.set_fps(44100)]
    if music_path and os.path.exists(music_path):
        music = AudioFileClip(music_path).set_fps(44100).fx(afx.volumex, cfg.music_volume)
        audio_tracks.append(music)
    final_clip = final_clip.set_audio(CompositeAudioClip(audio_tracks))
    final_clip = final_clip.set_duration(voice_clip.duration)

    if subtitles is not None:
        final_clip = CompositeVideoClip([final_clip, subtitles])

    final_clip.write_videofile(output_path, threads=cfg.threads, fps=cfg.fps)
    return output_path

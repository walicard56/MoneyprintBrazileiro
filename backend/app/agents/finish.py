"""Finishing agents: editor (timeline), quality control, and render."""

from __future__ import annotations

import os

from app.core.config import settings
from app.core.enums import AgentType, LogLevel, Stage
from app.agents.base import BaseAgent
from app.engine.compose import RenderConfig, SceneClip, render_video


class EditorAgent(BaseAgent):
    """Builds a timeline the frontend editor can display/edit (spec req 10)."""

    agent_type = AgentType.EDITOR
    stage = Stage.EDIT

    def run(self) -> None:
        self.ctx.db.flush()
        timeline = []
        cursor = 0.0
        for scene in self.ctx.video.scenes:
            duration = max(0.5, float(scene.duration or 4))
            timeline.append(
                {
                    "scene_id": scene.id,
                    "index": scene.index,
                    "start": round(cursor, 3),
                    "duration": duration,
                    "image_path": scene.image_path,
                    "clip_path": scene.clip_path,
                    "narration": scene.narration,
                    "transition": scene.transition,
                    "subtitle_position": scene.subtitle_position,
                }
            )
            cursor += duration

        cfg = dict(self.ctx.video.config)
        cfg["timeline"] = timeline
        cfg["estimated_duration"] = round(cursor, 2)
        self.ctx.video.config = cfg
        self.log(f"Built timeline with {len(timeline)} clips (~{cursor:.1f}s).")


class QCAgent(BaseAgent):
    """Deterministic quality checks before render (spec req: QC Agent)."""

    agent_type = AgentType.QC
    stage = Stage.QC

    def run(self) -> None:
        self.ctx.db.flush()
        scenes = self.ctx.video.scenes
        issues: list[str] = []

        if not scenes:
            raise ValueError("QC failed: no scenes.")

        with_images = [s for s in scenes if s.image_path and os.path.exists(s.image_path)]
        if not with_images:
            raise ValueError("QC failed: no scene has a usable image.")

        for scene in scenes:
            if not scene.narration.strip():
                issues.append(f"Scene {scene.index}: empty narration.")
            if scene.duration <= 0:
                issues.append(f"Scene {scene.index}: non-positive duration.")
            if not (scene.image_path and os.path.exists(scene.image_path)):
                issues.append(f"Scene {scene.index}: missing image.")

        if not self.ctx.video.config.get("voice_path"):
            issues.append("No voiceover track was produced.")

        cfg = dict(self.ctx.video.config)
        cfg["qc_issues"] = issues
        cfg["qc_passed"] = len(issues) == 0
        self.ctx.video.config = cfg

        if issues:
            for issue in issues:
                self.log(issue, level=LogLevel.WARNING)
            self.log(f"QC completed with {len(issues)} non-blocking issue(s).")
        else:
            self.log("QC passed with no issues.")


class RenderAgent(BaseAgent):
    """Composes the final MP4 using the media engine (spec req: render)."""

    agent_type = AgentType.EDITOR  # reuses editor config; no LLM/prompt needed
    stage = Stage.RENDER

    def run(self) -> None:
        self.ctx.db.flush()
        video = self.ctx.video
        voice_path = video.config.get("voice_path")
        if not voice_path or not os.path.exists(voice_path):
            raise ValueError("Cannot render without a voiceover track.")

        scenes = [
            SceneClip(image_path=s.image_path, duration=max(0.5, float(s.duration or 4)))
            for s in video.scenes
            if s.image_path and os.path.exists(s.image_path)
        ]
        if not scenes:
            raise ValueError("Cannot render: no usable scene images.")

        output_path = os.path.join(settings.media_root, f"{video.id}.mp4")
        cfg = self._build_render_config(video.config)

        render_video(
            scenes,
            voice_path,
            output_path,
            music_path=video.config.get("music_path"),
            subtitle_path=video.config.get("subtitle_path"),
            config=cfg,
        )
        video.video_path = output_path
        self.log(f"Rendered final video: {output_path}")

    @staticmethod
    def _build_render_config(vconfig: dict) -> RenderConfig:
        preset = vconfig.get("preset", {})
        return RenderConfig(
            width=int(preset.get("width", vconfig.get("width", 1080))),
            height=int(preset.get("height", vconfig.get("height", 1920))),
            fps=int(preset.get("fps", vconfig.get("fps", 30))),
            threads=int(vconfig.get("threads", 2)),
            font_path=vconfig.get("font_path", ""),
            imagemagick_path=vconfig.get("imagemagick_path", ""),
            music_volume=float(vconfig.get("music_volume", 0.1)),
            subtitle_fontsize=int(vconfig.get("subtitle_fontsize", 100)),
            subtitle_color=vconfig.get("subtitle_color", "#FFFF00"),
        )

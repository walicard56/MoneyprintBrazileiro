"""Media agents: image, (optional) video, voice, music, and subtitles."""

from __future__ import annotations

import os
import re
import uuid

from app.core.config import settings
from app.core.enums import AgentType, Capability, Stage
from app.providers.base import ImageRequest, STTRequest, TTSRequest
from app.providers.router import NoProviderAvailable
from app.agents.base import BaseAgent
from app.engine.music import choose_random_song


def _media_path(ext: str) -> str:
    os.makedirs(settings.media_root, exist_ok=True)
    return os.path.join(settings.media_root, f"{uuid.uuid4()}.{ext}")


class ImageAgent(BaseAgent):
    agent_type = AgentType.IMAGE
    stage = Stage.IMAGES

    def run(self) -> None:
        self.ctx.db.flush()
        scenes = self.ctx.video.scenes
        if not scenes:
            raise ValueError("No scenes to generate images for.")
        aspect = self.ctx.video.config.get("aspect_ratio", "9:16")

        generated = 0
        for scene in scenes:
            prompt = scene.visual_prompt or scene.visual_description or scene.narration
            if not prompt:
                continue
            out = _media_path("png")

            def fn(provider, _p=prompt, _out=out):
                resp = provider.generate(
                    ImageRequest(prompt=_p, aspect_ratio=aspect, output_path=_out)
                )
                return resp, resp.usage

            try:
                result = self.ctx.router.run(
                    Capability.IMAGE,
                    fn,
                    project_id=self.ctx.project.id,
                    video_id=self.ctx.video.id,
                )
            except NoProviderAvailable as exc:
                raise ValueError(f"Image generation unavailable: {exc}") from exc
            scene.image_path = result.value.path
            generated += 1
        self.log(f"Generated {generated} scene image(s).")


class VideoAgent(BaseAgent):
    """Animates scenes when a VIDEO provider exists; otherwise skips (spec req 6)."""

    agent_type = AgentType.VIDEO
    stage = Stage.VIDEOS

    def run(self) -> None:
        specs = self.ctx.router.specs(Capability.VIDEO)
        if not specs:
            self.log("No video provider configured; using still images for all scenes.")
            return
        self.log("Video provider configured, but animation is not yet enabled; skipping.")


class VoiceAgent(BaseAgent):
    agent_type = AgentType.VOICE
    stage = Stage.VOICE

    def run(self) -> None:
        script = self.ctx.video.script
        text = script.content if script else ""
        if not text:
            text = " ".join(s.narration for s in self.ctx.video.scenes)
        # Clean for TTS (keep basic punctuation), ported from MPV2.
        text = re.sub(r"[^\w\s.?!,]", "", text).strip()
        if not text:
            raise ValueError("No narration text available for voiceover.")

        voice = self.ctx.video.config.get("voice") or self.config.params.get("voice", "")
        out = _media_path("wav")

        def fn(provider, _text=text, _voice=voice, _out=out):
            resp = provider.synthesize(
                TTSRequest(text=_text, voice=_voice, output_path=_out)
            )
            return resp, resp.usage

        try:
            result = self.ctx.router.run(
                Capability.TTS,
                fn,
                project_id=self.ctx.project.id,
                video_id=self.ctx.video.id,
            )
        except NoProviderAvailable as exc:
            raise ValueError(f"TTS unavailable: {exc}") from exc

        cfg = dict(self.ctx.video.config)
        cfg["voice_path"] = result.value.path
        self.ctx.video.config = cfg
        self.log("Synthesized voiceover.")


class MusicAgent(BaseAgent):
    agent_type = AgentType.MUSIC
    stage = Stage.MUSIC

    def run(self) -> None:
        if self.ctx.video.config.get("music_enabled") is False:
            self.log("Background music disabled for this video; skipping.")
            return
        songs_dir = self.ctx.video.config.get("songs_dir") or os.path.join(
            settings.media_root, "songs"
        )
        song = choose_random_song(songs_dir)
        if not song:
            self.log("No background music available; continuing without music.")
            return
        cfg = dict(self.ctx.video.config)
        cfg["music_path"] = song
        self.ctx.video.config = cfg
        self.log(f"Selected background music: {os.path.basename(song)}")


class SubtitleAgent(BaseAgent):
    agent_type = AgentType.SUBTITLE
    stage = Stage.SUBTITLES

    def run(self) -> None:
        if self.ctx.video.config.get("subtitles_enabled") is False:
            self.log("Subtitles disabled for this video; skipping.")
            return
        voice_path = self.ctx.video.config.get("voice_path")
        if not voice_path or not os.path.exists(voice_path):
            self.log("No voiceover audio; skipping subtitles.")
            return
        out = _media_path("srt")

        def fn(provider, _audio=voice_path, _out=out):
            resp = provider.transcribe(STTRequest(audio_path=_audio, output_path=_out))
            return resp, resp.usage

        try:
            result = self.ctx.router.run(
                Capability.STT,
                fn,
                project_id=self.ctx.project.id,
                video_id=self.ctx.video.id,
            )
        except NoProviderAvailable:
            self.log("No STT provider configured; continuing without subtitles.")
            return

        srt_path = result.value.srt_path
        self._equalize(srt_path)
        cfg = dict(self.ctx.video.config)
        cfg["subtitle_path"] = srt_path
        self.ctx.video.config = cfg
        self.log("Generated subtitles.")

    @staticmethod
    def _equalize(srt_path: str) -> None:
        try:
            import srt_equalizer

            srt_equalizer.equalize_srt_file(srt_path, srt_path, 10)
        except Exception:  # noqa: BLE001 - optional nicety
            pass

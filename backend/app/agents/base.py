"""Base agent: shared context, LLM helper, logging, and JSON parsing."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from sqlalchemy.orm import Session

from app.core.enums import AgentType, Capability, LogLevel, Stage
from app.db.models import Project, Video
from app.providers.base import LLMRequest, LLMResponse, Usage
from app.providers.router import ProviderRouter
from app.services import logs
from app.services.agent_config import ResolvedAgentConfig, resolve_agent_config
from app.services.style_guidance import compile_style_guidance

# Injected into every agent prompt via {locked_notice} when the script is
# user-provided and must not be reworded (entry_mode="script", Phase 6).
_SCRIPT_LOCKED_NOTICE = (
    "CRITICAL: the script above was written by the user and is LOCKED — you "
    "must NOT rewrite, paraphrase, or alter a single word of it. Only decide "
    "where to split it into scenes and give each one a brief visual hint "
    "from context; every scene's \"narration\" must be an exact, "
    "uninterrupted substring of the original text."
)


class AgentContext:
    """Everything an agent needs to do its job for one video."""

    def __init__(self, db: Session, video: Video) -> None:
        self.db = db
        self.video = video
        self.project: Project = video.project
        self.router = ProviderRouter(db)

    def base_fields(self) -> dict[str, Any]:
        """Common template placeholders drawn from project + video."""
        duration = self.video.config.get("duration") or self.project.default_duration
        platform = self.video.config.get("platform", "tiktok")
        # ~2.5 spoken words per second is a reasonable short-form estimate.
        word_count = max(20, int(duration * 2.5))
        cfg = self.video.config
        return {
            "niche": self.project.niche,
            # Per-video config overrides the project defaults where provided.
            "language": cfg.get("language") or self.project.language,
            "country": cfg.get("country") or self.project.country,
            "audience": cfg.get("audience") or self.project.audience,
            "style": cfg.get("style") or self.project.style or "cinematic",
            "tone": cfg.get("tone", ""),
            "platform": platform,
            "duration": duration,
            "word_count": word_count,
            "topic": self.video.topic or self.video.idea,
            "idea": self.video.idea,
            "structure": cfg.get("structure", "curiosity"),
            "style_guidance": compile_style_guidance(self.db, cfg.get("style_profile_id")),
            "locked_notice": _SCRIPT_LOCKED_NOTICE if cfg.get("script_locked") else "",
        }


class BaseAgent(ABC):
    agent_type: ClassVar[AgentType]
    stage: ClassVar[Stage]

    def __init__(self, ctx: AgentContext) -> None:
        self.ctx = ctx
        self.config: ResolvedAgentConfig = resolve_agent_config(
            ctx.db, self.agent_type, ctx.project.id
        )

    # --- helpers available to all agents ---

    def log(self, message: str, level: LogLevel = LogLevel.INFO) -> None:
        logs.log(
            self.ctx.db,
            message,
            level=level,
            agent=self.agent_type.value,
            stage=self.stage.value,
            project_id=self.ctx.project.id,
            video_id=self.ctx.video.id,
            commit=False,
        )

    def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        """Run an LLM completion using this agent's resolved config + fallback."""

        def fn(provider) -> tuple[LLMResponse, Usage]:
            resp: LLMResponse = provider.generate(
                LLMRequest(
                    prompt=prompt,
                    system=self.config.system_prompt or None,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                    json_mode=json_mode,
                )
            )
            return resp, resp.usage

        result = self.ctx.router.run(
            Capability.LLM,
            fn,
            project_id=self.ctx.project.id,
            video_id=self.ctx.video.id,
            provider_config_id=self.config.provider_config_id,
        )
        return result.value.text

    def render_prompt(self, **extra: Any) -> str:
        fields = self.ctx.base_fields()
        fields.update(extra)
        template = self.config.prompt_template
        try:
            return template.format(**_SafeDict(fields))
        except Exception:  # noqa: BLE001 - never fail on a stray brace
            return template

    @staticmethod
    def parse_json(text: str) -> Any:
        """Best-effort JSON extraction from an LLM response (ported from MPV2)."""
        cleaned = text.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
        # Fall back to the first {...} or [...] block.
        for pattern in (r"\[.*\]", r"\{.*\}"):
            match = re.search(pattern, cleaned, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    continue
        raise ValueError("Could not parse JSON from model response.")

    @abstractmethod
    def run(self) -> None:
        """Execute the stage, mutating DB state. Raise to signal failure."""


class _SafeDict(dict):
    """dict that leaves unknown ``{placeholders}`` untouched during format()."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"

"""Agents for reference learning (D6): per-video fiche, aggregated style
profile, and editorial-direction discovery.

``BaseAgent``/``AgentContext`` are not reused directly — they require a
``Video``, which doesn't exist yet when learning from a reference (D6).
``ReferenceAgentContext``/``BaseServiceAgent`` below are their lightweight,
Video-free counterparts, built from the same pieces
(``resolve_agent_config``, ``ProviderRouter.run(..., video_id=None)``,
``BaseAgent.parse_json``) so prompts stay editable from the same
Prompts/Agents screens as every other agent.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar, TypeVar

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from app.agents.base import BaseAgent
from app.core.enums import AgentType, Capability, LogLevel
from app.db.models import Project, ReferenceSource, ReferenceVideo
from app.providers.base import LLMRequest, LLMResponse, Usage
from app.providers.router import ProviderRouter
from app.schemas.reference import (
    EditorialDirectionItem,
    ReferenceVideoAnalysis,
    StyleProfileData,
)
from app.services import logs
from app.services.agent_config import ResolvedAgentConfig, resolve_agent_config

# The anti-copy rule is mandatory in every prompt that touches reference
# material (D6) — repeated here as a constant so it can't be edited away by
# accident from the Prompts screen without the author seeing why it's there.
ANTI_COPY_RULE = (
    "Describe the style abstractly. Do not reproduce exact phrases, "
    "distinctive proper names, catchphrases, or passages from the reference "
    "material. No verbatim quotes, ever."
)

T = TypeVar("T")


class ReferenceAgentContext:
    """Like ``AgentContext``, but scoped to a project/reference instead of a
    ``Video`` — reference analysis runs before, or entirely without, any
    ``Video`` existing."""

    def __init__(
        self, db: Session, project: Project | None, source: ReferenceSource | None = None
    ) -> None:
        self.db = db
        self.project = project
        # None for standalone discovery (directions/discover): a typed-in
        # niche with no specific learned reference behind it.
        self.source = source
        self.router = ProviderRouter(db)

    @property
    def project_id(self) -> str | None:
        return self.project.id if self.project else None

    def base_fields(self) -> dict[str, Any]:
        return {
            "niche": self.project.niche if self.project else "",
            "language": (self.project.language if self.project else "") or "English",
            # Always available to every prompt template, so the mandatory
            # anti-copy rule (D6) can't be dropped by forgetting to pass it
            # at a given call site — only by editing the token out of the
            # prompt itself, which is a visible, deliberate act.
            "anti_copy_rule": ANTI_COPY_RULE,
        }


class BaseServiceAgent:
    """Video-free counterpart to ``BaseAgent`` (D6)."""

    agent_type: ClassVar[AgentType]

    def __init__(self, ctx: ReferenceAgentContext) -> None:
        self.ctx = ctx
        self.config: ResolvedAgentConfig = resolve_agent_config(
            ctx.db, self.agent_type, ctx.project_id
        )

    def log(self, message: str, level: LogLevel = LogLevel.INFO) -> None:
        logs.log(
            self.ctx.db,
            message,
            level=level,
            agent=self.agent_type.value,
            stage="reference",
            project_id=self.ctx.project_id,
            commit=False,
        )

    def complete(self, prompt: str, *, json_mode: bool = False) -> str:
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
            project_id=self.ctx.project_id,
            video_id=None,
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

    def complete_json(self, prompt: str, adapter: TypeAdapter[T]) -> T:
        """Run the prompt in JSON mode and validate the result against
        ``adapter``, with exactly one retry (with a correction instruction)
        if the first reply doesn't parse/validate."""
        text = self.complete(prompt, json_mode=True)
        try:
            return adapter.validate_python(BaseAgent.parse_json(text))
        except (ValueError, ValidationError) as exc:
            retry_prompt = (
                f"{prompt}\n\nYour previous reply could not be parsed as the "
                f"required JSON shape ({exc}). Return ONLY the corrected JSON, "
                "nothing else — no markdown, no commentary."
            )
            text = self.complete(retry_prompt, json_mode=True)
            return adapter.validate_python(BaseAgent.parse_json(text))


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


class ReferenceAnalystAgent(BaseServiceAgent):
    """Produces one abstract fiche per reference video."""

    agent_type = AgentType.REFERENCE_ANALYST

    def analyze(self, video: ReferenceVideo, transcript: str | None) -> ReferenceVideoAnalysis:
        prompt = self.render_prompt(
            title=video.title,
            duration_s=video.duration_s,
            views=video.views,
            likes=video.likes,
            comments=video.comments,
            outlier_score=video.outlier_score if video.outlier_score is not None else "n/a",
            published_at=video.published_at.isoformat() if video.published_at else "unknown",
            transcript=transcript or "(not available)",
        )
        return self.complete_json(prompt, TypeAdapter(ReferenceVideoAnalysis))


class StyleProfilerAgent(BaseServiceAgent):
    """Aggregates per-video fiches + channel stats into a draft style profile."""

    agent_type = AgentType.STYLE_PROFILER

    def build_profile(
        self, videos: list[ReferenceVideo], *, had_transcript: bool
    ) -> StyleProfileData:
        fiches = [
            {"role": v.role.value, "views": v.views, "outlier_score": v.outlier_score, **v.analysis}
            for v in videos
            if v.analysis
        ]
        prompt = self.render_prompt(
            videos_analyzed=len(videos),
            had_transcript=had_transcript,
            fiches_json=json.dumps(fiches, ensure_ascii=False),
        )
        data = self.complete_json(prompt, TypeAdapter(StyleProfileData))
        data.meta.setdefault("versao_do_schema", 1)
        data.meta["videos_analisados"] = len(videos)
        data.meta["tinha_transcricao"] = had_transcript
        return data


class TrendAgent(BaseServiceAgent):
    """Generates original editorial directions from top-performing evidence
    (or from general niche knowledge, when discovering with no reference)."""

    agent_type = AgentType.TREND

    def discover(
        self, niche: str, opportunities: list[ReferenceVideo] | None = None
    ) -> list[EditorialDirectionItem]:
        evidence = [
            {
                "video_external_id": v.external_id,
                "title": v.title,
                "views": v.views,
                "multiplier": v.outlier_score,
                "url": f"https://www.youtube.com/watch?v={v.external_id}",
            }
            for v in (opportunities or [])
        ]
        prompt = self.render_prompt(
            niche=niche or self.ctx.base_fields()["niche"],
            opportunities_json=json.dumps(evidence, ensure_ascii=False),
        )
        return self.complete_json(prompt, TypeAdapter(list[EditorialDirectionItem]))


def style_profile_data_to_dict(data: StyleProfileData) -> dict[str, Any]:
    """``StyleProfile.profile`` is stored as plain JSON; this keeps the
    dump logic (and the ``StyleProfileItem`` defaults) in one place."""
    return data.model_dump(mode="json")

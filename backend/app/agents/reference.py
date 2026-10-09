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
import math
import re
from typing import Any, ClassVar, TypeVar

from pydantic import BaseModel, TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from app.agents.base import BaseAgent
from app.core.enums import AgentType, Capability, LogLevel
from app.db.models import Project, ReferenceSource, ReferenceVideo
from app.providers.base import LLMRequest, LLMResponse, Usage
from app.providers.router import ProviderRouter
from app.schemas.reference import (
    EditorialDirectionEvidence,
    EditorialDirectionItem,
    ReferenceVideoAnalysis,
    StyleProfileData,
    StyleProfileItem,
)
from app.services import logs
from app.services.agent_config import ResolvedAgentConfig, resolve_agent_config
from app.services.channel_facts import ChannelFacts

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


# Which StyleProfileData item each ChannelGrammar field can actually fill —
# only ritmo/música have a Laboratório-measured counterpart (D6/Etapa 3);
# legenda.estilo and imagens.* are descriptive, not something the lab's
# numbers alone can write.
_GRAMMAR_FIELD_MAP = {
    ("ritmo", "corte_mediano_s"): "scene_duration_median_s",
    ("ritmo", "palavras_por_minuto"): "avg_wpm",
    ("musica", "nivel_relativo_db"): "loudness_lufs",
}


def _apply_channel_grammar(data: StyleProfileData, grammar: dict[str, Any] | None) -> None:
    """Overwrites the ritmo/música items the Laboratório de vídeo can
    actually measure with the real, code-computed number — never trusts
    the LLM to transcribe these correctly (same reasoning as the accepted
    invariant below)."""
    if not grammar:
        return
    for (section_name, key), grammar_key in _GRAMMAR_FIELD_MAP.items():
        field = grammar.get(grammar_key)
        if not isinstance(field, dict) or field.get("value") is None:
            continue
        section = getattr(data, section_name, None)
        if not isinstance(section, dict):
            continue
        n = field.get("n", 0)
        section[key] = StyleProfileItem(
            value=round(field["value"], 1),
            why=f"medido em {n} vídeo{'s' if n != 1 else ''} no Laboratório de vídeo",
            confidence=field.get("confidence", "low"),
            accepted=True,
        )


def _enforce_accepted_invariant(data: StyleProfileData) -> None:
    """The LLM is asked to always write ``accepted: true`` (it has no way to
    judge usefulness) — the real accept/reject decision is made here, in
    code, so a field with no value or low confidence is never silently
    presented to the user as an already-accepted trait (Etapa 1, item 3)."""
    for section_name in ("roteiro", "titulos", "imagens", "ritmo", "legenda", "musica", "voz"):
        section = getattr(data, section_name, None)
        if not isinstance(section, dict):
            continue
        for item in section.values():
            if item.value is None or item.confidence == "low":
                item.accepted = False


class StyleProfilerAgent(BaseServiceAgent):
    """Aggregates per-video fiches + channel stats into a draft style profile."""

    agent_type = AgentType.STYLE_PROFILER

    def build_profile(
        self,
        videos: list[ReferenceVideo],
        *,
        had_transcript: bool,
        facts: ChannelFacts | None = None,
        thumbnail_traits: dict[str, Any] | None = None,
        channel_grammar: dict[str, Any] | None = None,
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
            facts_json=facts.model_dump_json() if facts else "{}",
            thumbnail_traits_json=json.dumps(thumbnail_traits or {}, ensure_ascii=False),
        )
        data = self.complete_json(prompt, TypeAdapter(StyleProfileData))
        _apply_channel_grammar(data, channel_grammar)
        _enforce_accepted_invariant(data)
        data.meta.setdefault("versao_do_schema", 1)
        data.meta["videos_analisados"] = len(videos)
        data.meta["tinha_transcricao"] = had_transcript
        return data


# --- TrendAgent: closed, code-built candidates + an anti-fabrication validator


class _TrendDraftItem(BaseModel):
    """What the LLM is allowed to write: a label for a candidate_id it was
    given, plus title/why/approach. It never writes `evidence` itself —
    that's always filled from the matching candidate, in code."""

    candidate_id: str | None = None
    title: str
    why: str = ""
    approach: str = ""


_FORBIDDEN_METRIC_WORDS = (
    "retention", "retenção", "retencao",
    "ctr", "click-through", "click through",
    "traffic", "tráfego", "trafego",
    "rpm",
)

# A number followed by a unit that reads as a performance claim ("2.5x",
# "3,2×", "40%", "10 vezes") — anything else (a year, a list position the
# user typed) isn't a metric claim and doesn't need grounding.
_NUMBER_CLAIM_RE = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:x\b|×|vezes\b|%|por\s*cento)", re.IGNORECASE
)


def _text_forbidden_metric(text: str) -> str | None:
    lowered = text.lower()
    for word in _FORBIDDEN_METRIC_WORDS:
        if word in lowered:
            return word
    return None


def _parse_number_claim_value(claim: str) -> float | None:
    match = re.match(r"[\d.,]+", claim)
    if not match:
        return None
    raw = match.group(0)
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def _is_number_claim_grounded(value: float, candidate: dict[str, Any] | None) -> bool:
    if candidate is None:
        return False
    multiplier = candidate.get("multiplier")
    return multiplier is not None and math.isclose(value, multiplier, rel_tol=0.05, abs_tol=0.05)


def _validate_direction_text(item: _TrendDraftItem, candidate: dict[str, Any] | None) -> str | None:
    """Returns a short violation reason, or ``None`` if the text is clean."""
    full_text = f"{item.title} {item.why} {item.approach}"
    forbidden = _text_forbidden_metric(full_text)
    if forbidden:
        return f"mentions '{forbidden}', a metric this system never collects"
    for match in _NUMBER_CLAIM_RE.finditer(full_text):
        value = _parse_number_claim_value(match.group(0))
        if value is not None and not _is_number_claim_grounded(value, candidate):
            return f"claims '{match.group(0).strip()}' with no matching evidence"
    return None


def _build_candidates(
    opportunities: list[ReferenceVideo] | None, facts: ChannelFacts | None
) -> list[dict[str, Any]]:
    """Closed list of real, code-computed opportunities the LLM may write
    about — series and topic clusters (richer, channel-level groupings) take
    priority; any leftover individual top video not already covered by one
    of those fills in the rest."""
    candidates: list[dict[str, Any]] = []
    covered_ids: set[str] = set()

    if facts is not None:
        for s in facts.series[:3]:
            candidates.append(
                {
                    "candidate_id": f"series:{s.label}",
                    "label": s.label,
                    "kind": "series",
                    "video_count": s.video_count,
                    "views": s.best_video_views,
                    "multiplier": s.best_multiplier,
                    "example_external_id": s.best_video_external_id,
                }
            )
            covered_ids.update(s.video_external_ids)
        for c in facts.clusters[:3]:
            candidates.append(
                {
                    "candidate_id": f"cluster:{c.label}",
                    "label": c.label,
                    "kind": "cluster",
                    "video_count": c.video_count,
                    "views": c.best_video_views,
                    "multiplier": c.best_multiplier,
                    "example_external_id": c.best_video_external_id,
                }
            )
            covered_ids.update(c.top_video_external_ids)

    for v in opportunities or []:
        if v.external_id in covered_ids:
            continue
        candidates.append(
            {
                "candidate_id": f"video:{v.external_id}",
                "label": v.title,
                "kind": "video",
                "video_count": 1,
                "views": v.views,
                "multiplier": v.outlier_score,
                "example_external_id": v.external_id,
            }
        )

    candidates.sort(key=lambda c: (c.get("multiplier") or 0), reverse=True)
    return candidates[:8]


def _resolve_candidate(
    item: _TrendDraftItem, candidates: list[dict[str, Any]], candidates_by_id: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    if item.candidate_id and item.candidate_id in candidates_by_id:
        return candidates_by_id[item.candidate_id]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _evidence_from_candidate(candidate: dict[str, Any] | None) -> EditorialDirectionEvidence:
    if not candidate:
        return EditorialDirectionEvidence()
    ext_id = candidate.get("example_external_id")
    return EditorialDirectionEvidence(
        video_external_id=ext_id,
        views=candidate.get("views"),
        multiplier=candidate.get("multiplier"),
        url=f"https://www.youtube.com/watch?v={ext_id}" if ext_id else None,
    )


def _fallback_direction_text(candidate: dict[str, Any] | None) -> tuple[str, str, str]:
    """A safe, code-generated text used only when the LLM couldn't produce a
    grounded rewrite after one retry — guarantees the final result never
    carries an invented number or an uncollected metric."""
    if candidate is None:
        return (
            "Uma ideia original para este nicho",
            "Ideia geral, sem dado de desempenho.",
            "Explore um ângulo próprio — não é uma reescrita de nenhum vídeo específico.",
        )
    label = candidate.get("label") or "este assunto"
    multiplier = candidate.get("multiplier")
    views = candidate.get("views")
    if multiplier is not None:
        why = f"Múltiplo real de {multiplier:.1f}x sobre a mediana do canal, com base em dados coletados."
    elif views is not None:
        why = f"{views} visualizações reais registradas para vídeos deste assunto."
    else:
        why = "Ideia geral, sem dado de desempenho."
    return (
        f"Um novo ângulo sobre: {label}",
        why,
        "Aborde com um ângulo original — não é uma reescrita do vídeo de referência.",
    )


class TrendAgent(BaseServiceAgent):
    """Generates original editorial directions from a closed, code-built
    list of real candidates (series/clusters/outlier videos) — or from
    general niche knowledge, with no numbers at all, when there's no
    evidence to ground one. A validator strips any invented number or
    uncollected metric (retention/CTR/traffic/RPM) the LLM adds anyway,
    regenerating once before falling back to safe, code-written text."""

    agent_type = AgentType.TREND

    def discover(
        self,
        niche: str,
        opportunities: list[ReferenceVideo] | None = None,
        *,
        facts: ChannelFacts | None = None,
    ) -> list[EditorialDirectionItem]:
        candidates = _build_candidates(opportunities, facts)
        candidates_by_id = {c["candidate_id"]: c for c in candidates}
        candidates_payload = [
            {k: v for k, v in c.items() if k != "example_external_id"} for c in candidates
        ]

        prompt = self.render_prompt(
            niche=niche or self.ctx.base_fields()["niche"],
            candidates_json=json.dumps(candidates_payload, ensure_ascii=False),
        )
        draft = self.complete_json(prompt, TypeAdapter(list[_TrendDraftItem]))
        resolved = [(item, _resolve_candidate(item, candidates, candidates_by_id)) for item in draft]
        bad = {i for i, (item, cand) in enumerate(resolved) if _validate_direction_text(item, cand)}

        if bad:
            reasons = "; ".join(
                f"item {i + 1}: {_validate_direction_text(*resolved[i])}" for i in sorted(bad)
            )
            retry_prompt = (
                f"{prompt}\n\nSome of your items broke the rules — {reasons}. Rewrite EVERY "
                "item. Use a number ONLY if it appears in the candidate list above, rounded "
                "the same way. Never mention retention, CTR, traffic, or RPM — this system "
                "never measures them. If a candidate has no numbers, write a general idea "
                "with NO numbers at all."
            )
            try:
                draft = self.complete_json(retry_prompt, TypeAdapter(list[_TrendDraftItem]))
                resolved = [
                    (item, _resolve_candidate(item, candidates, candidates_by_id)) for item in draft
                ]
                bad = {
                    i for i, (item, cand) in enumerate(resolved) if _validate_direction_text(item, cand)
                }
            except Exception:  # noqa: BLE001 - keep the first pass; still-bad items get sanitized below
                pass

        results: list[EditorialDirectionItem] = []
        for i, (item, cand) in enumerate(resolved):
            if i in bad:
                reason = _validate_direction_text(item, cand)
                self.log(
                    f"Direction for candidate {cand.get('candidate_id') if cand else 'n/a'} "
                    f"still broke the rules after one retry ({reason}); replaced with a safe, "
                    "code-written fallback.",
                    level=LogLevel.WARNING,
                )
                title, why, approach = _fallback_direction_text(cand)
            else:
                title, why, approach = item.title, item.why, item.approach
            results.append(
                EditorialDirectionItem(
                    title=title, why=why, approach=approach, evidence=_evidence_from_candidate(cand)
                )
            )
        return results


def style_profile_data_to_dict(data: StyleProfileData) -> dict[str, Any]:
    """``StyleProfile.profile`` is stored as plain JSON; this keeps the
    dump logic (and the ``StyleProfileItem`` defaults) in one place."""
    return data.model_dump(mode="json")

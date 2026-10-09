"""Resolution of per-agent configuration and prompts (spec reqs 20/21).

Each agent reads its configuration (provider pin, model, temperature, system
prompt) and its active prompt template. Project-scoped rows win over global
defaults, so a project can override any agent without touching code.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import AgentType
from app.db.models import AgentConfig, PromptTemplate


@dataclass
class ResolvedAgentConfig:
    agent_type: AgentType
    provider_config_id: str | None
    model: str
    temperature: float
    max_tokens: int
    system_prompt: str
    params: dict
    prompt_template: str


def _resolve_agent_row(
    db: Session, agent_type: AgentType, project_id: str | None
) -> AgentConfig | None:
    stmt = select(AgentConfig).where(
        AgentConfig.agent_type == agent_type, AgentConfig.enabled.is_(True)
    )
    rows = list(db.execute(stmt).scalars())
    project_row = next((r for r in rows if r.project_id == project_id), None)
    if project_row is not None:
        return project_row
    return next((r for r in rows if r.project_id is None), None)


def _resolve_prompt(
    db: Session, agent_type: AgentType, project_id: str | None
) -> str:
    stmt = select(PromptTemplate).where(
        PromptTemplate.agent_type == agent_type,
        PromptTemplate.is_active.is_(True),
    )
    rows = list(db.execute(stmt).scalars())
    project_row = next((r for r in rows if r.project_id == project_id), None)
    if project_row is not None:
        return project_row.content
    default_row = next(
        (r for r in rows if r.project_id is None and r.is_default), None
    )
    if default_row is not None:
        return default_row.content
    global_row = next((r for r in rows if r.project_id is None), None)
    return global_row.content if global_row else ""


def resolve_agent_config(
    db: Session, agent_type: AgentType, project_id: str | None
) -> ResolvedAgentConfig:
    """Build the effective config for an agent, merging DB rows with defaults."""
    from app.agents.defaults import DEFAULT_AGENT_SETTINGS, DEFAULT_PROMPTS

    defaults = DEFAULT_AGENT_SETTINGS.get(agent_type, {})
    row = _resolve_agent_row(db, agent_type, project_id)
    prompt = _resolve_prompt(db, agent_type, project_id)

    return ResolvedAgentConfig(
        agent_type=agent_type,
        provider_config_id=row.provider_config_id if row else None,
        model=(row.model if row and row.model else defaults.get("model", "")),
        temperature=(row.temperature if row else defaults.get("temperature", 0.8)),
        max_tokens=(row.max_tokens if row else defaults.get("max_tokens", 2000)),
        system_prompt=(
            row.system_prompt
            if row and row.system_prompt
            else defaults.get("system_prompt", "")
        ),
        params=(row.params if row and row.params else {}),
        prompt_template=prompt or DEFAULT_PROMPTS.get(agent_type, ""),
    )

"""Seed default prompt templates and agent configs (spec reqs 20/21).

Idempotent: safe to run multiple times. Nothing here overwrites user edits.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.defaults import DEFAULT_AGENT_SETTINGS, DEFAULT_PROMPTS
from app.db.models import AgentConfig, PromptTemplate


def seed_defaults(db: Session) -> dict[str, int]:
    """Insert global default prompts/agent configs that don't exist yet."""
    prompts_created = 0
    for agent_type, content in DEFAULT_PROMPTS.items():
        exists = db.execute(
            select(PromptTemplate).where(
                PromptTemplate.agent_type == agent_type,
                PromptTemplate.project_id.is_(None),
                PromptTemplate.is_default.is_(True),
            )
        ).scalar_one_or_none()
        if exists is None:
            db.add(
                PromptTemplate(
                    name=f"Default {agent_type.value}",
                    agent_type=agent_type,
                    content=content,
                    is_active=True,
                    is_default=True,
                )
            )
            prompts_created += 1

    agents_created = 0
    for agent_type, settings_dict in DEFAULT_AGENT_SETTINGS.items():
        exists = db.execute(
            select(AgentConfig).where(
                AgentConfig.agent_type == agent_type,
                AgentConfig.project_id.is_(None),
            )
        ).scalar_one_or_none()
        if exists is None:
            db.add(
                AgentConfig(
                    project_id=None,
                    agent_type=agent_type,
                    temperature=settings_dict.get("temperature", 0.8),
                    max_tokens=settings_dict.get("max_tokens", 2000),
                    system_prompt=settings_dict.get("system_prompt", ""),
                )
            )
            agents_created += 1

    db.commit()
    return {"prompts_created": prompts_created, "agent_configs_created": agents_created}

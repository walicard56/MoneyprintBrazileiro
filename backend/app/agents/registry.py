"""Maps workflow stages to the agent that executes them."""

from __future__ import annotations

from app.core.enums import Stage
from app.agents.base import AgentContext, BaseAgent
from app.agents.content import ResearchAgent, ScriptAgent, ScriptReviewerAgent
from app.agents.finish import EditorAgent, QCAgent, RenderAgent
from app.agents.media import (
    ImageAgent,
    MusicAgent,
    SubtitleAgent,
    VideoAgent,
    VoiceAgent,
)
from app.agents.visual import (
    CharacterDesignerAgent,
    SceneDirectorAgent,
    StoryboardAgent,
)

# Ordered subset of STAGE_ORDER that the generation pipeline runs.
# IDEA is the seed (no agent); PUBLISH is a separate, explicit action.
STAGE_AGENTS: dict[Stage, type[BaseAgent]] = {
    Stage.RESEARCH: ResearchAgent,
    Stage.SCRIPT: ScriptAgent,
    Stage.REVIEW: ScriptReviewerAgent,
    Stage.STORYBOARD: StoryboardAgent,
    Stage.CHARACTERS: CharacterDesignerAgent,
    Stage.SCENES: SceneDirectorAgent,
    Stage.IMAGES: ImageAgent,
    Stage.VIDEOS: VideoAgent,
    Stage.VOICE: VoiceAgent,
    Stage.MUSIC: MusicAgent,
    Stage.SUBTITLES: SubtitleAgent,
    Stage.EDIT: EditorAgent,
    Stage.QC: QCAgent,
    Stage.RENDER: RenderAgent,
}

PIPELINE_STAGES: list[Stage] = list(STAGE_AGENTS.keys())


def get_agent(stage: Stage, ctx: AgentContext) -> BaseAgent:
    agent_cls = STAGE_AGENTS[stage]
    return agent_cls(ctx)

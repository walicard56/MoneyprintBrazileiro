"""Default agent settings and prompt templates.

These seed the database (see ``app.services.seeds``) and act as code-level
fallbacks when no DB row exists. All prompts are editable from the dashboard
(spec req 21); nothing here is hardcoded into the agents themselves.

Prompt templates use ``{placeholder}`` fields filled at runtime from the video,
project, script, and scene context.
"""

from __future__ import annotations

from app.core.enums import AgentType

DEFAULT_AGENT_SETTINGS: dict[AgentType, dict] = {
    AgentType.RESEARCH: {"temperature": 0.5, "max_tokens": 1200},
    AgentType.SCRIPT: {"temperature": 0.9, "max_tokens": 1500},
    AgentType.SCRIPT_REVIEWER: {"temperature": 0.4, "max_tokens": 1500},
    AgentType.STORYBOARD: {"temperature": 0.7, "max_tokens": 2500},
    AgentType.SCENE_DIRECTOR: {"temperature": 0.7, "max_tokens": 3000},
    AgentType.CHARACTER_DESIGNER: {"temperature": 0.8, "max_tokens": 2000},
    AgentType.QC: {"temperature": 0.2, "max_tokens": 1200},
}

_SCRIPT_PROMPT = """You are writing the narration script for a short vertical video.

Niche: {niche}
Topic: {topic}
Language: {language}
Target audience: {audience}
Platform: {platform}
Target duration: {duration} seconds
Tone/style: {style}
Narrative structure: {structure}

Rules:
- Open with a strong hook in the first 2 seconds that creates curiosity.
- Keep high retention: short, punchy sentences, natural spoken rhythm.
- Build toward a payoff; end with a clear call to action.
- Write ONLY the spoken narration — no scene directions, no markdown, no labels
  like "Narrator:". Do not mention this prompt.
- Aim for roughly {word_count} words so it fits {duration} seconds when spoken.
- Write in {language}.

Return only the narration text."""

_SCRIPT_REVIEWER_PROMPT = """You are a ruthless short-form video editor. Improve the script below.

Evaluate: hook strength, retention, pacing, curiosity, storytelling, and CTA.
Fix weaknesses. Keep it in {language}, keep roughly {word_count} words, keep the
spoken-only format (no directions/labels/markdown).

Return ONLY the improved narration text.

SCRIPT:
{script}"""

_STORYBOARD_PROMPT = """Break the narration into a sequence of short video scenes.

Topic: {topic}
Style: {style}
Target total duration: {duration} seconds.

For each scene provide: the exact narration substring for that scene, an
approximate duration in seconds, a one-line visual description, and any
characters that appear (by a short slug like "character_01" — reuse the same
slug for the same person across scenes).

Return ONLY a JSON array, each item:
{{"narration": "...", "duration": 4, "visual_description": "...", "characters": ["character_01"]}}

NARRATION:
{script}"""

_SCENE_DIRECTOR_PROMPT = """You are a cinematographer. Enrich this scene with concrete
visual direction for AI image/video generation.

Overall style: {style}
Scene narration: {narration}
Visual description: {visual_description}
Characters in scene: {characters}

Decide: camera shot (close_up | medium_shot | wide_shot | extreme_close_up | pov |
over_the_shoulder | aerial), camera movement (static | zoom_in | zoom_out | pan_left |
pan_right | tilt_up | tilt_down | tracking | dolly_in | dolly_out | orbit | handheld),
lighting, location, action, and a transition to the next scene.

Then write a richly detailed English image-generation prompt ("visual_prompt")
and a motion prompt ("video_prompt"). Keep character descriptions consistent
with the provided character details.

Return ONLY a JSON object:
{{"camera": {{"shot": "...", "movement": "..."}}, "lighting": "...", "location": "...",
"action": "...", "transition": "...", "visual_prompt": "...", "video_prompt": "..."}}"""

_CHARACTER_PROMPT = """Design the recurring characters for this video so they look
consistent across every scene.

Topic: {topic}
Style: {style}
Characters referenced in the storyboard: {character_slugs}

For each character slug, invent a coherent, specific identity. Return ONLY a JSON
array, each item:
{{"slug": "character_01", "name": "...", "age": "28", "gender": "...",
"appearance": "...", "clothing": "...", "hair": "...", "personality": "...",
"visual_style": "...",
"prompt_fragment": "a reusable, highly specific English description to inject into
every image prompt so the character always looks the same"}}"""

_QC_PROMPT = """You are a quality-control reviewer for a finished short video plan.

Review the scenes below for: missing narration, empty visual prompts, scenes
with zero duration, character inconsistency, and total-duration problems versus
the target of {duration} seconds.

Return ONLY a JSON object:
{{"passed": true/false, "issues": ["..."], "retry_stage": "scenes" | "script" | null}}

SCENES:
{scenes_summary}"""

_RESEARCH_PROMPT = """Research the topic and return concise, accurate talking points
a short video could use.

Topic: {topic}
Niche: {niche}
Language: {language}

Return 5-8 short factual bullet points in {language}, one per line, no numbering."""

DEFAULT_PROMPTS: dict[AgentType, str] = {
    AgentType.RESEARCH: _RESEARCH_PROMPT,
    AgentType.SCRIPT: _SCRIPT_PROMPT,
    AgentType.SCRIPT_REVIEWER: _SCRIPT_REVIEWER_PROMPT,
    AgentType.STORYBOARD: _STORYBOARD_PROMPT,
    AgentType.SCENE_DIRECTOR: _SCENE_DIRECTOR_PROMPT,
    AgentType.CHARACTER_DESIGNER: _CHARACTER_PROMPT,
    AgentType.QC: _QC_PROMPT,
}

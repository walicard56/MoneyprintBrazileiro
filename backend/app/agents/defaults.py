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
    AgentType.REFERENCE_ANALYST: {"temperature": 0.3, "max_tokens": 1200},
    AgentType.STYLE_PROFILER: {"temperature": 0.4, "max_tokens": 2500},
    AgentType.TREND: {"temperature": 0.8, "max_tokens": 1500},
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
{style_guidance}

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
{style_guidance}

Return ONLY the improved narration text.

SCRIPT:
{script}"""

_STORYBOARD_PROMPT = """Break the narration into a sequence of short video scenes.

Topic: {topic}
Style: {style}
Target total duration: {duration} seconds.
{style_guidance}
{locked_notice}

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

_REFERENCE_ANALYST_PROMPT = """You are analyzing one reference video to learn its abstract
style for a different channel — never to copy or quote it.

CRITICAL RULE: {anti_copy_rule}

Video title: {title}
Duration: {duration_s} seconds
Views: {views} (likes: {likes}, comments: {comments})
Outlier score vs. this channel's median views: {outlier_score}
Published: {published_at}
Transcript (may say "(not available)"): {transcript}

Analyze the SHAPE of this video, not its content: how the narration is
structured, what kind of hook opens it, where it pivots, its language
register, and its pacing. If no transcript was provided, infer only what the
metadata and duration can reasonably support, and reflect that honestly in
"confidence" and "tinha_transcricao".

Return ONLY a JSON object, with every text value written in {language}:
{{"estrutura": "...", "gancho": "...", "viradas": ["...", "..."],
"linguagem": "...", "ritmo": "...", "confidence": "low"|"medium"|"high",
"tinha_transcricao": true|false}}"""

_STYLE_PROFILER_PROMPT = """You aggregate several per-video analyses into one
channel-level style profile — an abstract pattern, never a copy of any one video.

CRITICAL RULE: {anti_copy_rule}

Channel niche: {niche}
Target language for every text value below: {language}
Number of videos analyzed: {videos_analyzed}
Had at least one transcript available: {had_transcript}

Per-video fiches as JSON, each tagged with its role (top = big outlier / what
blew up, bottom = underperformed, representative = typical for the channel):
{fiches_json}

Code-computed channel facts as JSON — series (installments of the same
format, e.g. "Vol.2"/"Parte 3" or a shared title prefix), topic clusters,
title patterns, upload cadence, and top-vs-bottom differences. These are the
ONLY numbers you may use for numeric claims anywhere in your answer — do not
estimate, round differently, or invent any number that isn't in here. If a
series or cluster is present, prefer naming it specifically (e.g. a real
recurring series title) over a generic placeholder like "[Local/Evento]":
{facts_json}

Where you can, contrast what the "top" videos do differently from the
"bottom" ones. For "nao_replicavel", pick and translate into {language} only
the limitations below that genuinely seem to apply here — don't invent
others: on-camera presenter, custom/hand-drawn animation, animated maps,
animated on-screen text effects, cross-dissolve transitions between clips.

Return ONLY a JSON object matching this exact shape. Every leaf item has
"value", "why" (short, with a number when you have one), "confidence"
("low"|"medium"|"high"), and "accepted" (always true):
{{
  "roteiro": {{"narrador": {{}}, "tom": {{}}, "como_o_video_avanca": {{}},
    "como_o_video_termina": {{}}, "linguagem": {{}}, "gancho_inicial": {{}},
    "pergunta_que_prende": {{}}}},
  "titulos": {{"padroes": {{"value": ["..."], "why": "...", "confidence": "...", "accepted": true}}}},
  "imagens": {{"tipo": {{}}, "percentual_video": {{}}, "fontes_sugeridas": {{}}}},
  "ritmo": {{"corte_mediano_s": {{}}, "palavras_por_minuto": {{}}}},
  "legenda": {{"estilo": {{}}, "cor": {{}}, "destaque": {{}}, "caixa_alta": {{}}}},
  "musica": {{"genero": {{}}, "nivel_relativo_db": {{}}}},
  "voz": {{"genero": {{}}, "timbre": {{}}, "velocidade": {{}}, "idioma": {{}},
    "sugestao_de_voz": {{}}}},
  "nao_replicavel": ["..."],
  "meta": {{"versao_do_schema": 1, "videos_analisados": {videos_analyzed},
    "tinha_transcricao": {had_transcript}}}
}}
Each "{{}}" above is itself a full item object (value/why/confidence/accepted).
Fields that depend on media you don't have (corte_mediano_s, nivel_relativo_db)
must have "value": null, "confidence": "low", and
"why": "precisa do arquivo de midia"."""

_TREND_PROMPT = """Generate original editorial directions — new subjects and
angles, never rewrites — for videos in this niche.

CRITICAL RULE: {anti_copy_rule}

Niche: {niche}
Language for every text value below: {language}

Closed list of real, code-computed candidates (may be empty — if so, write a
general idea for the niche instead, with NO numbers anywhere in your answer):
{candidates_json}

Write ONE direction PER candidate, in the same order, each referencing its
"candidate_id" exactly as given. If the list is empty, return exactly one
general-idea direction with "candidate_id": null.

Rules for numbers: use a number ONLY if it is the candidate's own "multiplier"
or "views" value (you may round it, e.g. 10.1 -> "10x"). Never invent a
number. Never mention retention, CTR, click-through rate, traffic, or RPM —
this system never measures any of those.

Return ONLY a JSON array, each item:
{{"candidate_id": "..." or null,
"title": "an original video subject + angle, written in {language}",
"why": "the opportunity, with the candidate's own number when it has one, in {language}",
"approach": "a short, original angle to take, in {language} — never a rewrite of the source"}}"""

DEFAULT_PROMPTS: dict[AgentType, str] = {
    AgentType.RESEARCH: _RESEARCH_PROMPT,
    AgentType.SCRIPT: _SCRIPT_PROMPT,
    AgentType.SCRIPT_REVIEWER: _SCRIPT_REVIEWER_PROMPT,
    AgentType.STORYBOARD: _STORYBOARD_PROMPT,
    AgentType.SCENE_DIRECTOR: _SCENE_DIRECTOR_PROMPT,
    AgentType.CHARACTER_DESIGNER: _CHARACTER_PROMPT,
    AgentType.QC: _QC_PROMPT,
    AgentType.REFERENCE_ANALYST: _REFERENCE_ANALYST_PROMPT,
    AgentType.STYLE_PROFILER: _STYLE_PROFILER_PROMPT,
    AgentType.TREND: _TREND_PROMPT,
}

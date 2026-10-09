"""Visual-planning agents: storyboard, character design, and scene direction."""

from __future__ import annotations

import re

from sqlalchemy import select

from app.agents.content import LONG_FORM_THRESHOLD_S, WORDS_PER_MINUTE
from app.core.enums import AgentType, Stage, Status
from app.db.models import Character, ChannelGrammar, Scene
from app.agents.base import BaseAgent

# Etapa 6, spec item 3: a long video has hundreds of scenes, far too many
# for the LLM to time one-by-one in a single storyboard call without just
# inventing numbers. Below this fallback, the per-scene durations the LLM
# (or the sentence split) returns are used as-is, same as before Etapa 6.
DEFAULT_LONG_SCENE_DURATION_S = 6.0

# Only the bracket convention from docs/PROMPT_CANAIS.md ("[imagem: ...]" /
# "[image: ...]") is stripped from a locked script's narration. The spec also
# mentions parenthetical "direction" asides, but with no concrete marker for
# telling those apart from a normal spoken parenthetical ("the study
# (published in 2019) found..."), stripping all parens risked mangling real
# narration — so that part was deliberately left out; flag if you want it.
_BRACKET_RE = re.compile(r"\[[^\]]*\]")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _strip_ws(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _strip_brackets(text: str) -> str:
    return re.sub(r"\s+", " ", _BRACKET_RE.sub(" ", text)).strip()


class StoryboardAgent(BaseAgent):
    """Breaks the narration into ordered scene skeletons (spec req 6)."""

    agent_type = AgentType.STORYBOARD
    stage = Stage.STORYBOARD

    def run(self) -> None:
        script = self.ctx.video.script
        if script is None or not script.content:
            raise ValueError("Cannot storyboard without a script.")

        duration = int(self.ctx.video.config.get("duration") or self.ctx.project.default_duration or 45)
        if duration >= LONG_FORM_THRESHOLD_S:
            # A video this long splits into hundreds of scenes — one LLM
            # call can't time each of them without inventing numbers, so
            # this goes straight to a deterministic, grammar-grounded split
            # regardless of script_locked.
            data = self._split_long_form(script.content)
        elif self.ctx.video.config.get("script_locked"):
            data = self._split_locked(script.content)
        else:
            prompt = self.render_prompt(script=script.content)
            data = self.parse_json(self.complete(prompt, json_mode=False))
            if isinstance(data, dict):
                data = data.get("scenes", [])
            if not isinstance(data, list) or not data:
                raise ValueError("Storyboard did not return any scenes.")
            data = [item if isinstance(item, dict) else {"narration": str(item)} for item in data]

        self._replace_scenes(data)
        self.log(f"Created {len(data)} scenes.")

    def _split_long_form(self, raw_text: str) -> list[dict]:
        """Etapa 6, spec item 3: scene count/duration for a long video
        comes from the channel's own grammar (``scene_duration_median_s``),
        not the LLM — groups consecutive sentences until each group's
        estimated spoken length reaches that target."""
        target_s = self._grammar_scene_duration_s()
        target_words = max(3, round(target_s / 60 * WORDS_PER_MINUTE))

        sentences = [s for s in _SENTENCE_SPLIT_RE.split(raw_text.strip()) if s.strip()]
        scenes: list[dict] = []
        buffer: list[str] = []
        buffer_words = 0
        for sentence in sentences:
            hints = [h.strip("[] ") for h in _BRACKET_RE.findall(sentence)]
            narration = _strip_brackets(sentence)
            if not narration:
                continue
            buffer.append(narration)
            buffer_words += len(narration.split())
            if hints:
                scenes.append(self._flush_long_scene(buffer, buffer_words, hints))
                buffer, buffer_words = [], 0
            elif buffer_words >= target_words:
                scenes.append(self._flush_long_scene(buffer, buffer_words))
                buffer, buffer_words = [], 0
        if buffer:
            scenes.append(self._flush_long_scene(buffer, buffer_words))
        return scenes or [{"narration": _strip_brackets(raw_text), "visual_description": "", "duration": target_s}]

    @staticmethod
    def _flush_long_scene(buffer: list[str], word_count: int, hints: list[str] | None = None) -> dict:
        duration = max(2.0, word_count / WORDS_PER_MINUTE * 60)
        return {
            "narration": " ".join(buffer),
            "visual_description": "; ".join(hints or []),
            "duration": round(duration, 2),
        }

    def _grammar_scene_duration_s(self) -> float:
        row = self.ctx.db.execute(
            select(ChannelGrammar).where(ChannelGrammar.project_id == self.ctx.project.id)
        ).scalar_one_or_none()
        if row and row.grammar:
            value = (row.grammar.get("scene_duration_median_s") or {}).get("value")
            if value:
                return max(2.0, float(value))
        return DEFAULT_LONG_SCENE_DURATION_S

    def _split_locked(self, raw_text: str) -> list[dict]:
        """entry_mode="script": split without rewriting a single word.

        Tries the LLM first (it can place smarter scene breaks and infer a
        visual hint per scene), but only accepts its answer if every scene's
        narration, concatenated, reproduces the original text exactly
        (ignoring whitespace) — otherwise a word-preserving sentence split
        is used instead.
        """
        target = _strip_ws(_strip_brackets(raw_text))
        items = self._try_llm_split(raw_text)
        if items is not None:
            concatenated = _strip_ws("".join(str(i.get("narration", "")) for i in items))
            if concatenated == target:
                return items
        self.log("script_locked: LLM split didn't preserve the text exactly; using a sentence split.")
        return _deterministic_split(raw_text)

    def _try_llm_split(self, raw_text: str) -> list[dict] | None:
        prompt = self.render_prompt(script=raw_text)
        try:
            data = self.parse_json(self.complete(prompt, json_mode=False))
        except Exception:  # noqa: BLE001 - any failure here just falls back
            return None
        if isinstance(data, dict):
            data = data.get("scenes", [])
        if not isinstance(data, list) or not data:
            return None
        return [item if isinstance(item, dict) else {"narration": str(item)} for item in data]

    def _replace_scenes(self, data: list[dict]) -> None:
        # Replace any existing scenes.
        for existing in list(self.ctx.video.scenes):
            self.ctx.db.delete(existing)
        self.ctx.db.flush()

        for index, item in enumerate(data, start=1):
            scene = Scene(
                video_id=self.ctx.video.id,
                index=index,
                duration=float(item.get("duration", 4) or 4),
                narration=str(item.get("narration", "")).strip(),
                visual_description=str(item.get("visual_description", "")).strip(),
                character_slugs=[str(s) for s in item.get("characters", []) if s],
                status=Status.PENDING,
            )
            self.ctx.db.add(scene)


def _deterministic_split(raw_text: str) -> list[dict]:
    """Word-preserving fallback: one scene per sentence, with that
    sentence's own [bracketed] hints moved into visual_description."""
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(raw_text.strip()) if s.strip()]
    scenes: list[dict] = []
    for sentence in sentences:
        hints = [h.strip("[] ") for h in _BRACKET_RE.findall(sentence)]
        narration = _strip_brackets(sentence)
        if not narration:
            continue  # a chunk that was only a bracketed instruction, no spoken words
        scenes.append({"narration": narration, "visual_description": "; ".join(hints)})
    return scenes or [{"narration": _strip_brackets(raw_text), "visual_description": ""}]


class CharacterDesignerAgent(BaseAgent):
    """Creates persistent characters reused across scenes (spec reqs 7/8)."""

    agent_type = AgentType.CHARACTER_DESIGNER
    stage = Stage.CHARACTERS

    def run(self) -> None:
        self.ctx.db.flush()
        slugs: set[str] = set()
        for scene in self.ctx.video.scenes:
            slugs.update(scene.character_slugs or [])
        if not slugs:
            self.log("No characters referenced; skipping character design.")
            return

        existing = {
            c.slug: c
            for c in self.ctx.project.characters
        }
        missing = sorted(s for s in slugs if s not in existing)
        if not missing:
            self.log(f"Reusing {len(slugs)} existing characters.")
            return

        prompt = self.render_prompt(character_slugs=", ".join(missing))
        try:
            data = self.parse_json(self.complete(prompt))
        except Exception as exc:  # noqa: BLE001
            self.log(f"Character design failed, continuing without: {exc}")
            return
        if isinstance(data, dict):
            data = data.get("characters", [])

        created = 0
        for item in data if isinstance(data, list) else []:
            if not isinstance(item, dict):
                continue  # a malformed entry has no slug to key a character by
            slug = str(item.get("slug", "")).strip()
            if not slug or slug in existing:
                continue
            character = Character(
                project_id=self.ctx.project.id,
                slug=slug,
                name=str(item.get("name", "")),
                age=str(item.get("age", "")),
                gender=str(item.get("gender", "")),
                appearance=str(item.get("appearance", "")),
                clothing=str(item.get("clothing", "")),
                hair=str(item.get("hair", "")),
                personality=str(item.get("personality", "")),
                visual_style=str(item.get("visual_style", "")),
                prompt_fragment=str(item.get("prompt_fragment", "")),
            )
            self.ctx.db.add(character)
            existing[slug] = character
            created += 1
        self.log(f"Designed {created} new character(s).")


class SceneDirectorAgent(BaseAgent):
    """Fills each scene with camera, lighting, and generation prompts (reqs 6/9)."""

    agent_type = AgentType.SCENE_DIRECTOR
    stage = Stage.SCENES

    def run(self) -> None:
        self.ctx.db.flush()
        characters = {c.slug: c for c in self.ctx.project.characters}
        scenes = self.ctx.video.scenes
        if not scenes:
            raise ValueError("No scenes to direct.")

        for scene in scenes:
            char_details = self._character_details(scene, characters)
            prompt = self.render_prompt(
                narration=scene.narration,
                visual_description=scene.visual_description,
                characters=char_details or "none",
            )
            try:
                data = self.parse_json(self.complete(prompt))
            except Exception as exc:  # noqa: BLE001
                self.log(f"Scene {scene.index} direction fell back: {exc}")
                data = {}
            if not isinstance(data, dict):
                # The prompt asks for a single JSON object; a model that
                # returned something else (e.g. a bare list) has nothing
                # usable here — fall back the same way a parse failure does.
                data = {}

            scene.camera = data.get("camera", {}) or {"shot": "medium_shot", "movement": "static"}
            scene.lighting = str(data.get("lighting", ""))
            scene.location = str(data.get("location", scene.location))
            scene.action = str(data.get("action", ""))
            scene.transition = str(data.get("transition", ""))
            visual = str(data.get("visual_prompt", "")).strip()
            scene.video_prompt = str(data.get("video_prompt", "")).strip()

            # Always inject character fragments so visuals stay consistent.
            fragments = [
                characters[s].prompt_fragment
                for s in (scene.character_slugs or [])
                if s in characters and characters[s].prompt_fragment
            ]
            if not visual:
                visual = scene.visual_description or scene.narration
            if fragments:
                visual = f"{visual}. Characters: " + " | ".join(fragments)
            style = self.ctx.base_fields()["style"]
            scene.visual_prompt = f"{visual}. Style: {style}."
            scene.status = Status.COMPLETED

        self.log(f"Directed {len(scenes)} scenes with camera + prompts.")

    @staticmethod
    def _character_details(scene: Scene, characters: dict[str, Character]) -> str:
        parts = []
        for slug in scene.character_slugs or []:
            c = characters.get(slug)
            if c:
                parts.append(f"{slug}: {c.name}, {c.appearance}, wearing {c.clothing}")
        return "; ".join(parts)

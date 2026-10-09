"""Visual-planning agents: storyboard, character design, and scene direction."""

from __future__ import annotations

from app.core.enums import AgentType, Stage, Status
from app.db.models import Character, Scene
from app.agents.base import BaseAgent


class StoryboardAgent(BaseAgent):
    """Breaks the narration into ordered scene skeletons (spec req 6)."""

    agent_type = AgentType.STORYBOARD
    stage = Stage.STORYBOARD

    def run(self) -> None:
        script = self.ctx.video.script
        if script is None or not script.content:
            raise ValueError("Cannot storyboard without a script.")

        prompt = self.render_prompt(script=script.content)
        data = self.parse_json(self.complete(prompt, json_mode=False))
        if isinstance(data, dict):
            data = data.get("scenes", [])
        if not isinstance(data, list) or not data:
            raise ValueError("Storyboard did not return any scenes.")

        # Replace any existing scenes.
        for existing in list(self.ctx.video.scenes):
            self.ctx.db.delete(existing)
        self.ctx.db.flush()

        for index, item in enumerate(data, start=1):
            # Not every model follows the requested "array of objects" shape
            # strictly (seen for real: a flat array of plain strings) — treat
            # a non-dict item as its own narration rather than crashing the
            # whole pipeline on an AttributeError.
            if not isinstance(item, dict):
                item = {"narration": str(item)}
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
        self.log(f"Created {len(data)} scenes.")


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

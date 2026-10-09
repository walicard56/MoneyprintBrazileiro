"""Content agents: research, script writing, and script review."""

from __future__ import annotations

import re

from app.core.enums import AgentType, Stage
from app.db.models import EditorialDirection, Script
from app.agents.base import BaseAgent
from app.services.skeleton import skeleton_from_config

# Etapa 6: at/above this target duration, ScriptAgent switches from one LLM
# call to a sectioned, checkpointed write (services/long_script territory,
# kept inline here since it's just ScriptAgent's own run() branching).
LONG_FORM_THRESHOLD_S = 240
SECTION_TARGET_S = 90
WORDS_PER_MINUTE = 150  # matches base_fields()'s own 2.5 words/sec estimate


def _clean_script(text: str) -> str:
    text = re.sub(r"\*", "", text)
    return text.strip()


class ResearchAgent(BaseAgent):
    agent_type = AgentType.RESEARCH
    stage = Stage.RESEARCH

    def run(self) -> None:
        if not self.ctx.video.topic and self.ctx.video.idea:
            self.ctx.video.topic = self.ctx.video.idea

        # entry_mode="discover": the editorial direction's own opportunity
        # evidence IS the research — asking the LLM again would be redundant
        # and risks drifting away from the reason this topic was suggested.
        direction_id = self.ctx.video.config.get("direction_id")
        if direction_id:
            direction = self.ctx.db.get(EditorialDirection, direction_id)
            if direction is not None:
                notes = f"Opportunity: {direction.why}\nApproach: {direction.approach}"
                cfg = dict(self.ctx.video.config)
                cfg["research_notes"] = notes
                self.ctx.video.config = cfg
                self.log("Used the editorial direction's opportunity/approach as research notes.")
                return

        prompt = self.render_prompt()
        try:
            notes = self.complete(prompt)
        except Exception as exc:  # noqa: BLE001 - research is optional/best-effort
            self.log(f"Research skipped: {exc}")
            return
        cfg = dict(self.ctx.video.config)
        cfg["research_notes"] = notes
        self.ctx.video.config = cfg
        self.log(f"Collected {len(notes.splitlines())} research points.")


class ScriptAgent(BaseAgent):
    agent_type = AgentType.SCRIPT
    stage = Stage.SCRIPT

    def run(self) -> None:
        notes = self.ctx.video.config.get("research_notes", "")
        duration = int(self.ctx.video.config.get("duration") or self.ctx.project.default_duration or 45)

        if duration >= LONG_FORM_THRESHOLD_S:
            text = self._run_long_form(notes, duration)
        else:
            prompt = self.render_prompt(research_notes=notes)
            text = _clean_script(self.complete(prompt))

        if not text:
            raise ValueError("Script generation returned empty text.")

        script = self.ctx.video.script
        if script is None:
            script = Script(video_id=self.ctx.video.id)
            self.ctx.db.add(script)
        script.content = text
        script.structure = self.ctx.video.config.get("structure", "")
        self.ctx.video.script = script

        target_words = round(duration / 60 * WORDS_PER_MINUTE)
        actual_words = len(text.split())
        if target_words and abs(actual_words - target_words) / target_words > 0.10:
            self.log(
                f"Script is {actual_words} words, outside +-10% of the {target_words}-word "
                f"target for {duration}s — kept as written, not retried."
            )
        self.log(f"Wrote script ({actual_words} words).")

    # --- Etapa 6: long-form, sectioned script with a resumable checkpoint ---

    def _run_long_form(self, notes: str, duration: int) -> str:
        script = self.ctx.video.script
        if script is None:
            script = Script(video_id=self.ctx.video.id, meta={})
            self.ctx.db.add(script)
            self.ctx.db.flush()
            self.ctx.video.script = script

        meta = dict(script.meta or {})
        sections = meta.get("sections")
        if not sections:
            sections = self._build_outline(duration)
            meta["sections"] = sections
            script.meta = meta
            self.ctx.db.commit()

        for i, section in enumerate(sections):
            if section.get("content"):
                continue  # already written in a previous (possibly crashed) attempt
            prior_summary = self._summarize_prior(sections[:i])
            target_words = max(20, round(section["duration_s"] / 60 * WORDS_PER_MINUTE))
            prompt = self._section_prompt(section["topic"], prior_summary, target_words, notes)
            content = _clean_script(self.complete(prompt))
            section["content"] = content
            meta["sections"] = sections
            script.meta = meta
            self.ctx.db.commit()  # checkpoint after every section, not just at the end
            self.log(f"Section {i + 1}/{len(sections)} written ({len(content.split())} words).")

        return "\n\n".join(s["content"] for s in sections if s.get("content"))

    def _build_outline(self, duration: int) -> list[dict]:
        """A skeleton (Etapa 4B), if this video has one, drives the section
        count/durations directly. Otherwise a deterministic arc (hook,
        N body sections, closing) — no extra LLM call just to outline."""
        skeleton = skeleton_from_config(self.ctx.video.config.get("skeleton"))
        if skeleton and skeleton.beats:
            return [
                {"index": i, "topic": f"{beat.role}", "duration_s": beat.duration_target_s, "content": ""}
                for i, beat in enumerate(skeleton.beats)
            ]

        n_sections = max(3, round(duration / SECTION_TARGET_S))
        each = duration / n_sections
        sections = []
        for i in range(n_sections):
            if i == 0:
                topic = "hook / introduction"
            elif i == n_sections - 1:
                topic = "conclusion / call to action"
            else:
                topic = f"development, part {i} of {n_sections - 2}"
            sections.append({"index": i, "topic": topic, "duration_s": each, "content": ""})
        return sections

    def _summarize_prior(self, written: list[dict]) -> str:
        if not written:
            return ""
        tail = " ".join((written[-1].get("content") or "").split()[-60:])
        topics_so_far = ", ".join(s["topic"] for s in written)
        return (
            f"Topics already covered: {topics_so_far}.\n"
            f'End of the immediately previous section: "...{tail}"'
        )

    def _section_prompt(self, topic: str, prior_summary: str, target_words: int, notes: str) -> str:
        base = self.ctx.base_fields()
        return (
            "You are continuing a long-form video script, one section at a time. "
            "Write ONLY this section's spoken narration — no headers, no labels, "
            "no markdown.\n\n"
            f"Niche: {base['niche']}\nTopic/theme: {base['topic']}\nLanguage: {base['language']}\n"
            f"Research notes: {notes}\n\n"
            f"{prior_summary}\n\n"
            f"This section's focus: {topic}\n"
            f"Target length: about {target_words} words (stay within ~10%).\n"
            f"{base['style_guidance']}\n{base['skeleton_guidance']}\n\n"
            "Continue naturally from where the previous section left off, if there was one. "
            f"Write in {base['language']}. Return only the narration text."
        )


class ScriptReviewerAgent(BaseAgent):
    agent_type = AgentType.SCRIPT_REVIEWER
    stage = Stage.REVIEW

    def run(self) -> None:
        script = self.ctx.video.script
        if script is None or not script.content:
            self.log("No script to review; skipping.")
            return
        prompt = self.render_prompt(script=script.content)
        try:
            improved = _clean_script(self.complete(prompt))
        except Exception as exc:  # noqa: BLE001
            self.log(f"Review skipped: {exc}")
            return
        if improved:
            script.review_notes = "Revised by Script Reviewer agent."
            script.content = improved
            self.log("Script improved by reviewer.")

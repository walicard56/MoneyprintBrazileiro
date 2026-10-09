"""Content agents: research, script writing, and script review."""

from __future__ import annotations

import re

from app.core.enums import AgentType, Stage
from app.db.models import Script
from app.agents.base import BaseAgent


def _clean_script(text: str) -> str:
    text = re.sub(r"\*", "", text)
    return text.strip()


class ResearchAgent(BaseAgent):
    agent_type = AgentType.RESEARCH
    stage = Stage.RESEARCH

    def run(self) -> None:
        if not self.ctx.video.topic and self.ctx.video.idea:
            self.ctx.video.topic = self.ctx.video.idea
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
        self.log(f"Wrote script ({len(text.split())} words).")


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

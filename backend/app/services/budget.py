"""Budget enforcement: pause generation when spend limits are hit (spec req 16)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Project
from app.services.costs import spend_summary


class BudgetExceeded(RuntimeError):
    """Raised when a spend limit would be exceeded by further generation."""


def check_budget(db: Session, project_id: str | None) -> None:
    """Raise BudgetExceeded if the project or global spend limit is reached.

    Project limits come from ``project.config`` (``daily_budget`` /
    ``monthly_budget``); global limits from ``MP_DAILY_BUDGET`` /
    ``MP_MONTHLY_BUDGET`` env vars. A limit of 0 or missing means unlimited.
    """
    # Global limits.
    global_daily = float(getattr(settings, "daily_budget", 0) or 0)
    global_monthly = float(getattr(settings, "monthly_budget", 0) or 0)
    if global_daily or global_monthly:
        total = spend_summary(db, None)
        if global_daily and total.today >= global_daily:
            raise BudgetExceeded(
                f"Global daily budget reached (${total.today:.2f} / ${global_daily:.2f})."
            )
        if global_monthly and total.month >= global_monthly:
            raise BudgetExceeded(
                f"Global monthly budget reached (${total.month:.2f} / ${global_monthly:.2f})."
            )

    if project_id is None:
        return

    project = db.get(Project, project_id)
    if project is None:
        return
    cfg = project.config or {}
    daily = float(cfg.get("daily_budget", 0) or 0)
    monthly = float(cfg.get("monthly_budget", 0) or 0)
    if not (daily or monthly):
        return

    spend = spend_summary(db, project_id)
    if daily and spend.today >= daily:
        raise BudgetExceeded(
            f"Project daily budget reached (${spend.today:.2f} / ${daily:.2f})."
        )
    if monthly and spend.month >= monthly:
        raise BudgetExceeded(
            f"Project monthly budget reached (${spend.month:.2f} / ${monthly:.2f})."
        )

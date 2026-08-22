"""
Live agent catalog — every field derived from running code, never hardcoded.

Sources:
  - AGENT_ALLOWLISTS (wrap.py)        -> agent ids + tool allowlists
  - DEFAULT_TOOL_REGISTRY (policy.py) -> risk tier per tool
  - the live APScheduler jobs         -> trigger_type + schedule
  - run_store.get_last_run            -> last_run status

Only `name` and `category` below are hand-authored display metadata — they
have no live source to derive from and aren't operational data.
"""

from __future__ import annotations

from typing import Any, Optional

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .wrap import AGENT_ALLOWLISTS
from .policy import DEFAULT_TOOL_REGISTRY
from . import run_store

AGENT_LABELS: dict[str, tuple[str, str]] = {
    "support_chat": ("Support Chat", "chat"),
    "demand_forecast": ("Demand Forecast", "scheduled"),
    "inventory_reorder": ("Inventory Reorder", "scheduled"),
    "churn_prevention": ("Churn Prevention", "scheduled"),
    "review_response": ("Review Response", "event"),
    "shift_optimisation": ("Shift Optimisation", "scheduled"),
    "kitchen_coach": ("Kitchen Coach", "scheduled"),
    "dynamic_pricing": ("Dynamic Pricing", "scheduled"),
}

ENDPOINT_MAP: dict[str, str] = {
    "support_chat": "/agent/chat",
    "demand_forecast": "/agents/demand-forecast/trigger",
    "inventory_reorder": "/agents/inventory-reorder/trigger",
    "churn_prevention": "/agents/churn-prevention/trigger",
    "review_response": "/agents/review-response/trigger",
    "shift_optimisation": "/agents/shift-optimisation/trigger",
    "kitchen_coach": "/agents/kitchen-coach/trigger",
    "dynamic_pricing": "/agents/dynamic-pricing/trigger",
}

# Agents with no scheduler job at all — the schedule is structurally absent,
# not merely unregistered yet.
NO_SCHEDULER_JOB: dict[str, str] = {
    "support_chat": "chat",
    "review_response": "rabbitmq+manual",
}


def _describe_trigger(trigger: Any) -> tuple[str, str]:
    if isinstance(trigger, IntervalTrigger):
        total_seconds = trigger.interval.total_seconds()
        hours = total_seconds / 3600
        if hours == int(hours):
            return "interval", f"every {int(hours)}h"
        return "interval", f"every {int(total_seconds)}s"
    if isinstance(trigger, CronTrigger):
        parts = [
            f"{field.name}={field}"
            for field in trigger.fields
            if str(field) != "*"
        ]
        return "cron", ", ".join(parts)
    return "unknown", str(trigger)


def build_registry() -> list[dict]:
    from ..scheduler.scheduler import get_scheduler

    jobs_by_id = {job.id: job for job in get_scheduler().get_jobs()}

    entries: list[dict] = []
    for agent_id, tools in AGENT_ALLOWLISTS.items():
        name, category = AGENT_LABELS.get(agent_id, (agent_id, "scheduled"))

        if agent_id in NO_SCHEDULER_JOB:
            trigger_type: str = NO_SCHEDULER_JOB[agent_id]
            schedule: Optional[str] = None
        else:
            job = jobs_by_id.get(agent_id)
            if job is not None:
                trigger_type, schedule = _describe_trigger(job.trigger)
            else:
                trigger_type, schedule = "unknown", None

        allowlist = [
            {"name": t, "tier": DEFAULT_TOOL_REGISTRY[t].tier.value}
            for t in tools
            if t in DEFAULT_TOOL_REGISTRY
        ]

        entries.append({
            "id": agent_id,
            "name": name,
            "category": category,
            "trigger_type": trigger_type,
            "schedule": schedule,
            "tool_allowlist": allowlist,
            "last_run": run_store.get_last_run(agent_id),
            "endpoint": ENDPOINT_MAP.get(agent_id, ""),
        })
    return entries

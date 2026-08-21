"""
APScheduler configuration for MaSoVa background agents.
Uses AsyncIOScheduler so all jobs run in the same event loop as FastAPI.
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.executors.asyncio import AsyncIOExecutor
import logging

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(
    executors={"default": AsyncIOExecutor()},
    job_defaults={"coalesce": True, "max_instances": 1},
    timezone="Asia/Kolkata",
)


def get_scheduler() -> AsyncIOScheduler:
    return scheduler


def register_jobs():
    """Register all scheduled agent jobs. Call this after scheduler.start()."""
    from ..agents.demand_forecasting_agent import run_demand_forecast
    from ..agents.inventory_reorder_agent import run_inventory_reorder
    from ..agents.churn_prevention_agent import run_churn_prevention
    from ..agents.shift_optimisation_agent import run_shift_optimisation
    from ..agents.kitchen_coach_agent import run_kitchen_coach
    from ..agents.dynamic_pricing_agent import run_dynamic_pricing

    # Agent 2: Demand Forecasting — nightly at 2am IST
    scheduler.add_job(
        run_demand_forecast,
        trigger="cron",
        hour=2,
        minute=0,
        id="demand_forecast",
        name="Demand Forecasting Agent",
        replace_existing=True,
    )

    # Agent 3: Inventory Reorder — every 6 hours
    scheduler.add_job(
        run_inventory_reorder,
        trigger="interval",
        hours=6,
        id="inventory_reorder",
        name="Inventory Reorder Agent",
        replace_existing=True,
    )

    # Agent 4: Churn Prevention — daily at 10am IST
    scheduler.add_job(
        run_churn_prevention,
        trigger="cron",
        hour=10,
        minute=0,
        id="churn_prevention",
        name="Churn Prevention Agent",
        replace_existing=True,
    )

    # Agent 6: Shift Optimisation — Sundays 8pm
    scheduler.add_job(
        run_shift_optimisation,
        trigger="cron",
        day_of_week="sun",
        hour=20,
        id="shift_optimisation",
        name="Shift Optimisation Agent",
        replace_existing=True,
    )

    # Agent 7: Kitchen Performance Coach — nightly 11pm
    scheduler.add_job(
        run_kitchen_coach,
        trigger="cron",
        hour=23,
        id="kitchen_coach",
        name="Kitchen Performance Coach",
        replace_existing=True,
    )

    # Agent 8: Dynamic Pricing — every 30min during 9am-10pm
    scheduler.add_job(
        run_dynamic_pricing,
        trigger="cron",
        hour="9-22",
        minute="0,30",
        id="dynamic_pricing",
        name="Dynamic Pricing Agent",
        replace_existing=True,
    )

    logger.info("Registered %d scheduled agent jobs", len(scheduler.get_jobs()))

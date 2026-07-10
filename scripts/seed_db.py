"""
scripts/seed_db.py
───────────────────
Idempotent database seeder — creates all rows required for the system to
start correctly on a fresh PostgreSQL database.

What is seeded:
  1. AutomationModule row for each YAML module config (inspection_station)
  2. Agent rows:
       - inspection_station_operator  (OPERATOR, module=inspection_station)
       - manager                      (MANAGER,  module=None)
  3. AgentSubscription rows:
       inspection_station_operator → ["Inspection Station", "MES"]

All operations are idempotent — running this script twice will not create
duplicate rows. Existing rows are left unchanged.

Usage:
    python scripts/seed_db.py

Prerequisites:
  - DATABASE_URL set in .env or environment
  - PostgreSQL server running and the database created
  - Alembic migrations applied: alembic upgrade head
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to sys.path so imports work when run as a script
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.module_loader import load_all_module_configs
from config.settings import get_settings
from db.models.agent import Agent, AgentSubscription, AgentType, AgentStatus
from db.models.automation_module import AutomationModule
from db.session import get_session_factory, init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("seed_db")


async def seed(db: AsyncSession) -> None:
    settings = get_settings()
    module_configs = load_all_module_configs(settings.modules_config_dir)

    # ── 1. AutomationModule rows ───────────────────────────────────────────────
    module_db_ids: dict[str, object] = {}

    for module_id, cfg in module_configs.items():
        result = await db.execute(
            select(AutomationModule).where(
                AutomationModule.module_id == module_id
            )
        )
        existing = result.scalar_one_or_none()

        if existing is not None:
            logger.info("AutomationModule '%s' already exists — skipping.", module_id)
            module_db_ids[module_id] = existing.id
        else:
            row = AutomationModule(
                module_id=module_id,
                display_name=cfg.display_name,
                config_snapshot=cfg.model_dump(),
            )
            db.add(row)
            await db.flush()
            module_db_ids[module_id] = row.id
            logger.info(
                "AutomationModule '%s' created (id=%s).", module_id, row.id
            )

    # ── 2. Agent rows ──────────────────────────────────────────────────────────

    agents_to_seed = []

    # One OPERATOR agent per module
    for module_id, cfg in module_configs.items():
        agents_to_seed.append({
            "agent_id": f"{module_id}_operator",
            "agent_type": AgentType.OPERATOR,
            "module_db_id": module_db_ids[module_id],
            "subscriptions": list(cfg.subscription_scopes()),
        })

    # One MANAGER agent (no module FK)
    agents_to_seed.append({
        "agent_id": "manager",
        "agent_type": AgentType.MANAGER,
        "module_db_id": None,
        "subscriptions": [],
    })

    agent_db_ids: dict[str, object] = {}

    for spec in agents_to_seed:
        result = await db.execute(
            select(Agent).where(Agent.agent_id == spec["agent_id"])
        )
        existing = result.scalar_one_or_none()

        if existing is not None:
            logger.info(
                "Agent '%s' already exists — skipping.", spec["agent_id"]
            )
            agent_db_ids[spec["agent_id"]] = existing.id
        else:
            row = Agent(
                agent_id=spec["agent_id"],
                agent_type=spec["agent_type"],
                module_id=spec["module_db_id"],
                last_event_sequence=0,
                status=AgentStatus.IDLE,
            )
            db.add(row)
            await db.flush()
            agent_db_ids[spec["agent_id"]] = row.id
            logger.info(
                "Agent '%s' created (id=%s).", spec["agent_id"], row.id
            )

    # ── 3. AgentSubscription rows ──────────────────────────────────────────────

    for spec in agents_to_seed:
        if not spec["subscriptions"]:
            continue

        agent_db_id = agent_db_ids[spec["agent_id"]]

        for scope in spec["subscriptions"]:
            result = await db.execute(
                select(AgentSubscription).where(
                    AgentSubscription.agent_id == agent_db_id,
                    AgentSubscription.event_scope == scope,
                )
            )
            existing = result.scalar_one_or_none()

            if existing is not None:
                logger.info(
                    "Subscription '%s' → '%s' already exists — skipping.",
                    spec["agent_id"], scope,
                )
            else:
                sub = AgentSubscription(
                    agent_id=agent_db_id,
                    event_scope=scope,
                )
                db.add(sub)
                logger.info(
                    "Subscription '%s' → '%s' created.",
                    spec["agent_id"], scope,
                )

    await db.commit()
    logger.info("Seeding complete.")


async def main() -> None:
    settings = get_settings()
    logger.info("Connecting to: %s", settings.database_url.rsplit("/", 1)[-1])
    init_db(settings.database_url, echo=False)

    async with get_session_factory()() as db:
        await seed(db)


if __name__ == "__main__":
    asyncio.run(main())
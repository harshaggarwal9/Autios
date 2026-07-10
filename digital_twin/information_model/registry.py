"""
digital_twin/information_model/registry.py
───────────────────────────────────────────
ModuleRegistry — creates and owns one InformationModel per automation module.

Paper connection (§II.B — Digital Twins):
  The registry initialises each module's InformationModel at startup, optionally
  restoring the last persisted state snapshot so the digital twin picks up
  from where it left off after a process restart.

Lifecycle:
  1. startup:  ModuleRegistry.initialise(module_configs, db)
               — creates InformationModels, queries most recent snapshots
  2. runtime:  get_model(module_id) → InformationModel
               — used by DataObserver, AdapterManager, CommandInterface
  3. shutdown: save_snapshot(module_id, db)
               — persists final state to module_state_snapshots

Dependencies:
  db.models.automation_module.AutomationModule
  db.models.state_snapshot.ModuleStateSnapshot
  digital_twin.information_model.model.InformationModel
  sqlalchemy async
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.module_loader import ModuleConfig
from db.models.automation_module import AutomationModule
from db.models.state_snapshot import ModuleStateSnapshot
from digital_twin.information_model.model import InformationModel

logger = logging.getLogger(__name__)


class ModuleRegistry:
    """
    Owns one InformationModel per registered automation module.

    Held on app.state.module_registry. All components that need to read
    or write module state go through this registry.
    """

    def __init__(self) -> None:
        # module_id (str) → InformationModel
        self._models: dict[str, InformationModel] = {}
        # module_id (str) → AutomationModule.id (UUID) for snapshot FK
        self._db_ids: dict[str, uuid.UUID] = {}

    async def initialise(
        self,
        module_configs: dict[str, ModuleConfig],
        db: AsyncSession,
    ) -> None:
        """
        Create InformationModels for all module configs and restore
        the most recent state snapshot from the DB (if any).

        Also upserts an AutomationModule row for each module so the
        module exists in the DB before any FK references are created.

        Args:
            module_configs: dict[module_id → ModuleConfig] from YAML loader.
            db:             Open AsyncSession — caller commits after this returns.
        """
        for module_id, cfg in module_configs.items():
            # Upsert AutomationModule row
            module_db_id = await self._upsert_module(db, cfg)
            self._db_ids[module_id] = module_db_id

            # Build InformationModel from YAML schema
            model = InformationModel(cfg)

            # Restore most recent snapshot if one exists
            snapshot_state = await self._load_latest_snapshot(db, module_db_id)
            if snapshot_state:
                model.update_from_snapshot(snapshot_state)
                logger.info(
                    "ModuleRegistry: restored snapshot for '%s'.", module_id
                )

            self._models[module_id] = model
            logger.info(
                "ModuleRegistry: initialised model for '%s' (%d nodes).",
                module_id, len(model.node_ids()),
            )

        logger.info(
            "ModuleRegistry: %d module(s) initialised: %s",
            len(self._models), list(self._models.keys()),
        )

    def get_model(self, module_id: str) -> InformationModel:
        """
        Return the InformationModel for a module.

        Raises:
            KeyError: if module_id is not registered — always a config bug.
        """
        try:
            return self._models[module_id]
        except KeyError:
            raise KeyError(
                f"No InformationModel for module_id={module_id!r}. "
                f"Registered: {list(self._models.keys())}"
            )

    def all_module_ids(self) -> list[str]:
        return list(self._models.keys())

    def get_db_id(self, module_id: str) -> uuid.UUID:
        """Return the AutomationModule.id (UUID) for FK references."""
        return self._db_ids[module_id]

    async def save_snapshot(self, module_id: str, db: AsyncSession) -> None:
        """
        Persist the current state of a module to module_state_snapshots.

        Called at shutdown and periodically by the DataObserver.
        Creates a new snapshot row each time (the table is append-only;
        the most recent row is loaded on next startup).

        Args:
            module_id: The module to snapshot.
            db:        Open AsyncSession — caller must commit after this returns.
        """
        model = self.get_model(module_id)
        module_db_id = self._db_ids.get(module_id)
        if module_db_id is None:
            logger.warning(
                "ModuleRegistry.save_snapshot: no DB id for '%s' — skipping.",
                module_id,
            )
            return

        snapshot = ModuleStateSnapshot(
            module_id=module_db_id,
            state=model.get_state(),
        )
        db.add(snapshot)
        logger.debug("ModuleRegistry: snapshot queued for '%s'.", module_id)

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    async def _upsert_module(db: AsyncSession, cfg: ModuleConfig) -> uuid.UUID:
        """
        Insert or update the AutomationModule row for a module config.

        Returns the row's UUID (for FK use in snapshots).
        """
        result = await db.execute(
            select(AutomationModule).where(
                AutomationModule.module_id == cfg.module_id
            )
        )
        existing = result.scalar_one_or_none()

        if existing is not None:
            # Update display_name in case the YAML changed
            existing.display_name = cfg.display_name
            return existing.id

        new_module = AutomationModule(
            module_id=cfg.module_id,
            display_name=cfg.display_name,
            config_snapshot=cfg.model_dump(),
        )
        db.add(new_module)
        await db.flush()  # populate server-generated id
        return new_module.id

    @staticmethod
    async def _load_latest_snapshot(
        db: AsyncSession,
        module_db_id: uuid.UUID,
    ) -> dict | None:
        """
        Load the most recent state snapshot for a module, or return None.
        """
        result = await db.execute(
            select(ModuleStateSnapshot)
            .where(ModuleStateSnapshot.module_id == module_db_id)
            .order_by(ModuleStateSnapshot.recorded_at.desc())
            .limit(1)
        )
        snapshot = result.scalar_one_or_none()
        return snapshot.state if snapshot is not None else None
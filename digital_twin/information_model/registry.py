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
  

    def __init__(self) -> None:

        self._models: dict[str, InformationModel] = {}

        self._db_ids: dict[str, uuid.UUID] = {}

    async def initialise(
        self,
        module_configs: dict[str, ModuleConfig],
        db: AsyncSession,
    ) -> None:

        for module_id, cfg in module_configs.items():

            module_db_id = await self._upsert_module(db, cfg)
            self._db_ids[module_id] = module_db_id


            model = InformationModel(cfg)


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
        
        return self._db_ids[module_id]

    async def save_snapshot(self, module_id: str, db: AsyncSession) -> None:

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



    @staticmethod
    async def _upsert_module(db: AsyncSession, cfg: ModuleConfig) -> uuid.UUID:

        result = await db.execute(
            select(AutomationModule).where(
                AutomationModule.module_id == cfg.module_id
            )
        )
        existing = result.scalar_one_or_none()

        if existing is not None:

            existing.display_name = cfg.display_name
            return existing.id

        new_module = AutomationModule(
            module_id=cfg.module_id,
            display_name=cfg.display_name,
            config_snapshot=cfg.model_dump(),
        )
        db.add(new_module)
        await db.flush()
        return new_module.id

    @staticmethod
    async def _load_latest_snapshot(
        db: AsyncSession,
        module_db_id: uuid.UUID,
    ) -> dict | None:
    
        result = await db.execute(
            select(ModuleStateSnapshot)
            .where(ModuleStateSnapshot.module_id == module_db_id)
            .order_by(ModuleStateSnapshot.recorded_at.desc())
            .limit(1)
        )
        snapshot = result.scalar_one_or_none()
        return snapshot.state if snapshot is not None else None

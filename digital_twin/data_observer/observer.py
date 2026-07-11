import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.event_log.store import EventLogStore
from digital_twin.data_observer.rule_engine import RuleEngine
from digital_twin.information_model.model import InformationModel
from digital_twin.information_model.registry import ModuleRegistry
from schemas.event import EventCreate

logger = logging.getLogger(__name__)



SNAPSHOT_EVERY_N_CYCLES = 100


class DataObserver:


    def __init__(
        self,
        model: InformationModel,
        rule_engine: RuleEngine,
        module_registry: ModuleRegistry,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._model = model
        self._rule_engine = rule_engine
        self._module_registry = module_registry
        self._session_factory = session_factory
        self._module_id = model.module_id
        self._cycle_count = 0

    async def run(self) -> None:

        logger.info("DataObserver '%s' started.", self._module_id)

        while True:
            try:

                await self._model.change_event.wait()



                self._model.change_event.clear()


                changed = self._model.get_changed_nodes()
                if not changed:

                    continue









                self._model.acknowledge_changes(list(changed.keys()))

                logger.debug(
                    "DataObserver '%s': %d node(s) changed: %s",
                    self._module_id,
                    len(changed),
                    list(changed.keys()),
                )


                events_to_emit: list[EventCreate] = []
                for node_id, (old_value, new_value) in changed.items():
                    semantic_events = self._rule_engine.evaluate(
                        node_id, old_value, new_value
                    )
                    for evt in semantic_events:
                        events_to_emit.append(
                            EventCreate(
                                scope=evt.scope,
                                source=evt.source,
                                text=evt.text,
                                metadata={
                                    "node_id": node_id,
                                    "old_value": old_value,
                                    "new_value": new_value,
                                },
                            )
                        )


                if events_to_emit:
                    async with self._session_factory() as db:
                        store = EventLogStore(db)
                        emitted = await store.append_many(events_to_emit)
                        await db.commit()
                    logger.debug(
                        "DataObserver '%s': emitted %d event(s) (seq %d–%d).",
                        self._module_id,
                        len(emitted),
                        emitted[0].sequence_id,
                        emitted[-1].sequence_id,
                    )


                self._cycle_count += 1
                if self._cycle_count % SNAPSHOT_EVERY_N_CYCLES == 0:
                    async with self._session_factory() as db:
                        await self._module_registry.save_snapshot(
                            self._module_id, db
                        )
                        await db.commit()
                    logger.debug(
                        "DataObserver '%s': snapshot saved at cycle %d.",
                        self._module_id, self._cycle_count,
                    )

            except asyncio.CancelledError:
                logger.info("DataObserver '%s' cancelled.", self._module_id)
                raise

            except Exception as exc:
                logger.exception(
                    "DataObserver '%s' unhandled error (will retry): %s",
                    self._module_id, exc,
                )

                await asyncio.sleep(1.0)


class DataObserverManager:

    def __init__(self) -> None:
        self._observers: dict[str, DataObserver] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    def start(
        self,
        module_registry: ModuleRegistry,
        rule_engines: dict[str, RuleEngine],
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:

        for module_id in module_registry.all_module_ids():
            if module_id not in rule_engines:
                logger.warning(
                    "DataObserverManager: no RuleEngine for '%s' — "
                    "observer will not start for this module. "
                    "Check that a *_rules.yaml file exists.", module_id,
                )
                continue

            model = module_registry.get_model(module_id)
            rule_engine = rule_engines[module_id]

            observer = DataObserver(
                model=model,
                rule_engine=rule_engine,
                module_registry=module_registry,
                session_factory=session_factory,
            )
            self._observers[module_id] = observer

            task = asyncio.create_task(
                observer.run(),
                name=f"data_observer_{module_id}",
            )
            self._tasks[module_id] = task

            logger.info(
                "DataObserverManager: started observer for '%s'.", module_id
            )

        logger.info(
            "DataObserverManager: %d observer(s) running: %s",
            len(self._tasks), list(self._tasks.keys()),
        )

    async def stop(self) -> None:
        
        for module_id, task in self._tasks.items():
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            logger.info("DataObserverManager: observer '%s' stopped.", module_id)

        self._tasks.clear()
        self._observers.clear()

    def get_observer(self, module_id: str) -> DataObserver:
        
        try:
            return self._observers[module_id]
        except KeyError:
            raise KeyError(
                f"No DataObserver for module_id={module_id!r}. "
                f"Registered: {list(self._observers.keys())}"
            )

    def all_module_ids(self) -> list[str]:
        return list(self._observers.keys())

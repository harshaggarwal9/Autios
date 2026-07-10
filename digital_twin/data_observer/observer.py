"""
digital_twin/data_observer/observer.py
───────────────────────────────────────
DataObserver — watches an InformationModel for state changes, evaluates
them against the RuleEngine, and emits semantic events to the EventLogStore.

Paper connection (§II.B — Digital Twins and Semantics, Figure 3):
  "The data observer watches the information model for changes and converts
  low-level sensor/actuator state transitions into high-level semantic
  events that are stored in the shared event log."

  This class is the bridge between the digital twin layer and the event bus.
  It runs as a persistent asyncio background task per module.

Processing cycle (per wake-up):
  1. Await change_event (set by InformationModel.update_node/update_many).
  2. Clear the event immediately (prevents missing changes that happen
     during processing — if a change arrives while we're building events,
     change_event will be set again and we'll wake up next iteration).
  3. Read get_changed_nodes() → dict of {node_id: (old, new)}.
  4. Call acknowledge_changes() IMMEDIATELY after reading — this syncs
     _previous_state and prevents stale re-emission of already-handled
     transitions (Phase 5 bug fix).
  5. Evaluate each changed node against the RuleEngine.
  6. For nodes that produced semantic events: call EventLogStore.append_many().
  7. Periodically save a state snapshot.

Bug fix (Phase 5):
  Step 4 (acknowledge_changes) was added after discovering that
  get_changed_nodes() would re-report the same (old, new) pair indefinitely
  if _previous_state was never synced. This caused the DataObserver to
  re-emit stale events on every cycle after the first state change.

Dependencies:
  digital_twin.information_model.model.InformationModel
  digital_twin.information_model.registry.ModuleRegistry
  digital_twin.data_observer.rule_engine.RuleEngine
  core.event_log.store.EventLogStore
  schemas.event.EventCreate
  sqlalchemy async
"""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.event_log.store import EventLogStore
from digital_twin.data_observer.rule_engine import RuleEngine
from digital_twin.information_model.model import InformationModel
from digital_twin.information_model.registry import ModuleRegistry
from schemas.event import EventCreate

logger = logging.getLogger(__name__)

# Save a state snapshot every N observation cycles (not every wake-up,
# to avoid excessive DB writes in high-frequency scenarios).
SNAPSHOT_EVERY_N_CYCLES = 100


class DataObserver:
    """
    Watches one InformationModel and emits semantic events on state changes.

    One DataObserver per module, running as a background asyncio task.
    """

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
        """
        Main observation loop — runs until asyncio.CancelledError.

        Awaits InformationModel.change_event, then processes all nodes
        that changed since the last acknowledgement.
        """
        logger.info("DataObserver '%s' started.", self._module_id)

        while True:
            try:
                # Wait for a state change
                await self._model.change_event.wait()

                # Clear event BEFORE reading changed nodes so we don't miss
                # any changes that occur during our processing below.
                self._model.change_event.clear()

                # ── Read all changes since last observation ────────────────────
                changed = self._model.get_changed_nodes()
                if not changed:
                    # Spurious wake-up (should not happen, but be defensive)
                    continue

                # Acknowledge immediately: sync _previous_state to _state for
                # every node we just read, so the SAME transition is never
                # reported again on a future get_changed_nodes() call. This
                # must happen before we build/emit events below — if event
                # emission fails and we retry, re-reading the already-
                # acknowledged nodes is harmless (they will simply show no
                # change), whereas failing to acknowledge would cause
                # infinite re-emission of stale transitions.
                self._model.acknowledge_changes(list(changed.keys()))

                logger.debug(
                    "DataObserver '%s': %d node(s) changed: %s",
                    self._module_id,
                    len(changed),
                    list(changed.keys()),
                )

                # ── Evaluate rules and collect semantic events ─────────────────
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

                # ── Emit to EventLogStore ─────────────────────────────────────
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

                # ── Periodic snapshot ─────────────────────────────────────────
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
                # Brief sleep to avoid tight error loops
                await asyncio.sleep(1.0)


class DataObserverManager:
    """
    Owns and manages DataObserver background tasks for all modules.

    One DataObserverManager per application, held on app.state.
    """

    def __init__(self) -> None:
        self._observers: dict[str, DataObserver] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    def start(
        self,
        module_registry: ModuleRegistry,
        rule_engines: dict[str, RuleEngine],
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """
        Create and start one DataObserver task per registered module.

        Args:
            module_registry: Provides InformationModel for each module.
            rule_engines:    dict[module_id → RuleEngine] from YAML loader.
            session_factory: For EventLogStore writes and snapshot saves.
        """
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
        """Cancel all observer tasks and wait for them to finish."""
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
        """Return the DataObserver for a module."""
        try:
            return self._observers[module_id]
        except KeyError:
            raise KeyError(
                f"No DataObserver for module_id={module_id!r}. "
                f"Registered: {list(self._observers.keys())}"
            )

    def all_module_ids(self) -> list[str]:
        return list(self._observers.keys())
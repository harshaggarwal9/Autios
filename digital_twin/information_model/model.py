"""
digital_twin/information_model/model.py
────────────────────────────────────────
InformationModel — the in-memory digital twin of one automation module.

Paper connection (§II.B — Digital Twins):
  "A digital twin maintains a synchronized digital representation of a
  physical asset. The information model maps every sensor and actuator
  node to its current value."

  This class is the runtime state dict for one module (e.g. the Inspection
  Station). Keys are node_ids from the module YAML (BG51, H2, C1_running,
  etc.) and values are their current states (bool, str, float, etc.).

Key design decisions:
  1. change_event (asyncio.Event) — wakes the DataObserver whenever any
     node changes. Single shared event per model; the observer clears it
     after reading.

  2. get_changed_nodes() + acknowledge_changes() — a two-step read protocol
     that prevents the DataObserver from re-emitting stale transitions.
     MUST call acknowledge_changes() after processing get_changed_nodes()
     output, or the same transition will be reported forever.

  3. register_node_if_absent() — adds new schema nodes at construction time
     (e.g. "emergency_stop_active" added by CommandInterface). Distinct
     from update_from_snapshot() which only updates EXISTING nodes.

Bug fix (Phase 5 integration):
  The original get_changed_nodes() implementation never reset _previous_state,
  causing the DataObserver to re-emit stale events indefinitely. Fixed by
  adding acknowledge_changes() and calling it in DataObserver.run() immediately
  after reading changed nodes.

Dependencies:
  asyncio (stdlib), copy.deepcopy, config.module_loader.ModuleConfig
"""

import asyncio
import logging
from copy import deepcopy
from typing import Any

from config.module_loader import ModuleConfig

logger = logging.getLogger(__name__)

StateDict = dict[str, Any]


class InformationModel:
    """
    In-memory state machine for one automation module.

    One instance per module, created by ModuleRegistry at startup and held
    for the lifetime of the process. All reads and writes are synchronous
    except update_node() and update_many() which are async to allow callers
    to await them in async contexts.
    """

    def __init__(self, module_config: ModuleConfig) -> None:
        self._module_id = module_config.module_id
        self._module_config = module_config

        # Primary state dict: node_id → current value
        self._state: StateDict = self._build_initial_state(module_config)

        # Previous state snapshot for change detection.
        # _previous_state[node_id] is the value the node held BEFORE the
        # most recent update_node() / update_many() call on that node.
        # acknowledge_changes() syncs this to _state after consumption.
        self._previous_state: StateDict = deepcopy(self._state)

        # Signalled whenever any node changes value.
        # DataObserver.run() awaits this; update_node/update_many set it.
        self.change_event = asyncio.Event()

        logger.info(
            "InformationModel '%s' initialised with %d nodes.",
            self._module_id, len(self._state),
        )

    # ── State initialisation ──────────────────────────────────────────────────

    @staticmethod
    def _build_initial_state(cfg: ModuleConfig) -> StateDict:
        """
        Build the initial state dict from the module YAML definition.

        Sensors default to False (not detecting).
        Actuators default based on type:
          - holder → True  (paper: holders are "normally at holding position")
          - switch → "continue"  (paper: switch default path is straight through)
        Conveyors get two nodes each:
          - {C}_running → False   (conveyor not running initially)
          - {C}_direction → "forward"  (default direction)
        """
        state: StateDict = {}

        # Sensor nodes — all default to False (not detecting)
        for sensor in cfg.component_description.sensors:
            state[sensor.node_id] = False

        # Actuator nodes
        for actuator in cfg.component_description.actuators:
            if actuator.type == "holder":
                state[actuator.node_id] = True   # normally in holding position
            elif actuator.type == "switch":
                state[actuator.node_id] = "continue"  # default path
            else:
                state[actuator.node_id] = False

        # Conveyor nodes (one running + one direction flag per conveyor)
        for conveyor in cfg.component_description.conveyors:
            state[f"{conveyor.id}_running"] = False
            state[f"{conveyor.id}_direction"] = "forward"

        return state

    # ── Node read / write ─────────────────────────────────────────────────────

    def get_node(self, node_id: str) -> Any:
        """Return the current value of a node, or None if not registered."""
        return self._state.get(node_id)

    def get_state(self) -> StateDict:
        """Return a deep copy of the entire state dict."""
        return deepcopy(self._state)

    def get_previous_state(self) -> StateDict:
        """Return a deep copy of the previous state dict (before last update)."""
        return deepcopy(self._previous_state)

    async def update_node(self, node_id: str, value: Any) -> bool:
        """
        Update a single node's value.

        Returns True if the value actually changed, False if it was already
        equal. Only sets change_event when the value changes.

        The caller is responsible for calling acknowledge_changes() after
        reading get_changed_nodes() to prevent stale re-emission.
        """
        if node_id not in self._state:
            logger.warning(
                "InformationModel '%s': update_node called for unknown "
                "node_id '%s'. Call register_node_if_absent() first.",
                self._module_id, node_id,
            )
            return False

        old_value = self._state[node_id]
        if old_value == value:
            return False

        self._previous_state[node_id] = old_value
        self._state[node_id] = value
        self.change_event.set()

        logger.debug(
            "InformationModel '%s': %s: %r → %r",
            self._module_id, node_id, old_value, value,
        )
        return True

    async def update_many(self, updates: dict[str, Any]) -> list[str]:
        """
        Update multiple nodes atomically (single change_event signal).

        Returns the list of node_ids that actually changed.
        """
        changed: list[str] = []

        for node_id, value in updates.items():
            if node_id not in self._state:
                logger.warning(
                    "InformationModel '%s': update_many skipping unknown "
                    "node_id '%s'.", self._module_id, node_id,
                )
                continue

            old_value = self._state[node_id]
            if old_value != value:
                self._previous_state[node_id] = old_value
                self._state[node_id] = value
                changed.append(node_id)

        if changed:
            self.change_event.set()
            logger.debug(
                "InformationModel '%s': update_many changed %d node(s): %s",
                self._module_id, len(changed), changed,
            )

        return changed

    # ── Change detection (two-step read protocol) ─────────────────────────────

    def get_changed_nodes(self) -> dict[str, tuple[Any, Any]]:
        """
        Return nodes whose value changed since the last acknowledgement.

        Returns dict of {node_id: (old_value, new_value)}.
        Called by the DataObserver immediately after change_event is set.

        IMPORTANT: callers MUST call acknowledge_changes() after processing
        the returned dict. Without that call, the same (old, new) pair will
        be reported again on every subsequent call to get_changed_nodes()
        forever — see acknowledge_changes() docstring for the full explanation.
        """
        changed: dict[str, tuple[Any, Any]] = {}
        for node_id, current_value in self._state.items():
            prev = self._previous_state.get(node_id)
            if current_value != prev:
                changed[node_id] = (prev, current_value)
        return changed

    def acknowledge_changes(self, node_ids: list[str]) -> None:
        """
        Mark the given nodes' changes as consumed by syncing _previous_state
        to their current _state value.

        Bug fix rationale:
          update_node()/update_many() set _previous_state[node_id] to the
          value the node held immediately BEFORE that specific write, and
          never touch _previous_state again afterwards. If a consumer (the
          DataObserver) reads get_changed_nodes(), processes the result, but
          nothing ever updates _previous_state to match the new _state, the
          SAME (old, new) pair is reported as "changed" on every future call
          to get_changed_nodes() — even though it was already handled. This
          previously caused the DataObserver to re-emit the same semantic
          event indefinitely after the first state transition on any node
          that was never written to again.

          The fix follows the standard read-then-acknowledge pattern used by
          message queues: get_changed_nodes() is the "peek/read" step,
          acknowledge_changes() is the explicit "commit" step. The
          DataObserver calls this immediately after building (and
          successfully persisting) events for the changes it just read.

        Args:
            node_ids: The nodes whose changes have been fully processed.
                      Typically exactly the keys returned by the preceding
                      get_changed_nodes() call.
        """
        for node_id in node_ids:
            if node_id in self._state:
                self._previous_state[node_id] = self._state[node_id]

    # ── Schema management ─────────────────────────────────────────────────────

    def update_from_snapshot(self, snapshot: StateDict) -> None:
        """
        Overwrite current state from a persisted snapshot.

        Called once at startup by the ModuleRegistry after loading the most
        recent module_state_snapshots row. Silently ignores keys in the
        snapshot that are not in the current state schema (e.g. from an older
        schema version).

        Safety guarantee: this method NEVER introduces new keys into the
        schema. Only keys already present in self._state are updated.
        Use register_node_if_absent() to intentionally extend the schema.
        """
        for key, value in snapshot.items():
            if key in self._state:
                self._state[key] = value
        self._previous_state = deepcopy(self._state)
        logger.info(
            "InformationModel '%s' restored from snapshot (%d nodes).",
            self._module_id, len(snapshot),
        )

    def register_node_if_absent(self, node_id: str, default_value: Any) -> None:
        """
        Add a new node to the schema with a default value, if not already present.

        Distinct from update_from_snapshot(): that method only restores values
        for nodes already in the schema (crash-recovery safety guarantee —
        it must never silently introduce new nodes from a stale snapshot).
        This method is the explicit, intentional way to extend the schema at
        construction time — e.g. CommandInterface registers
        "emergency_stop_active" here since it is not part of the paper's
        sensor/actuator component list but is required runtime safety state.

        Synchronous: this is schema setup, not a runtime state transition,
        so no DataObserver wake-up is triggered.
        """
        if node_id not in self._state:
            self._state[node_id] = default_value
            self._previous_state[node_id] = default_value
            logger.debug(
                "InformationModel '%s': registered new node '%s' = %r",
                self._module_id, node_id, default_value,
            )

    # ── Introspection ─────────────────────────────────────────────────────────

    @property
    def module_id(self) -> str:
        return self._module_id

    def node_ids(self) -> list[str]:
        return list(self._state.keys())

    def __repr__(self) -> str:
        return (
            f"<InformationModel module_id={self._module_id!r} "
            f"nodes={len(self._state)}>"
        )
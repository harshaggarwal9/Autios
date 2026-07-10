"""
api/dependencies.py
────────────────────
Shared FastAPI dependencies injected across all route modules.

Using Request.app.state instead of module-level globals makes dependencies
test-safe: each test can create a fresh app with its own state rather than
inheriting shared mutable module globals.
"""

from fastapi import Request

from core.subscription.registry import SubscriptionRegistry
from dataset.recorder import DatasetRecorder
from digital_twin.adapters.adapter_manager import AdapterManager
from digital_twin.information_model.registry import ModuleRegistry


def get_subscription_registry(request: Request) -> SubscriptionRegistry:
    return request.app.state.subscription_registry


def get_module_registry(request: Request) -> ModuleRegistry:
    return request.app.state.module_registry


def get_adapter_manager(request: Request) -> AdapterManager:
    return request.app.state.adapter_manager


def get_dataset_recorder(request: Request) -> DatasetRecorder:
    return request.app.state.dataset_recorder
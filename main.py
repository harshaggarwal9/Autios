import logging
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from agents.agent_runner import AgentRunner
from agents.summarization_agent import SummaryType
from api.router import api_router
from command.interface_manager import CommandInterfaceManager
from config.module_loader import load_all_module_configs, load_rule_engines
from config.settings import get_settings
from core.subscription.registry import SubscriptionRegistry
from dataset.recorder import DatasetRecorder
from db.session import get_engine, get_session_factory, init_db
from digital_twin.adapters.adapter_manager import AdapterManager
from digital_twin.data_observer.observer import DataObserverManager
from digital_twin.information_model.registry import ModuleRegistry


# ── Logging setup ──────────────────────────────────────────────────────────────
# Configured before anything else so all startup messages are captured.

def _configure_logging(log_level: str) -> None:
    """
    Configure root logger with a consistent format.

    Uses stdout (not stderr) so Docker / systemd log collectors see
    all output in the same stream regardless of level.
    """
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)-40s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    # Quiet down noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("google").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan handler.

    Everything before `yield` runs at startup; everything after runs at
    shutdown. FastAPI guarantees the shutdown block runs even if startup
    raises, so resources are always cleaned up.
    """
    settings = get_settings()
    _configure_logging(settings.log_level)
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("  LLM4IAS — startup initiated")
    logger.info("  env=%s  log_level=%s", settings.app_env, settings.log_level)
    logger.info("=" * 60)

    # ── Step 1: Database ───────────────────────────────────────────────────────
    logger.info("[1/10] Initialising database engine...")
    init_db(
        settings.database_url,
        echo=settings.is_development,
    )
    session_factory = get_session_factory()
    logger.info(
        "       DB pool ready: %s",
        settings.database_url.rsplit("/", 1)[-1],
    )

    # Store on app.state immediately — dependencies may need these even during
    # subsequent startup steps if they open their own sessions.
    app.state.settings = settings
    app.state.session_factory = session_factory

    # ── Step 2: Module configs ─────────────────────────────────────────────────
    logger.info("[2/10] Loading module YAML configs...")
    module_configs = load_all_module_configs(settings.modules_config_dir)
    app.state.module_configs = module_configs
    logger.info("       Loaded: %s", list(module_configs.keys()))

    # ── Step 3: Rule engines ───────────────────────────────────────────────────
    logger.info("[3/10] Loading DataObserver rule engines...")
    rule_engines = load_rule_engines(settings.modules_config_dir)
    app.state.rule_engines = rule_engines
    logger.info(
        "       Rules: %s",
        {k: v.rule_count() for k, v in rule_engines.items()},
    )

    # ── Step 4: SubscriptionRegistry ──────────────────────────────────────────
    logger.info("[4/10] Loading SubscriptionRegistry...")
    subscription_registry = SubscriptionRegistry()
    async with session_factory() as db:
        await subscription_registry.load(db)
    app.state.subscription_registry = subscription_registry
    logger.info(
        "       Agents with subscriptions: %d",
        len(subscription_registry.all_agent_ids()),
    )

    if not subscription_registry.all_agent_ids():
        logger.warning(
            "       SubscriptionRegistry is empty — no agents have subscriptions. "
            "Run: python scripts/seed_db.py"
        )

    # ── Step 5: ModuleRegistry (InformationModels) ─────────────────────────────
    logger.info("[5/10] Initialising ModuleRegistry (InformationModels)...")
    module_registry = ModuleRegistry()
    async with session_factory() as db:
        await module_registry.initialise(module_configs, db)
        await db.commit()
    app.state.module_registry = module_registry
    logger.info(
        "       Modules: %d  nodes per module: %s",
        len(module_registry.all_module_ids()),
        {
            mid: len(module_registry.get_model(mid).node_ids())
            for mid in module_registry.all_module_ids()
        },
    )

    # ── Step 6: AdapterManager ─────────────────────────────────────────────────
    logger.info("[6/10] Connecting hardware adapters (MockOpcUa)...")
    adapter_manager = AdapterManager()
    await adapter_manager.initialise(module_registry)
    app.state.adapter_manager = adapter_manager
    logger.info(
        "       Adapters connected: %s", adapter_manager.all_module_ids()
    )

    # ── Step 7: CommandInterfaceManager ────────────────────────────────────────
    logger.info("[7/10] Building CommandInterfaces...")
    command_interface_manager = CommandInterfaceManager()
    command_interface_manager.initialise(
        module_registry=module_registry,
        module_configs=module_configs,
        session_factory=session_factory,
    )
    app.state.command_interface_manager = command_interface_manager
    logger.info(
        "       Interfaces: %s  functions per module: %s",
        command_interface_manager.all_module_ids(),
        {
            mid: len(command_interface_manager.get_interface(mid).registered_function_names())
            for mid in command_interface_manager.all_module_ids()
        },
    )

    # ── Step 8: DatasetRecorder ────────────────────────────────────────────────
    logger.info("[8/10] Initialising DatasetRecorder (Phase 6)...")
    dataset_recorder = DatasetRecorder(session_factory=session_factory)
    app.state.dataset_recorder = dataset_recorder
    logger.info("       DatasetRecorder ready — recording enabled.")

    # ── Step 9: DataObserverManager ────────────────────────────────────────────
    logger.info("[9/10] Starting DataObserver background tasks...")
    observer_manager = DataObserverManager()
    observer_manager.start(
        module_registry=module_registry,
        rule_engines=rule_engines,
        session_factory=session_factory,
    )
    app.state.observer_manager = observer_manager
    logger.info(
        "       Observers running: %s", observer_manager.all_module_ids()
    )

    # ── Step 10: AgentRunner ────────────────────────────────────────────────────
    logger.info("[10/10] Starting AgentRunner (Operators + Manager + Summarization)...")
    agent_runner = AgentRunner()
    await agent_runner.start(
        session_factory=session_factory,
        module_configs=module_configs,
        subscription_registry=subscription_registry,
        command_interface_manager=command_interface_manager,
        dataset_recorder=dataset_recorder,
        enable_summarization=settings.enable_summarization,
        summary_types=[SummaryType.PRODUCTION, SummaryType.ERROR],
        summary_interval_seconds=settings.summary_interval_seconds,
    )
    app.state.agent_runner = agent_runner
    logger.info(
        "       Agents running: %d — %s",
        agent_runner.agent_count(),
        agent_runner.all_agent_ids(),
    )

    # ── Startup complete ────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("  LLM4IAS is ready  —  http://localhost:8000/docs")
    logger.info("=" * 60)

    _log_startup_diagnostics(logger, app)

    # ── Yield: application runs ─────────────────────────────────────────────────
    yield

    # ── Shutdown ────────────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("  LLM4IAS — shutdown initiated")
    logger.info("=" * 60)

    # 1. Stop agents — persists cursors and updates DB status to STOPPED
    logger.info("Stopping AgentRunner...")
    await agent_runner.stop()
    logger.info("Agents stopped.")

    # 2. Stop DataObservers
    logger.info("Stopping DataObservers...")
    await observer_manager.stop()
    logger.info("DataObservers stopped.")

    # 3. Persist final InformationModel snapshots
    logger.info("Saving final state snapshots...")
    async with session_factory() as db:
        for module_id in module_registry.all_module_ids():
            await module_registry.save_snapshot(module_id, db)
        await db.commit()
    logger.info("Snapshots saved.")

    # 4. Disconnect adapters
    logger.info("Disconnecting adapters...")
    await adapter_manager.shutdown()
    logger.info("Adapters disconnected.")

    # 5. Dispose DB connection pool
    logger.info("Disposing database connection pool...")
    await get_engine().dispose()
    logger.info("DB pool disposed.")

    logger.info("=" * 60)
    logger.info("  LLM4IAS shutdown complete.")
    logger.info("=" * 60)


# ── Startup diagnostics ────────────────────────────────────────────────────────

def _log_startup_diagnostics(logger: logging.Logger, app: FastAPI) -> None:
    """Log a summary of registered routes and app.state attributes."""
    settings = app.state.settings

    logger.info("── Startup diagnostics ──────────────────────────────")
    logger.info("  App env:           %s", settings.app_env)
    logger.info("  Gemini model:      %s", settings.gemini_model_name)
    logger.info("  Summarization:     %s", settings.enable_summarization)
    logger.info(
        "  Poll interval:     %.1fs", settings.agent_poll_interval_seconds
    )
    logger.info(
        "  Event window size: %d", settings.agent_event_window_size
    )

    routes = [
        f"{list(r.methods)[0]:6} {r.path}"
        for r in app.routes
        if hasattr(r, "methods") and r.methods
    ]
    logger.info("  API routes (%d):", len(routes))
    for route in sorted(routes):
        logger.info("    %s", route)


# ── Exception handlers ─────────────────────────────────────────────────────────

async def _unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    logger = logging.getLogger(__name__)
    logger.exception(
        "Unhandled exception on %s %s: %s",
        request.method, request.url.path, exc,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": (
                "An unexpected error occurred. "
                "Check application logs for details."
            ),
            "path": str(request.url.path),
        },
    )


async def _value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "message": str(exc),
            "path": str(request.url.path),
        },
    )


# ── Application factory ────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    """
    Build and return the configured FastAPI application.

    Called once at module load time to produce `app`. Also usable by
    test fixtures that need a fresh application instance:

        from main import create_app
        app = create_app()
    """
    settings = get_settings()

    app = FastAPI(
        title="LLM4IAS — LLM-Controlled Industrial Automation System",
        description=(
            "Backend implementation of:\n\n"
            "**Xia et al. (IEEE ETFA 2025)**\n"
            "*Control Industrial Automation System with Large Language Models*\n\n"
            "Phases implemented: 1 (Foundation) · 2 (Event Bus) · "
            "3 (Digital Twin) · 4 (LLM + PromptEngine) · "
            "5 (Command Interface) · 6 (Dataset + Evaluation + Summarization)"
        ),
        version="0.1.0",
        lifespan=lifespan,
        # Expose docs only in development — never in production
        docs_url="/docs" if settings.is_development else None,
        redoc_url="/redoc" if settings.is_development else None,
        openapi_url="/openapi.json" if settings.is_development else None,
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    # Permissive in development; restrict origins in production via env config.
    cors_origins = (
        ["*"]
        if settings.is_development
        else settings.cors_allowed_origins
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Exception handlers ────────────────────────────────────────────────────
    app.add_exception_handler(Exception, _unhandled_exception_handler)
    app.add_exception_handler(ValueError, _value_error_handler)

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(api_router, prefix="/api/v1")

    return app


# ── Module-level app instance ──────────────────────────────────────────────────
# uvicorn main:app --reload  resolves this name.

app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.is_development,
        log_level=settings.log_level.lower(),
        # Let uvicorn handle its own log formatting rather than doubling up
        # with our basicConfig — set to False in production
        use_colors=settings.is_development,
    )
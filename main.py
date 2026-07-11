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

def _configure_logging(log_level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)-40s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("google").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    _configure_logging(settings.log_level)
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("  LLM4IAS — startup initiated")
    logger.info("  env=%s  log_level=%s", settings.app_env, settings.log_level)
    logger.info("=" * 60)


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

    app.state.settings = settings
    app.state.session_factory = session_factory


    logger.info("[2/10] Loading module YAML configs...")
    module_configs = load_all_module_configs(settings.modules_config_dir)
    app.state.module_configs = module_configs
    logger.info("       Loaded: %s", list(module_configs.keys()))


    logger.info("[3/10] Loading DataObserver rule engines...")
    rule_engines = load_rule_engines(settings.modules_config_dir)
    app.state.rule_engines = rule_engines
    logger.info(
        "       Rules: %s",
        {k: v.rule_count() for k, v in rule_engines.items()},
    )


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


    logger.info("[6/10] Connecting hardware adapters (MockOpcUa)...")
    adapter_manager = AdapterManager()
    await adapter_manager.initialise(module_registry)
    app.state.adapter_manager = adapter_manager
    logger.info(
        "       Adapters connected: %s", adapter_manager.all_module_ids()
    )


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


    logger.info("[8/10] Initialising DatasetRecorder (Phase 6)...")
    dataset_recorder = DatasetRecorder(session_factory=session_factory)
    app.state.dataset_recorder = dataset_recorder
    logger.info("       DatasetRecorder ready — recording enabled.")


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


    logger.info("=" * 60)
    logger.info("  LLM4IAS is ready  —  http://localhost:8000/docs")
    logger.info("=" * 60)

    _log_startup_diagnostics(logger, app)


    yield


    logger.info("=" * 60)
    logger.info("  LLM4IAS — shutdown initiated")
    logger.info("=" * 60)


    logger.info("Stopping AgentRunner...")
    await agent_runner.stop()
    logger.info("Agents stopped.")


    logger.info("Stopping DataObservers...")
    await observer_manager.stop()
    logger.info("DataObservers stopped.")


    logger.info("Saving final state snapshots...")
    async with session_factory() as db:
        for module_id in module_registry.all_module_ids():
            await module_registry.save_snapshot(module_id, db)
        await db.commit()
    logger.info("Snapshots saved.")


    logger.info("Disconnecting adapters...")
    await adapter_manager.shutdown()
    logger.info("Adapters disconnected.")


    logger.info("Disposing database connection pool...")
    await get_engine().dispose()
    logger.info("DB pool disposed.")

    logger.info("=" * 60)
    logger.info("  LLM4IAS shutdown complete.")
    logger.info("=" * 60)




def _log_startup_diagnostics(logger: logging.Logger, app: FastAPI) -> None:
    
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


async def _unhandled_exception_handler( request: Request, exc: Exception) -> JSONResponse:
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


def create_app() -> FastAPI:


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

        docs_url="/docs" if settings.is_development else None,
        redoc_url="/redoc" if settings.is_development else None,
        openapi_url="/openapi.json" if settings.is_development else None,
    )



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


    app.add_exception_handler(Exception, _unhandled_exception_handler)
    app.add_exception_handler(ValueError, _value_error_handler)


    app.include_router(api_router, prefix="/api/v1")

    return app


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
        use_colors=settings.is_development,
    )

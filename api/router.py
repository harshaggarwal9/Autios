from fastapi import APIRouter

from api.routes.health import router as health_router
from api.routes.events import router as events_router
from api.routes.digital_twin import router as digital_twin_router
from api.routes.agents import router as agents_router
from api.routes.tasks import router as tasks_router
from api.routes.dataset import router as dataset_router
from api.routes.evaluation import router as evaluation_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(events_router)
api_router.include_router(digital_twin_router)
api_router.include_router(agents_router)
api_router.include_router(tasks_router)
api_router.include_router(dataset_router)
api_router.include_router(evaluation_router)
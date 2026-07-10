import asyncio

from config.settings import get_settings
from db.base import Base
from db.session import init_db, get_engine

# Import all models so SQLAlchemy registers them
import db.models.agent
import db.models.automation_module
import db.models.dataset
import db.models.event_log
import db.models.inference_log
import db.models.state_snapshot
import db.models.task


async def main():
    settings = get_settings()

    # Initialize database engine
    init_db(
        database_url=settings.database_url,
        echo=True,
    )

    engine = get_engine()

    print("Creating database schema...")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    print("\n✅ Database schema created successfully!")


if __name__ == "__main__":
    asyncio.run(main())
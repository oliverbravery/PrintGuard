from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import select
import logging
from .config import get_settings
from .hashing import get_password_hash
from .utils import generate_random_string

_LOGGER = logging.getLogger(__name__)
settings = get_settings()

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

class Base(DeclarativeBase):
    pass

async def get_db():
    async with async_session() as session:
        yield session

async def init_db():
    from .db_models import User
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Check if any users exist, if not, create default admin
    async with async_session() as session:
        result = await session.execute(select(User).limit(1))
        if result.scalar_one_or_none() is None:
            # Generate random password
            password = generate_random_string(16)
            hashed_password = get_password_hash(password)
            admin_user = User(
                username="admin",
                hashed_password=hashed_password,
                scopes="admin printer:read printer:write rtc:stream tunnel:manage"
            )
            session.add(admin_user)
            await session.commit()
            print("\n" + "="*50)
            print("INITIAL ADMIN USER CREATED")
            print(f"Username: admin")
            print(f"Password: {password}")
            print("PLEASE COPY THIS PASSWORD AND STORE IT SAFELY!")
            print("="*50 + "\n")
            _LOGGER.info("Default admin user created with random password.")


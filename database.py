import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, Boolean, DateTime

DATABASE_URL = "sqlite+aiosqlite:///./database.db"

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    telegram_id = Column(Integer, primary_key=True, index=True)
    username = Column(String, nullable=True)
    is_vip = Column(Boolean, default=False)
    is_banned = Column(Boolean, default=False)
    ban_reason = Column(String, nullable=True)

class AuthCode(Base):
    __tablename__ = "auth_codes"
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(Integer, nullable=False)
    code = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Ticket(Base):
    __tablename__ = "tickets"
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(Integer, nullable=False)
    message = Column(String, nullable=False)
    admin_response = Column(String, nullable=True)
    status = Column(String, default="open")

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

import datetime
from sqlalchemy import Column, BigInteger, String, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite+aiosqlite:///./rubinov_system.db"

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    telegram_id = Column(BigInteger, primary_key=True)
    username = Column(String(64), nullable=True)
    is_vip = Column(Boolean, default=False)
    is_banned = Column(Boolean, default=False)
    ban_reason = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, ForeignKey("users.telegram_id"))
    message = Column(Text, nullable=False)
    status = Column(String(20), default="open")
    admin_response = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class AuthSession(Base):
    __tablename__ = "auth_sessions"

    token = Column(String(64), primary_key=True)
    telegram_id = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class AuthCode(Base):
    __tablename__ = "auth_codes"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, nullable=False)
    code = Column(String(10), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    is_used = Column(Boolean, default=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

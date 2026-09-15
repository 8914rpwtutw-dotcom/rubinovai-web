import os
import random
import string
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from sqlalchemy import select, func
from database import AsyncSessionLocal, AuthCode, User, Ticket

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_IDS = [7325255913]

if not BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не найден в Environment Variables!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def get_main_keyboard(is_admin: bool = False):
    keyboard = [
        [KeyboardButton(text="🔐 Получить код")],
        [KeyboardButton(text="🎫 Тикеты")]
    ]
    if is_admin:
        keyboard.append([KeyboardButton(text="👥 Пользователи"), KeyboardButton(text="🔍 Найти по ID")])
        keyboard.append([KeyboardButton(text="👑 Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

async def get_or_create_user(session, telegram_id: int, username: str = None):
    stmt = select(User).where(User.telegram_id == telegram_id)
    res = await session.execute(stmt)
    user = res.scalars().first()
    if not user:
        user = User(telegram_id=telegram_id, username=username)
        session.add(user)
        await session.commit()
    return user

@dp.message(Command("start"))
@dp.message(Command("code"))
@dp.message(F.text == "🔐 Получить код")
async def send_auth_code(message: types.Message):
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.username)
        is_admin = message.from_user.id in ADMIN_IDS

        if user.is_banned:
            await message.answer(f"⛔️ Аккаунт заблокирован.\nПричина: {user.ban_reason or 'Не указана'}")
            return

        code = ''.join(random.choices(string.digits, k=6))
        session.add(AuthCode(telegram_id=user.telegram_id, code=code))
        await session.commit()

        vip_str = "⭐ VIP" if user.is_vip else "FREE"
        await message.answer(
            f"🔑 Ваш код авторизации: `{code}`\n\nСтатус: **{vip_str}**", 
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(is_admin)
        )

@dp.message(Command("tickets"))
@dp.message(F.text == "🎫 Тикеты")
async def list_tickets(message: types.Message):
    async with AsyncSessionLocal() as session:
        if message.from_user.id in ADMIN_IDS:
            stmt = select(Ticket).where(Ticket.status == "open")
            tickets = (await session.execute(stmt)).scalars().all()
            if not tickets:
                await message.answer("🎉 Открытых тикетов нет!", reply_markup=get_main_keyboard(True))
                return
            text = "📋 **Открытые тикеты:**\n\n"
            for t in tickets:
                text += f"🔹 **Тикет #{t.id}** (ID `{t.telegram_id}`):\n{t.message}\nОтвет: `/reply {t.id} Текст`\n\n"
            await message.answer(text, parse_mode="Markdown")
        else:
            await message.answer("💬 Отправить обращение администратору:\n`/ticket Текст проблемы`", parse_mode="Markdown")

@dp.message(Command("ticket"))
async def create_ticket(message: types.Message, command: CommandObject):
    if not command.args:
        await message.answer("Формат: `/ticket Текст проблемы`")
        return
    async with AsyncSessionLocal() as session:
        ticket = Ticket(telegram_id=message.from_user.id, message=command.args)
        session.add(ticket)
        await session.commit()
        await message.answer(f"🎫 Тикет #{ticket.id} успешно создан!")

@dp.message(Command("reply"))
async def reply_ticket(message: types.Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS or not command.args: return
    try:
        t_id, ans = command.args.split(maxsplit=1)
        async with AsyncSessionLocal() as session:
            t = (await session.execute(select(Ticket).where(Ticket.id == int(t_id)))).scalars().first()
            if t:
                t.status = "closed"
                t.admin_response = ans
                await session.commit()
                await bot.send_message(t.telegram_id, f"📩 **Ответ на тикет #{t.id}:**\n\n{ans}", parse_mode="Markdown")
                await message.answer("✅ Ответ отправлен!")
    except Exception:
        await message.answer("Ошибка формата. Используй: `/reply <ID> <текст>`")

@dp.message(Command("admin"))
@dp.message(F.text == "👑 Админ-панель")
async def admin_panel(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    async with AsyncSessionLocal() as session:
        total = (await session.execute(select(func.count(User.telegram_id)))).scalar()
        vip = (await session.execute(select(func.count(User.telegram_id)).where(User.is_vip == True))).scalar()
        banned = (await session.execute(select(func.count(User.telegram_id)).where(User.is_banned == True))).scalar()
        await message.answer(f"👑 **Админ-панель**\n\n📊 Всего: `{total}` | VIP: `{vip}` | Забанено: `{banned}`", parse_mode="Markdown")

@dp.message(F.text == "👥 Пользователи")
async def list_users(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    async with AsyncSessionLocal() as session:
        users = (await session.execute(select(User).limit(10))).scalars().all()
        text = "👥 **Последние пользователи:**\n\n"
        for u in users:
            text += f"• ID: `{u.telegram_id}` | VIP: {u.is_vip} | BAN: {u.is_banned}\n"
        await message.answer(text, parse_mode="Markdown")

@dp.message(Command("vip"))
async def give_vip(message: types.Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS or not command.args: return
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, int(command.args.strip()))
        user.is_vip = True
        await session.commit()
        await message.answer(f"⭐ VIP выдан `{user.telegram_id}`")

@dp.message(Command("unvip"))
async def remove_vip(message: types.Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS or not command.args: return
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, int(command.args.strip()))
        user.is_vip = False
        await session.commit()
        await message.answer(f"❌ VIP снят у `{user.telegram_id}`")

@dp.message(Command("ban"))
async def ban_user(message: types.Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS or not command.args: return
    parts = command.args.split(maxsplit=1)
    target_id = int(parts[0])
    reason = parts[1] if len(parts) > 1 else "Нарушение"
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, target_id)
        user.is_banned = True
        user.ban_reason = reason
        await session.commit()
        await message.answer(f"⛔️ Пользователь `{target_id}` заблокирован.")

@dp.message(Command("unban"))
async def unban_user(message: types.Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS or not command.args: return
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, int(command.args.strip()))
        user.is_banned = False
        user.ban_reason = None
        await session.commit()
        await message.answer(f"🟢 Пользователь `{user.telegram_id}` разблокирован.")

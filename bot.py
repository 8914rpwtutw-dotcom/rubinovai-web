import asyncio
import random
import string
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandObject
from sqlalchemy import select
from database import AsyncSessionLocal, AuthCode, User, Ticket, init_db

BOT_TOKEN = "ТВОЙ_ТЕЛЕГРАМ_ТОКЕН"
ADMIN_IDS = [123456789]  # Укажи свой Telegram ID

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

async def get_or_create_user(session, telegram_id: int, username: str = None):
    stmt = select(User).where(User.telegram_id == telegram_id)
    res = await session.execute(stmt)
    user = res.scalars().first()
    if not user:
        user = User(telegram_id=telegram_id, username=username)
        session.add(user)
        await session.commit()
    return user

@dp.message(Command("start", "code"))
async def send_auth_code(message: types.Message):
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.username)
        if user.is_banned:
            await message.answer(
                f"⛔️ Ваш аккаунт заблокирован.\nПричина: {user.ban_reason or 'Не указана'}\n\n"
                f"Чтобы подать апелляцию, используйте команду:\n`/ticket Ваш текст`", 
                parse_mode="Markdown"
            )
            return

        code = ''.join(random.choices(string.digits, k=6))
        session.add(AuthCode(telegram_id=user.telegram_id, code=code))
        await session.commit()

        vip_str = "⭐ VIP" if user.is_vip else "FREE"
        await message.answer(f"🔑 Код входа: `{code}`\nСтатус: **{vip_str}**\n⏱ Код действителен 10 минут.", parse_mode="Markdown")

@dp.message(Command("ticket"))
async def create_ticket(message: types.Message, command: CommandObject):
    if not command.args:
        await message.answer("Использование: `/ticket Опишите вашу проблему`", parse_mode="Markdown")
        return

    async with AsyncSessionLocal() as session:
        ticket = Ticket(telegram_id=message.from_user.id, message=command.args)
        session.add(ticket)
        await session.commit()
        await message.answer(f"🎫 Тикет #{ticket.id} создан! Ожидайте ответа администратора.")

@dp.message(Command("tickets"))
async def list_tickets(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return

    async with AsyncSessionLocal() as session:
        stmt = select(Ticket).where(Ticket.status == "open")
        res = await session.execute(stmt)
        tickets = res.scalars().all()

        if not tickets:
            await message.answer("🎉 Открытых тикетов нет!")
            return

        text = "📋 **Открытые тикеты:**\n\n"
        for t in tickets:
            text += f"🔹 **Тикет #{t.id}** (от ID `{t.telegram_id}`):\n{t.message}\nДля ответа: `/reply {t.id} Ваш ответ`\n\n"
        await message.answer(text, parse_mode="Markdown")

@dp.message(Command("reply"))
async def reply_ticket(message: types.Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS or not command.args: return
    try:
        t_id, ans = command.args.split(maxsplit=1)
        async with AsyncSessionLocal() as session:
            stmt = select(Ticket).where(Ticket.id == int(t_id))
            t = (await session.execute(stmt)).scalars().first()
            if t:
                t.status = "closed"
                t.admin_response = ans
                await session.commit()
                await bot.send_message(t.telegram_id, f"📩 **Ответ на ваш тикет #{t.id}:**\n\n{ans}", parse_mode="Markdown")
                await message.answer(f"✅ Ответ отправлен в тикет #{t.id}")
    except Exception:
        await message.answer("Ошибка. Формат: `/reply <ID_тикета> <текст>`")

@dp.message(Command("vip"))
async def give_vip(message: types.Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS or not command.args: return
    target_id = int(command.args.strip())
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, target_id)
        user.is_vip = True
        await session.commit()
        await message.answer(f"⭐ VIP успешно выдан пользователю `{target_id}`")
        try: await bot.send_message(target_id, "🎉 Вам выдан **VIP-статус**! Теперь вам доступна загрузка файлов на сайте.")
        except Exception: pass

@dp.message(Command("unvip"))
async def remove_vip(message: types.Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS or not command.args: return
    target_id = int(command.args.strip())
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, target_id)
        user.is_vip = False
        await session.commit()
        await message.answer(f"❌ VIP снят у пользователя `{target_id}`")

@dp.message(Command("ban"))
async def ban_user(message: types.Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS or not command.args: return
    parts = command.args.split(maxsplit=1)
    target_id = int(parts[0])
    reason = parts[1] if len(parts) > 1 else "Нарушение правил"

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, target_id)
        user.is_banned = True
        user.ban_reason = reason
        await session.commit()
        await message.answer(f"⛔️ Пользователь `{target_id}` заблокирован.")
        try:
            await bot.send_message(
                target_id, 
                f"⛔️ **Ваш аккаунт был заблокирован!**\nПричина: {reason}\n\nДля разблокировки напишите в тикеты: `/ticket Прошу разбанить...`", 
                parse_mode="Markdown"
            )
        except Exception: pass

@dp.message(Command("unban"))
async def unban_user(message: types.Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS or not command.args: return
    target_id = int(command.args.strip())
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, target_id)
        user.is_banned = False
        user.ban_reason = None
        await session.commit()
        await message.answer(f"🟢 Пользователь `{target_id}` разблокирован.")
        try: await bot.send_message(target_id, "🟢 Ваш аккаунт разблокирован!")
        except Exception: pass

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

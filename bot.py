import asyncio
import random
import string
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from sqlalchemy import select, func
from database import AsyncSessionLocal, AuthCode, User, Ticket, init_db

BOT_TOKEN = "ТВОЙ_ТЕЛЕГРАМ_ТОКЕН"  # Вставьте токен из @BotFather
ADMIN_IDS = [123456789]            # Вставьте ваш Telegram ID (число)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Главная клавиатура с кнопками
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

# Старт и выдача кода авторизации
@dp.message(Command("start"))
@dp.message(Command("code"))
@dp.message(F.text == "🔐 Получить код")
async def send_auth_code(message: types.Message):
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.username)
        is_admin = message.from_user.id in ADMIN_IDS

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
        await message.answer(
            f"🔑 Ваш код для входа на сайт: `{code}`\n\n"
            f"Статус: **{vip_str}**\n"
            f"⏱ Код действителен 10 минут.", 
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(is_admin)
        )

# Кнопка и команда "Тикеты"
@dp.message(Command("tickets"))
@dp.message(F.text == "🎫 Тикеты")
async def list_tickets(message: types.Message):
    async with AsyncSessionLocal() as session:
        if message.from_user.id in ADMIN_IDS:
            stmt = select(Ticket).where(Ticket.status == "open")
            res = await session.execute(stmt)
            tickets = res.scalars().all()

            if not tickets:
                await message.answer("🎉 Открытых тикетов нет!", reply_markup=get_main_keyboard(True))
                return

            text = "📋 **Открытые тикеты пользователей:**\n\n"
            for t in tickets:
                text += f"🔹 **Тикет #{t.id}** (от ID `{t.telegram_id}`):\n{t.message}\nДля ответа напишите: `/reply {t.id} Ваш ответ`\n\n"
            await message.answer(text, parse_mode="Markdown")
        else:
            await message.answer(
                "💬 Напишите вашу проблему с помощью команды:\n`/ticket Текст проблемы`", 
                parse_mode="Markdown",
                reply_markup=get_main_keyboard(False)
            )

# Создание тикета пользователем
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

# Ответ на тикет администратором
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

# Кнопка "Админ-панель"
@dp.message(Command("admin"))
@dp.message(F.text == "👑 Админ-панель")
async def admin_panel(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return

    async with AsyncSessionLocal() as session:
        total_users = (await session.execute(select(func.count(User.telegram_id)))).scalar()
        vip_users = (await session.execute(select(func.count(User.telegram_id)).where(User.is_vip == True))).scalar()
        banned_users = (await session.execute(select(func.count(User.telegram_id)).where(User.is_banned == True))).scalar()

        text = (
            "👑 **Админ-панель Rubinov AI**\n\n"
            f"📊 Всего пользователей: `{total_users}`\n"
            f"⭐ VIP пользователей: `{vip_users}`\n"
            f"⛔️ Заблокировано: `{banned_users}`\n\n"
            "**Команды админа:**\n"
            "• Выдать VIP: `/vip <ID>`\n"
            "• Забрать VIP: `/unvip <ID>`\n"
            "• Забанить: `/ban <ID> <причина>`\n"
            "• Разбанить: `/unban <ID>`"
        )
        await message.answer(text, parse_mode="Markdown")

# Кнопка "Пользователи"
@dp.message(F.text == "👥 Пользователи")
async def list_users(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    async with AsyncSessionLocal() as session:
        stmt = select(User).limit(10)
        users = (await session.execute(stmt)).scalars().all()
        text = "👥 **Последние 10 пользователей:**\n\n"
        for u in users:
            vip = "⭐ VIP" if u.is_vip else "FREE"
            ban = "⛔️ BAN" if u.is_banned else "OK"
            text += f"• ID: `{u.telegram_id}` | @{u.username or 'no_name'} | [{vip}] [{ban}]\n"
        await message.answer(text, parse_mode="Markdown")

# Кнопка "Найти по ID"
@dp.message(F.text == "🔍 Найти по ID")
async def find_user_info(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    await message.answer("Для поиска инфо о пользователе используйте админ-панель или команды `/vip`, `/ban` с нужным Telegram ID.")

# Команды управления VIP и Банами
@dp.message(Command("vip"))
async def give_vip(message: types.Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS or not command.args: return
    target_id = int(command.args.strip())
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, target_id)
        user.is_vip = True
        await session.commit()
        await message.answer(f"⭐ VIP выдан пользователю `{target_id}`")
        try: await bot.send_message(target_id, "🎉 Вам выдан **VIP-статус**!")
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
        try: await bot.send_message(target_id, f"⛔️ Ваш аккаунт заблокирован!\nПричина: {reason}")
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

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

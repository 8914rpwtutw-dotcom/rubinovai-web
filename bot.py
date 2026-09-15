import os
import random
import time
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from database import (
    init_db, check_user_status, set_user_ban, 
    set_user_vip, register_user_if_not_exists, save_ticket, save_auth_code
)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_ID = os.getenv("ADMIN_TELEGRAM_ID", "")

bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None
dp = Dispatcher()

# Главное меню с кнопками как на твоем скриншоте
def get_main_keyboard(is_admin: bool = False):
    keyboard = [
        [KeyboardButton(text="🔑 Получить код"), KeyboardButton(text="🎫 Тикеты")],
    ]
    if is_admin:
        keyboard.append([KeyboardButton(text="👥 Пользователи"), KeyboardButton(text="🔍 Найти по ID")])
        keyboard.append([KeyboardButton(text="👑 Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    init_db()
    tg_id = str(message.from_user.id)
    username = message.from_user.username or "user"
    register_user_if_not_exists(tg_id, username)

    is_admin = (tg_id == str(ADMIN_ID))
    
    await message.answer(
        f"👋 Привет, <b>@{username}</b>!\n\n"
        f"🤖 Добро пожаловать в <b>Rubinov AI</b>.\n"
        f"Нажмите кнопку <b>🔑 Получить код</b>, чтобы войти на сайт.",
        parse_mode="HTML",
        reply_markup=get_main_keyboard(is_admin)
    )

@dp.message(F.text == "🔑 Получить код")
async def btn_get_code(message: types.Message):
    tg_id = str(message.from_user.id)
    status = check_user_status(tg_id)
    if status["is_banned"]:
        await message.answer("⛔ Вы забанены.")
        return

    code = str(random.randint(100000, 999900))
    expires_at = time.time() + 300  # 5 минут
    save_auth_code(tg_id, code, expires_at)
    
    await message.answer(
        f"🔑 Ваш код для входа на сайт:\n\n"
        f"<code>{code}</code>\n\n"
        f"⏰ Действителен 5 минут. Введите его на сайте.",
        parse_mode="HTML"
    )

@dp.message(F.text == "🎫 Тикеты")
async def btn_tickets(message: types.Message):
    await message.answer("💬 Напишите ваше сообщение или вопрос прямо сюда, и поддержка ответит вам!")

@dp.message(F.text == "👑 Админ-панель")
async def btn_admin_panel(message: types.Message):
    tg_id = str(message.from_user.id)
    if tg_id != str(ADMIN_ID):
        return
    await message.answer(
        "👑 <b>Панель администратора:</b>\n\n"
        "Команды управления:\n"
        "• /ban [ID] — заблокировать\n"
        "• /unban [ID] — разблокировать\n"
        "• /vip [ID] — выдать VIP\n"
        "• /unvip [ID] — забрать VIP\n"
        "• /reply [ID] [текст] — ответить на тикет",
        parse_mode="HTML"
    )

# Админ-команды
@dp.message(Command("ban"))
async def cmd_ban(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /ban [telegram_id]")
        return
    target_id = args[1]
    set_user_ban(target_id, 1)
    await bot.send_message(int(target_id), "❌ Вы забанены администратором.")
    await message.answer(f"✅ Пользователь {target_id} забанен.")

@dp.message(Command("unban"))
async def cmd_unban(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /unban [telegram_id]")
        return
    target_id = args[1]
    set_user_ban(target_id, 0)
    await bot.send_message(int(target_id), "✅ Ваш аккаунт разбанен!")
    await message.answer(f"✅ Пользователь {target_id} разбанен.")

@dp.message(Command("vip"))
async def cmd_vip(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /vip [telegram_id]")
        return
    target_id = args[1]
    set_user_vip(target_id, 1)
    await bot.send_message(int(target_id), "⭐ Вам выдан VIP-статус на сайте!")
    await message.answer(f"⭐ VIP выдан пользователю {target_id}.")

@dp.message(Command("unvip"))
async def cmd_unvip(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /unvip [telegram_id]")
        return
    target_id = args[1]
    set_user_vip(target_id, 0)
    await bot.send_message(int(target_id), "ℹ️ Ваш VIP-статус аннулирован.")
    await message.answer(f"ℹ️ VIP снят с пользователя {target_id}.")

@dp.message(Command("reply"))
async def cmd_reply(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
        return
    parts = message.text.split(" ", 2)
    if len(parts) < 3:
        await message.answer("Использование: /reply [telegram_id] [текст]")
        return
    t_id = parts[1]
    reply_text = parts[2]
    await bot.send_message(int(t_id), f"💬 <b>Ответ поддержки:</b>\n{reply_text}", parse_mode="HTML")
    await message.answer("✅ Ответ отправлен.")

# Обработка обычных текстовых сообщений (тикетов) от пользователей
@dp.message()
async def handle_other_messages(message: types.Message):
    if not message.text or message.text.startswith("/"):
        return
    tg_id = str(message.from_user.id)
    username = message.from_user.username or "user"
    
    status = check_user_status(tg_id)
    if status["is_banned"]:
        await message.answer("⛔ Вы забанены.")
        return

    save_ticket(tg_id, message.text, time.time())
    if ADMIN_ID:
        try:
            await bot.send_message(
                int(ADMIN_ID), 
                f"📩 <b>Тикет от @{username} ({tg_id}):</b>\n{message.text}\n\nОтветить: /reply {tg_id} текст",
                parse_mode="HTML"
            )
        except Exception:
            pass
    
    await message.answer("✅ Сообщение передано в поддержку.")

async def handle_telegram_update(update_dict: dict):
    if not bot:
        return {"status": "error"}
    update = types.Update(**update_dict)
    await dp.feed_update(bot, update)
    return {"status": "ok"}

import os
import asyncio
import logging
import urllib.parse
import psycopg2
from typing import Optional

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import (
    ReplyKeyboardMarkup, 
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand
)
from google import genai
from google.genai import types as genai_types

logging.basicConfig(level=logging.INFO)

# --- Инициализация токена и бота ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не установлен в Environment Variables!")

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# --- Настройка PostgreSQL (Neon) ---
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL не настроена в Environment Variables.")
    return psycopg2.connect(DATABASE_URL)

# Ваш Telegram ID из переменных окружения Render
SUPER_ADMIN_TG_ID = int(os.getenv("SUPER_ADMIN_TG_ID", "7325255913")) 

def init_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id BIGINT PRIMARY KEY,
                username TEXT DEFAULT '',
                status TEXT DEFAULT 'free',
                requests_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                message TEXT DEFAULT '',
                status TEXT DEFAULT 'open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        logging.error(f"Ошибка инициализации БД: {e}")

init_db()

# --- Логика работы с Gemini API ---
MODELS = ["gemini-2.0-flash", "gemini-1.5-flash"]
current_key_idx = 0
current_model_idx = 0

def get_api_keys():
    keys = [
        os.getenv("GEMINI_KEY_1"),
        os.getenv("GEMINI_KEY_2"),
        os.getenv("GEMINI_KEY_3"),
        os.getenv("GEMINI_API_KEY")
    ]
    return [k.strip() for k in keys if k and k.strip()]

def get_gemini_response(prompt: str, file_bytes: Optional[bytes] = None, mime_type: Optional[str] = None) -> str:
    global current_key_idx, current_model_idx
    
    lowered = prompt.lower()
    if "нарисуй" in lowered or "draw" in lowered or "сгенерируй" in lowered:
        clean_prompt = prompt.replace("Нарисуй:", "").replace("нарисуй", "").replace("сгенерируй", "").strip()
        if not clean_prompt:
            clean_prompt = "beautiful futuristic neon cyberpunk landscape"
        encoded_prompt = urllib.parse.quote(clean_prompt)
        return f"IMAGE_URL:https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true"

    api_keys = get_api_keys()
    if not api_keys:
        return "❌ Ошибка: API-ключи Gemini не найдены в переменных окружения."

    num_keys = len(api_keys)
    num_models = len(MODELS)
    total_attempts = num_keys * num_models * 2

    contents = []
    if file_bytes and mime_type:
        contents.append(genai_types.Part.from_bytes(data=file_bytes, mime_type=mime_type))
    if prompt:
        contents.append(prompt)

    last_error = "Неизвестная ошибка"

    for _ in range(total_attempts):
        active_key = api_keys[current_key_idx % num_keys]
        active_model = MODELS[current_model_idx % num_models]

        try:
            client = genai.Client(api_key=active_key)
            response = client.models.generate_content(
                model=active_model,
                contents=contents
            )
            if response and response.text:
                return response.text
        except Exception as err:
            last_error = str(err)
            current_model_idx += 1
            if current_model_idx >= num_models:
                current_model_idx = 0
                current_key_idx = (current_key_idx + 1) % num_keys
            continue

    return f"❌ Ошибка генерации ИИ: {last_error}"

# --- Функция получения / создания пользователя по Telegram ID ---
def get_telegram_user(telegram_id: int, username: str = "") -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT telegram_id, username, status, requests_count FROM users WHERE telegram_id = %s", (telegram_id,))
    row = cursor.fetchone()
    
    status = "admin" if (SUPER_ADMIN_TG_ID and telegram_id == SUPER_ADMIN_TG_ID) else (row[2] if row else "free")

    if row:
        if status != row[2]:
            cursor.execute("UPDATE users SET status = %s WHERE telegram_id = %s", (status, telegram_id))
            conn.commit()
        cursor.close()
        conn.close()
        return {"telegram_id": row[0], "username": row[1], "status": status, "requests_count": row[3] or 0}
    
    cursor.execute(
        "INSERT INTO users (telegram_id, username, status) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
        (telegram_id, username, status)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return {"telegram_id": telegram_id, "username": username, "status": status, "requests_count": 0}

# --- Клавиатуры интерфейса ---
def get_main_keyboard(is_admin: bool = False):
    buttons = [
        [KeyboardButton(text="💎 Профиль"), KeyboardButton(text="🎨 Нарисовать картинку")],
        [KeyboardButton(text="💬 Написать в поддержку"), KeyboardButton(text="ℹ️ О сервисе")]
    ]
    if is_admin:
        buttons.append([KeyboardButton(text="👑 Панель Админа")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# --- Хэндлеры команд ---
@dp.message(Command("start"))
async def cmd_start(msg: types.Message):
    user = get_telegram_user(msg.from_user.id, msg.from_user.username or "")
    is_admin = user["status"] == "admin"
    await msg.answer(
        f"✨ **Добро пожаловать в Rubinov AI!**\n\nПривет, **{msg.from_user.first_name}**!\nЯ твой персональный ассистент ИИ.",
        reply_markup=get_main_keyboard(is_admin),
        parse_mode="Markdown"
    )

@dp.message(F.text == "💎 Профиль")
@dp.message(Command("profile"))
async def cmd_profile(msg: types.Message):
    user = get_telegram_user(msg.from_user.id, msg.from_user.username or "")
    await msg.answer(
        f"💎 **ЛИЧНЫЙ КАБИНЕТ RUBINOV AI**\n\n🆔 Telegram ID: `{user['telegram_id']}`\n🏷️ Статус: **{user['status'].upper()}**\n📊 Запросов: `{user['requests_count']}`",
        parse_mode="Markdown"
    )

@dp.message(F.text == "👑 Панель Админа")
@dp.message(Command("admin"))
async def cmd_admin(msg: types.Message):
    user = get_telegram_user(msg.from_user.id, msg.from_user.username or "")
    if user["status"] != "admin":
        await msg.answer("⛔ У вас нет доступа к панеле администратора.")
        return

    text = (
        "👑 **Админ-Панель Rubinov AI**\n\n"
        "Команды управления пользователями:\n"
        "• `/set_vip TELEGRAM_ID` — выдать VIP статус\n"
        "• `/set_free TELEGRAM_ID` — вернуть статус Free\n"
        "• `/ban TELEGRAM_ID` — заблокировать доступ\n"
        "• `/unban TELEGRAM_ID` — разблокировать"
    )
    await msg.answer(text, parse_mode="Markdown")

@dp.message(Command("set_vip"))
async def cmd_set_vip(msg: types.Message):
    user = get_telegram_user(msg.from_user.id, msg.from_user.username or "")
    if user["status"] != "admin": return
    try:
        target_id = int(msg.text.split()[1])
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET status = 'vip' WHERE telegram_id = %s", (target_id,))
        conn.commit()
        cursor.close()
        conn.close()
        await msg.answer(f"✅ Пользователю `{target_id}` выдан **VIP** статус!", parse_mode="Markdown")
    except:
        await msg.answer("⚠️ Использование: `/set_vip TELEGRAM_ID`", parse_mode="Markdown")

@dp.message(Command("ban"))
async def cmd_ban(msg: types.Message):
    user = get_telegram_user(msg.from_user.id, msg.from_user.username or "")
    if user["status"] != "admin": return
    try:
        target_id = int(msg.text.split()[1])
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET status = 'banned' WHERE telegram_id = %s", (target_id,))
        conn.commit()
        cursor.close()
        conn.close()
        await msg.answer(f"🚫 Пользователь `{target_id}` заблокирован.", parse_mode="Markdown")
    except:
        await msg.answer("⚠️ Использование: `/ban TELEGRAM_ID`", parse_mode="Markdown")

@dp.message(Command("unban"))
async def cmd_unban(msg: types.Message):
    user = get_telegram_user(msg.from_user.id, msg.from_user.username or "")
    if user["status"] != "admin": return
    try:
        target_id = int(msg.text.split()[1])
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET status = 'free' WHERE telegram_id = %s", (target_id,))
        conn.commit()
        cursor.close()
        conn.close()
        await msg.answer(f"✅ Пользователь `{target_id}` разблокирован.", parse_mode="Markdown")
    except:
        await msg.answer("⚠️ Использование: `/unban TELEGRAM_ID`", parse_mode="Markdown")

@dp.message(F.text == "🎨 Нарисовать картинку")
async def cmd_draw(msg: types.Message):
    await msg.answer("🎨 Отправьте запрос в формате: `Нарисуй неоновый город`", parse_mode="Markdown")

@dp.message(F.text == "💬 Написать в поддержку")
async def cmd_supp(msg: types.Message):
    await msg.answer("💬 Задайте вопрос, и администрация свяжется с вами!", parse_mode="Markdown")

@dp.message(F.text == "ℹ️ О сервисе")
async def cmd_info(msg: types.Message):
    await msg.answer("🤖 **Rubinov AI** — мультимодальный ИИ ассистент на базе Gemini 2.0 & Pollinations AI.", parse_mode="Markdown")

@dp.message(F.text | F.photo)
async def handle_msg(msg: types.Message):
    user = get_telegram_user(msg.from_user.id, msg.from_user.username or "")
    if user["status"] == "banned":
        await msg.answer("🚫 Ваш аккаунт заблокирован.")
        return

    prompt = msg.text or msg.caption or ""
    file_bytes = None
    mime_type = None

    if msg.photo:
        if user["status"] == "free":
            await msg.answer("🔒 Анализ фото доступен только для VIP пользователей!")
            return
        photo = msg.photo[-1]
        file_info = await bot.get_file(photo.file_id)
        downloaded = await bot.download_file(file_info.file_path)
        file_bytes = downloaded.read()
        mime_type = "image/jpeg"

    status_msg = await msg.answer("🔮 *Rubinov AI думает...*", parse_mode="Markdown")
    resp = get_gemini_response(prompt, file_bytes, mime_type)
    await status_msg.delete()

    if resp.startswith("IMAGE_URL:"):
        img_url = resp.replace("IMAGE_URL:", "")
        await msg.answer_photo(photo=img_url, caption=f"🎨 *Запрос:* {prompt}", parse_mode="Markdown")
    else:
        await msg.answer(resp, parse_mode="Markdown")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

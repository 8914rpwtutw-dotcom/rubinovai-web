import os
import asyncio
import logging
import urllib.parse
import psycopg2
from typing import Optional

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from google import genai
from google.genai import types as genai_types

logging.basicConfig(level=logging.INFO)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не установлен в Environment Variables!")

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL не настроена в Environment Variables.")
    return psycopg2.connect(DATABASE_URL)

def get_user(telegram_id: int, username: str = "") -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT telegram_id, username, status, requests_count, last_reset_date FROM users WHERE telegram_id = %s", (telegram_id,))
    row = cursor.fetchone()
    
    if row:
        cursor.close()
        conn.close()
        return {
            "telegram_id": row[0],
            "username": row[1],
            "status": row[2],
            "requests_count": row[3],
            "last_reset_date": row[4]
        }
    
    cursor.execute(
        "INSERT INTO users (telegram_id, username, status) VALUES (%s, %s, 'free') ON CONFLICT DO NOTHING",
        (telegram_id, username)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return {"telegram_id": telegram_id, "username": username, "status": "free", "requests_count": 0, "last_reset_date": ""}

MODELS = ["gemini-2.0-flash", "gemini-2.0-flash-lite"]
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
        return "⚠️ Ошибка: API-ключи Gemini не найдены в переменные окружения."

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

    return f"⚠️ Ошибка генерации ИИ: {last_error}"

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = get_user(message.from_user.id, message.from_user.username or "")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile"), InlineKeyboardButton(text="💬 Поддержка", callback_data="support_ticket")]
    ])
    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        "Я **Rubinov AI** — твой интеллектуальный ассистент.\n"
        "Задай мне любой вопрос, отправь фото для анализа или напиши «Нарисуй ...», чтобы сгенерировать картинку!",
        reply_markup=kb,
        parse_mode="Markdown"
    )

@dp.message(Command("profile"))
@dp.callback_query(F.data == "profile")
async def cmd_profile(event: types.Message | types.CallbackQuery):
    user = get_user(event.from_user.id, event.from_user.username or "")
    text = (
        f"📊 **Ваш профиль Rubinov AI**\n\n"
        f"🆔 ID: `{user['telegram_id']}`\n"
        f"👑 Статус: **{user['status'].upper()}**\n"
        f"💬 Использовано запросов сегодня: **{user['requests_count']}**"
    )
    if isinstance(event, types.CallbackQuery):
        await event.message.answer(text, parse_mode="Markdown")
        await event.answer()
    else:
        await event.answer(text, parse_mode="Markdown")

@dp.message(F.text | F.photo)
async def handle_ai_message(message: types.Message):
    user = get_user(message.from_user.id, message.from_user.username or "")
    
    if user["status"] == "banned":
        await message.answer("🚫 Ваш аккаунт заблокирован администратором.")
        return

    prompt = message.text or message.caption or ""
    file_bytes = None
    mime_type = None

    if message.photo:
        if user["status"] == "free":
            await message.answer("🔒 Отправка файлов и фото доступна только VIP и Admin пользователям!")
            return
        photo = message.photo[-1]
        file_info = await bot.get_file(photo.file_id)
        downloaded = await bot.download_file(file_info.file_path)
        file_bytes = downloaded.read()
        mime_type = "image/jpeg"

    status_msg = await message.answer("⏳ Rubinov AI думает...")

    response = get_gemini_response(prompt, file_bytes, mime_type)

    await status_msg.delete()

    if response.startswith("IMAGE_URL:"):
        img_url = response.replace("IMAGE_URL:", "")
        await message.answer_photo(photo=img_url, caption=f"🎨 Изображение по запросу: *{prompt}*", parse_mode="Markdown")
    else:
        await message.answer(response, parse_mode="Markdown")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

import os
import time
import random
import httpx
from database import (
    init_db, check_user_status, set_user_ban, 
    set_user_vip, register_user_if_not_exists, save_ticket, save_auth_code
)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_ID = os.getenv("ADMIN_TELEGRAM_ID", "")

async def send_telegram_message(chat_id: str, text: str):
    if not BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
        except Exception:
            pass

async def handle_telegram_update(update: dict):
    init_db()
    if "message" in update:
        msg = update["message"]
        chat = msg.get("chat", {})
        tg_id = str(chat.get("id"))
        username = chat.get("username", "user")
        text = msg.get("text", "")

        register_user_if_not_exists(tg_id, username)

        if text == "/start":
            await send_telegram_message(
                tg_id, 
                f"👋 Привет, <b>@{username}</b>!\n\n"
                f"🤖 Добро пожаловать в <b>Rubinov AI</b>.\n"
                f"Чтобы войти на сайт, отправьте команду <b>/login</b> — вы получите одноразовый код, действительный 5 минут."
            )
            return {"status": "ok"}

        if text == "/login":
            code = str(random.randint(100000, 999900))
            expires_at = time.time() + 300  # 5 минут
            save_auth_code(tg_id, code, expires_at)
            
            await send_telegram_message(
                tg_id, 
                f"🔑 Ваш код для входа на сайт:\n\n"
                f"<code>{code}</code>\n\n"
                f"⏰ Действителен 5 минут. Введите его на сайте."
            )
            return {"status": "ok"}

        # Команды администратора
        if tg_id == str(ADMIN_ID):
            if text.startswith("/ban "):
                target_id = text.split(" ")[1]
                set_user_ban(target_id, 1)
                await send_telegram_message(target_id, "❌ Вы забанены администратором.")
                await send_telegram_message(tg_id, f"✅ Пользователь {target_id} забанен.")
                return {"status": "ok"}

            elif text.startswith("/unban "):
                target_id = text.split(" ")[1]
                set_user_ban(target_id, 0)
                await send_telegram_message(target_id, "✅ Ваш аккаунт разбанен!")
                await send_telegram_message(tg_id, f"✅ Пользователь {target_id} разбанен.")
                return {"status": "ok"}

            elif text.startswith("/vip "):
                target_id = text.split(" ")[1]
                set_user_vip(target_id, 1)
                await send_telegram_message(target_id, "⭐ Вам выдан VIP-статус на сайте!")
                await send_telegram_message(tg_id, f"⭐ VIP выдан пользователю {target_id}.")
                return {"status": "ok"}

            elif text.startswith("/unvip "):
                target_id = text.split(" ")[1]
                set_user_vip(target_id, 0)
                await send_telegram_message(target_id, "ℹ️ Ваш VIP-статус аннулирован.")
                await send_telegram_message(tg_id, f"ℹ️ VIP снят с пользователя {target_id}.")
                return {"status": "ok"}
            
            elif text.startswith("/reply "):
                parts = text.split(" ", 2)
                if len(parts) >= 3:
                    t_id = parts[1]
                    reply_text = parts[2]
                    await send_telegram_message(t_id, f"💬 <b>Ответ поддержки:</b>\n{reply_text}")
                    await send_telegram_message(tg_id, "✅ Ответ отправлен.")
                    return {"status": "ok"}

        status = check_user_status(tg_id)
        if status["is_banned"]:
            await send_telegram_message(tg_id, "⛔ Вы забанены.")
            return {"status": "ok"}

        if text and not text.startswith("/"):
            save_ticket(tg_id, text, time.time())
            if ADMIN_ID:
                await send_telegram_message(str(ADMIN_ID), f"📩 <b>Тикет от @{username} ({tg_id}):</b>\n{text}\n\nОтветить: /reply {tg_id} текст")
            await send_telegram_message(tg_id, "✅ Сообщение передано в поддержку.")

    return {"status": "ok"}

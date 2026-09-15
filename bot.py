import os
import time
import httpx
from database import (
    init_db, check_user_status, set_user_ban, 
    set_user_vip, register_user_if_not_exists, save_ticket
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

        # Команды администратора
        if tg_id == str(ADMIN_ID):
            if text.startswith("/ban "):
                target_id = text.split(" ")[1]
                set_user_ban(target_id, 1)
                await send_telegram_message(target_id, "❌ Вы были забанены администратором. Доступ к сайту закрыт. Обратитесь в тикет.")
                await send_telegram_message(tg_id, f"✅ Пользователь {target_id} успешно забанен.")
                return {"status": "ok"}

            elif text.startswith("/unban "):
                target_id = text.split(" ")[1]
                set_user_ban(target_id, 0)
                await send_telegram_message(target_id, "✅ Ваш аккаунт разбанен! Снова добро пожаловать в систему.")
                await send_telegram_message(tg_id, f"✅ Пользователь {target_id} разбанен.")
                return {"status": "ok"}

            elif text.startswith("/vip "):
                target_id = text.split(" ")[1]
                set_user_vip(target_id, 1)
                await send_telegram_message(target_id, "⭐ Вам выдан VIP-статус! На сайте активированы все функции и золотой шильдик.")
                await send_telegram_message(tg_id, f"⭐ VIP успешно выдан пользователю {target_id}.")
                return {"status": "ok"}

            elif text.startswith("/unvip "):
                target_id = text.split(" ")[1]
                set_user_vip(target_id, 0)
                await send_telegram_message(target_id, "ℹ️ Ваш VIP-статус был аннулирован.")
                await send_telegram_message(tg_id, f"ℹ️ VIP снят с пользователя {target_id}.")
                return {"status": "ok"}
            
            elif text.startswith("/reply "):
                parts = text.split(" ", 2)
                if len(parts) >= 3:
                    t_id = parts[1]
                    reply_text = parts[2]
                    await send_telegram_message(t_id, f"💬 <b>Ответ поддержки:</b>\n{reply_text}")
                    await send_telegram_message(tg_id, "✅ Ответ отправлен пользователю.")
                    return {"status": "ok"}

        # Проверка бана обычного пользователя
        status = check_user_status(tg_id)
        if status["is_banned"]:
            await send_telegram_message(tg_id, "⛔ Вы забанены. Обратитесь в тикет поддержки.")
            return {"status": "ok"}

        # Обработка тикетов
        if text and not text.startswith("/"):
            save_ticket(tg_id, text, time.time())
            
            if ADMIN_ID:
                await send_telegram_message(str(ADMIN_ID), f"📩 <b>Тикет от @{username} (ID: {tg_id}):</b>\n{text}\n\nОтветить: /reply {tg_id} текст")
            
            await send_telegram_message(tg_id, "✅ Ваше сообщение передано в поддержку. Ожидайте ответа!")

    return {"status": "ok"}

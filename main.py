import os
import time
import sqlite3
import random
import string
from typing import Optional
from fastapi import FastAPI, HTTPException, File, Form, UploadFile, Request, Response, Cookie
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from google import genai
from google.genai import types
from google.genai.errors import APIError
import requests

# --- НАСТРОЙКА БАЗЫ ДАННЫХ ---
DB_NAME = "database.sqlite"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            is_vip INTEGER DEFAULT 0,
            is_banned INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS auth_codes (
            code TEXT PRIMARY KEY,
            telegram_id INTEGER,
            is_used INTEGER DEFAULT 0,
            expires_at REAL
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_user_db(telegram_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT telegram_id, username, first_name, is_vip, is_banned FROM users WHERE telegram_id = ?", (telegram_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"telegram_id": row[0], "username": row[1], "first_name": row[2], "is_vip": bool(row[3]), "is_banned": bool(row[4])}
    return None

def upsert_user_db(telegram_id: int, username: str, first_name: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (telegram_id, username, first_name) VALUES (?, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name
    """, (telegram_id, username, first_name))
    conn.commit()
    conn.close()

def set_vip_db(telegram_id: int, status: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_vip = ? WHERE telegram_id = ?", (status, telegram_id))
    conn.commit()
    conn.close()

def set_ban_db(telegram_id: int, status: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_banned = ? WHERE telegram_id = ?", (status, telegram_id))
    conn.commit()
    conn.close()

def create_auth_code() -> str:
    code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    expires_at = time.time() + 60  # Жвет ровно 1 минуту
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM auth_codes WHERE expires_at < ?", (time.time(),))
    cursor.execute("INSERT OR REPLACE INTO auth_codes (code, telegram_id, is_used, expires_at) VALUES (?, NULL, 0, ?)", (code, expires_at))
    conn.commit()
    conn.close()
    return code

def activate_code_manual(code: str, telegram_id: int, username: str, first_name: str):
    upsert_user_db(telegram_id, username, first_name)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT is_used, expires_at FROM auth_codes WHERE code = ?", (code,))
    row = cursor.fetchone()
    if row:
        is_used, expires_at = row
        if time.time() > expires_at:
            conn.close()
            return "expired"
        if is_used == 0:
            cursor.execute("UPDATE auth_codes SET telegram_id = ?, is_used = 1 WHERE code = ?", (telegram_id, code))
            conn.commit()
            conn.close()
            return "success"
        else:
            conn.close()
            return "already_used"
    conn.close()
    return "not_found"


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

MODELS = ["gemini-2.5-flash", "gemini-3.1-flash-lite", "gemini-2.5-pro"]
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

def get_bot_token():
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

def get_bot_username():
    return os.getenv("TELEGRAM_BOT_USERNAME", "rubinov_ai_bot").strip()

def send_telegram_message(chat_id: int, text: str):
    token = get_bot_token()
    if not token:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})
    except Exception:
        pass

def get_gemini_client(api_key: str):
    return genai.Client(api_key=api_key)

def get_gemini_response(prompt: str, file_bytes: Optional[bytes] = None, mime_type: Optional[str] = None) -> str:
    global current_key_idx, current_model_idx
    
    lowered = prompt.lower()
    if "нарисуй" in lowered or "draw" in lowered or "сгенерируй" in lowered:
        clean_prompt = prompt.replace("Нарисуй:", "").replace("нарисуй", "").replace("сгенерируй", "").strip()
        if not clean_prompt:
            clean_prompt = "beautiful futuristic neon cyberpunk landscape"
        
        import urllib.parse
        encoded_prompt = urllib.parse.quote(clean_prompt)
        img_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true"
        
        return f"""Вот ваше сгенерированное изображение по запросу: *"{clean_prompt}"*

<div style="margin-top:14px;">
    <img src="{img_url}" alt="{clean_prompt}" style="max-width:100%; border-radius:16px; display:block; margin-bottom:12px; box-shadow: 0 12px 40px rgba(99, 102, 241, 0.2); border: 1px solid rgba(255,255,255,0.08);" />
    <a href="{img_url}" target="_blank" download="rubinov_ai.jpg" style="display:inline-flex; align-items: center; gap: 8px; background: linear-gradient(135deg, #6366f1, #a855f7); color:#fff; padding:9px 18px; border-radius:12px; font-size:12px; text-decoration:none; font-weight:600; box-shadow: 0 4px 20px rgba(99, 102, 241, 0.35); transition: all 0.2s ease;">📥 Скачать в высоком разрешении</a>
</div>"""

    api_keys = get_api_keys()
    if not api_keys:
        raise HTTPException(status_code=500, detail="API-ключи не найдены в Environment Variables.")

    num_keys = len(api_keys)
    num_models = len(MODELS)
    total_attempts = num_keys * num_models * 2

    contents = []
    if file_bytes and mime_type:
        contents.append(types.Part.from_bytes(data=file_bytes, mime_type=mime_type))
    if prompt:
        contents.append(prompt)

    for attempt in range(total_attempts):
        active_key = api_keys[current_key_idx % num_keys]
        active_model = MODELS[current_model_idx % num_models]

        try:
            client = get_gemini_client(active_key)
            response = client.models.generate_content(model=active_model, contents=contents)
            return response.text
        except APIError as e:
            if e.code in [503, 429] or "RESOURCE_EXHAUSTED" in str(e) or "UNAVAILABLE" in str(e):
                current_model_idx += 1
                if current_model_idx >= num_models:
                    current_model_idx = 0
                    current_key_idx = (current_key_idx + 1) % num_keys
                time.sleep(0.5)
                continue
            else:
                break
        except Exception:
            break

    raise HTTPException(status_code=500, detail="Сервис ИИ перегружен. Повторите попытку.")

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.post("/api/telegram/webhook")
async def telegram_webhook(req: Request):
    data = await req.json()
    if "message" in data:
        msg = data["message"]
        chat_id = msg["chat"]["id"]
        user = msg.get("from", {})
        user_id = user.get("id")
        username = user.get("username", "")
        first_name = user.get("first_name", "User")
        text = msg.get("text", "").strip()

        upsert_user_db(user_id, username, first_name)

        if text.startswith("/start"):
            parts = text.split()
            if len(parts) > 1 and parts[1].startswith("auth_"):
                auth_code = parts[1].replace("auth_", "").strip()
                # Если перешли по глубокой ссылке, тоже активируем
                res_status = activate_code_manual(auth_code, user_id, username, first_name)
                if res_status == "success":
                    send_telegram_message(chat_id, f"✅ *Авторизация успешна!*\n\nПривет, *{first_name}*! Можете вернуться на сайт.")
                elif res_status == "expired":
                    send_telegram_message(chat_id, "⚠️ Этот код просрочен (прошла 1 минута). Запросите новый на сайте.")
                else:
                    send_telegram_message(chat_id, "⚠️ Код недействителен или уже использован.")
            else:
                send_telegram_message(
                    chat_id, 
                    f"Привет, *{first_name}*! 👋\nЧтобы войти на сайт, запросите код на странице входа, и отправьте его сюда или введите прямо на сайте.\n\nТвой Telegram ID: `{user_id}`"
                )
        elif len(text) == 6 and text.isalnum():
            # Если пользователь написал боту сам код вручную
            res_status = activate_code_manual(text.upper(), user_id, username, first_name)
            if res_status == "success":
                send_telegram_message(chat_id, f"✅ *Код {text.upper()} успешно подтвержден!*\n\nПривет, *{first_name}*! Обновите страницу сайта — вы вошли.")
            elif res_status == "expired":
                send_telegram_message(chat_id, "⚠️ Этот код уже просрочен (прошла 1 минута).")
            else:
                send_telegram_message(chat_id, "⚠️ Неверный код или он уже был использован.")
        elif text.startswith("/vip "):
            try:
                target_id = int(text.split()[1])
                set_vip_db(target_id, 1)
                send_telegram_message(chat_id, f"⭐ Пользователю `{target_id}` выдан VIP статус!")
                send_telegram_message(target_id, "🎉 Поздравляем! Администратор выдал вам **VIP статус**!")
            except Exception:
                send_telegram_message(chat_id, "Использование: `/vip ID`")
        elif text.startswith("/unvip "):
            try:
                target_id = int(text.split()[1])
                set_vip_db(target_id, 0)
                send_telegram_message(chat_id, f"🔒 С пользователя `{target_id}` снят VIP статус.")
                send_telegram_message(target_id, "ℹ️ Ваш VIP статус был снят.")
            except Exception:
                send_telegram_message(chat_id, "Использование: `/unvip ID`")
        elif text.startswith("/ban "):
            try:
                target_id = int(text.split()[1])
                set_ban_db(target_id, 1)
                send_telegram_message(chat_id, f"⛔ Пользователь `{target_id}` заблокирован.")
                send_telegram_message(target_id, "🚫 Вы заблокированы администратором.")
            except Exception:
                send_telegram_message(chat_id, "Использование: `/ban ID`")
        elif text.startswith("/unban "):
            try:
                target_id = int(text.split()[1])
                set_ban_db(target_id, 0)
                send_telegram_message(chat_id, f"✅ Пользователь `{target_id}` разблокирован.")
                send_telegram_message(target_id, "✨ Ваш аккаунт разблокирован!")
            except Exception:
                send_telegram_message(chat_id, "Использование: `/unban ID`")

    return {"ok": True}

@app.get("/api/auth/start-code")
def api_start_code():
    code = create_auth_code()
    bot_uname = get_bot_username()
    bot_url = f"https://t.me/{bot_uname}"
    return {"code": code, "bot_url": bot_url}

@app.post("/api/auth/verify-code")
def api_verify_code(code: str = Form(...), response: Response = None):
    code_clean = code.strip().upper()
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT telegram_id, is_used, expires_at FROM auth_codes WHERE code = ?", (code_clean,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return {"status": "not_found"}
    
    telegram_id, is_used, expires_at = row
    if time.time() > expires_at:
        return {"status": "expired"}
    
    if is_used == 1 and telegram_id:
        user = get_user_db(telegram_id)
        if user and user["is_banned"]:
            return {"status": "banned"}
        
        resp = Response(content='{"status": "success"}', media_type="application/json")
        resp.set_cookie(key="tg_user_id", value=str(telegram_id), httponly=True, max_age=30*86400)
        return resp

    return {"status": "pending"}

@app.get("/api/user/status")
def get_user_status(tg_user_id: Optional[str] = Cookie(None)):
    if not tg_user_id:
        return {"logged_in": False}
    user = get_user_db(int(tg_user_id))
    if not user:
        return {"logged_in": False}
    if user["is_banned"]:
        return {"logged_in": True, "banned": True}
    return {
        "logged_in": True,
        "telegram_id": user["telegram_id"],
        "first_name": user["first_name"],
        "username": user["username"],
        "is_vip": user["is_vip"]
    }

@app.post("/api/chat")
async def chat_endpoint(
    prompt: str = Form(""),
    file: Optional[UploadFile] = File(None),
    tg_user_id: Optional[str] = Cookie(None)
):
    if not tg_user_id:
        raise HTTPException(status_code=401, detail="Требуется авторизация через Telegram")
    
    user = get_user_db(int(tg_user_id))
    if not user or user["is_banned"]:
        raise HTTPException(status_code=403, detail="Ваш аккаунт заблокирован.")
    
    if file and not user["is_vip"]:
        raise HTTPException(status_code=403, detail="Отправка файлов доступна только VIP пользователям.")

    if not prompt.strip() and not file:
        raise HTTPException(status_code=400, detail="Запрос или файл обязателен")
    
    file_bytes = await file.read() if file else None
    mime_type = file.content_type if file else None

    answer = get_gemini_response(prompt, file_bytes, mime_type)
    return {"response": answer}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <title>Rubinov AI</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <style>
        :root {
            --bg-main: #040508;
            --bg-sidebar: rgba(10, 12, 18, 0.65);
            --card-bg: rgba(18, 21, 31, 0.5);
            --border-color: rgba(255, 255, 255, 0.05);
            --border-hover: rgba(168, 85, 247, 0.25);
            --accent-gradient: linear-gradient(135deg, #6366f1 0%, #a855f7 100%);
            --vip-gradient: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
            --cancel-bg: rgba(248, 113, 113, 0.1);
            --cancel-border: rgba(248, 113, 113, 0.3);
            --cancel-color: #f87171;
            --text-main: #f1f5f9;
            --text-muted: #94a3b8;
            --user-msg-bg: linear-gradient(135deg, rgba(99, 102, 241, 0.16) 0%, rgba(168, 85, 247, 0.14) 100%);
            --bot-msg-bg: rgba(15, 18, 26, 0.65);
            --scrollbar-thumb: rgba(255, 255, 255, 0.08);
        }

        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', -apple-system, sans-serif; -webkit-tap-highlight-color: transparent; }
        html, body { height: 100%; height: 100dvh; overflow: hidden; background: var(--bg-main); color: var(--text-main); }
        body { display: flex; position: relative; }

        body::before {
            content: ''; position: fixed; top: -15vh; left: -15vw; width: 55vw; height: 55vh;
            background: radial-gradient(circle, rgba(99, 102, 241, 0.07) 0%, transparent 80%);
            z-index: 0; pointer-events: none; filter: blur(80px);
        }

        ::-webkit-scrollbar { width: 5px; height: 5px; }
        ::-webkit-scrollbar-thumb { background: var(--scrollbar-thumb); border-radius: 20px; }

        #sidebar-overlay {
            display: none; position: fixed; top: 0; left: 0; width: 100vw; height: 100dvh;
            background: rgba(4, 5, 8, 0.7); backdrop-filter: blur(6px); z-index: 40; opacity: 0; transition: opacity 0.3s ease;
        }
        #sidebar-overlay.active { display: block; opacity: 1; }

        #sidebar { 
            width: 280px; min-width: 280px; background: var(--bg-sidebar); backdrop-filter: blur(24px);
            border-right: 1px solid var(--border-color); display: flex; flex-direction: column; padding: 20px 14px; z-index: 50; height: 100dvh;
            transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1), margin-left 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            box-shadow: 15px 0 40px rgba(0, 0, 0, 0.4);
        }
        body.sidebar-collapsed #sidebar { margin-left: -280px; }

        .brand { display: flex; align-items: center; gap: 12px; margin-bottom: 22px; padding: 0 4px; }
        .brand-logo-svg { width: 32px; height: 32px; flex-shrink: 0; }
        .brand h2 { font-size: 15px; font-weight: 700; color: #ffffff; display: flex; align-items: center; gap: 6px; }
        .brand span { font-size: 10px; color: var(--text-muted); font-weight: 500; display: block; }
        
        .vip-badge { background: var(--vip-gradient); color: #fff; font-size: 8px; font-weight: 800; padding: 2px 5px; border-radius: 4px; display: none; }
        body.is-vip .vip-badge { display: inline-block; }

        .auth-box { background: rgba(255,255,255,0.02); border: 1px solid var(--border-color); border-radius: 12px; padding: 12px; margin-bottom: 14px; display: flex; flex-direction: column; gap: 8px; }
        .auth-box span { font-size: 11px; color: var(--text-muted); text-align: center; }
        
        .btn-telegram-auth {
            background: #229ed9; color: #fff; border: none; padding: 8px 12px; border-radius: 10px; font-size: 11.5px; font-weight: 600; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 6px; text-decoration: none; transition: 0.2s;
        }
        .btn-telegram-auth:hover { background: #1f8ad2; }

        .auth-input-row { display: flex; gap: 6px; margin-top: 4px; }
        .auth-input { flex: 1; background: rgba(0,0,0,0.3); border: 1px solid var(--border-color); border-radius: 8px; color: #fff; padding: 6px 8px; font-size: 12px; text-align: center; text-transform: uppercase; outline: none; }
        .auth-input:focus { border-color: #a855f7; }
        .btn-auth-submit { background: var(--accent-gradient); color: #fff; border: none; padding: 6px 12px; border-radius: 8px; font-size: 11.5px; font-weight: 600; cursor: pointer; }

        .btn-new-chat { 
            background: var(--accent-gradient); color: #ffffff; border: none; padding: 11px 16px; 
            border-radius: 14px; font-size: 12px; font-weight: 600; cursor: pointer; display: flex; align-items: center; gap: 9px; 
            margin-bottom: 18px; transition: all 0.25s ease; box-shadow: 0 4px 20px rgba(99, 102, 241, 0.3);
        }

        .chats-header { display: flex; justify-content: space-between; font-size: 10px; color: var(--text-muted); font-weight: 700; margin-bottom: 8px; padding: 0 4px; text-transform: uppercase; }
        #chats-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; padding-right: 2px; }
        .chat-item { 
            background: rgba(255, 255, 255, 0.015); border: 1px solid var(--border-color); border-radius: 12px; padding: 10px 12px; 
            font-size: 12px; color: #cbd5e1; display: flex; justify-content: space-between; align-items: center; cursor: pointer; transition: 0.2s;
        }
        .chat-item.active { background: rgba(168, 85, 247, 0.1); border-color: rgba(168, 85, 247, 0.35); color: #ffffff; }

        .sidebar-footer { font-size: 11px; color: var(--text-muted); display: flex; align-items: center; justify-content: space-between; margin-top: auto; padding-top: 14px; border-top: 1px solid var(--border-color); }
        .status-info { display: flex; align-items: center; gap: 8px; }
        .status-dot { width: 7px; height: 7px; background: #a855f7; border-radius: 50%; }

        #main { flex: 1; display: flex; flex-direction: column; background: var(--bg-main); position: relative; height: 100dvh; overflow: hidden; }
        #chat-header { height: 60px; min-height: 60px; border-bottom: 1px solid var(--border-color); display: flex; align-items: center; justify-content: space-between; padding: 0 24px; background: rgba(4, 5, 8, 0.5); backdrop-filter: blur(16px); z-index: 10; }
        .header-left { display: flex; align-items: center; gap: 14px; }
        .menu-toggle { background: rgba(255, 255, 255, 0.02); border: 1px solid var(--border-color); color: #ffffff; border-radius: 12px; padding: 8px; cursor: pointer; }
        #chat-header h3 { font-size: 14px; font-weight: 600; color: #ffffff; }

        #chat-container { flex: 1; overflow-y: auto; padding: 24px 24px 140px 24px; display: flex; flex-direction: column; gap: 22px; max-width: 900px; width: 100%; margin: 0 auto; position: relative; z-index: 2; }
        
        .welcome-screen { position: absolute; top: 45%; left: 50%; transform: translate(-50%, -50%); text-align: center; width: 90%; max-width: 480px; display: flex; flex-direction: column; align-items: center; gap: 16px; }
        .welcome-avatar-glow { padding: 20px; border-radius: 28px; background: rgba(168, 85, 247, 0.04); border: 1px solid rgba(168, 85, 247, 0.15); }
        .welcome-avatar-svg { width: 60px; height: 60px; }
        .welcome-screen h1 { font-size: 24px; font-weight: 700; color: #ffffff; }
        .welcome-screen p { font-size: 13.5px; color: var(--text-muted); }

        .msg-row { display: flex; flex-direction: column; width: 100%; }
        .msg-row.user-row { align-items: flex-end; }
        .msg-row.bot-row { align-items: flex-start; }

        .msg-user { background: var(--user-msg-bg); color: #ffffff; border: 1px solid rgba(168, 85, 247, 0.22); border-radius: 18px 18px 4px 18px; padding: 13px 18px; font-size: 13.5px; max-width: 85%; }
        .msg-bot { background: var(--bot-msg-bg); border: 1px solid var(--border-color); color: #e2e8f0; border-radius: 18px 18px 18px 4px; padding: 18px 22px; font-size: 13.5px; max-width: 90%; }
        .msg-bot strong { color: #ffffff; font-weight: 700; }
        .file-preview-tag { display: inline-flex; align-items: center; gap: 6px; background: rgba(168, 85, 247, 0.15); padding: 5px 10px; border-radius: 8px; font-size: 11px; margin-bottom: 8px; color: #d8b4fe; }

        .loader-box { display: flex; align-items: center; gap: 12px; background: var(--bot-msg-bg); border: 1px solid var(--border-color); border-radius: 18px; padding: 14px 20px; font-size: 13.5px; color: var(--text-muted); }
        .spinner { width: 16px; height: 16px; border: 2px solid rgba(168,85,247,0.2); border-top-color: #a855f7; border-radius: 50%; animation: spin 0.8s linear infinite; }
        @keyframes spin { to { transform: rotate(360deg); } }

        #input-wrapper { position: absolute; bottom: 0; left: 0; right: 0; padding: 16px 24px; background: linear-gradient(180deg, rgba(4,5,8,0) 0%, var(--bg-main) 80%); z-index: 20; }
        #input-container { max-width: 900px; margin: 0 auto; background: rgba(13, 16, 24, 0.8); backdrop-filter: blur(24px); border: 1px solid rgba(168, 85, 247, 0.18); border-radius: 20px; padding: 8px 12px; display: flex; flex-direction: column; gap: 8px; }
        #file-info-bar { display: none; align-items: center; justify-content: space-between; background: rgba(168, 85, 247, 0.12); padding: 6px 12px; border-radius: 10px; font-size: 11.5px; color: #d8b4fe; }
        .input-row { display: flex; gap: 8px; align-items: center; width: 100%; }
        .mini-btn { background: rgba(255,255,255,0.02); border: 1px solid var(--border-color); color: var(--text-muted); padding: 10px; border-radius: 12px; cursor: pointer; transition: 0.2s; }
        #prompt-input { flex: 1; background: transparent; border: none; color: #ffffff; font-size: 14px; outline: none; padding: 6px 4px; }
        .btn-action { background: var(--accent-gradient); color: #ffffff; border: none; border-radius: 12px; padding: 11px 20px; font-size: 12.5px; font-weight: 600; cursor: pointer; min-width: 100px; }
        .btn-action.cancel-mode { background: var(--cancel-bg); border: 1px solid var(--cancel-border); color: var(--cancel-color); }

        #ban-overlay { display: none; position: fixed; top: 0; left: 0; width: 100vw; height: 100dvh; background: rgba(4, 5, 8, 0.95); backdrop-filter: blur(20px); z-index: 100; flex-direction: column; align-items: center; justify-content: center; text-align: center; padding: 24px; }
        #ban-overlay h2 { color: #f87171; font-size: 26px; margin-bottom: 10px; }
        #ban-overlay p { color: var(--text-muted); font-size: 14px; max-width: 400px; }

        @media (max-width: 768px) {
            #sidebar { position: fixed; top: 0; left: 0; margin-left: 0 !important; transform: translateX(-100%); }
            #sidebar.mobile-open { transform: translateX(0); }
        }
    </style>
</head>
<body>
    <div id="sidebar-overlay" onclick="toggleSidebar()"></div>
    <div id="ban-overlay">
        <h2>🚫 Доступ ограничен</h2>
        <p>Ваш аккаунт был заблокирован администратором.</p>
    </div>

    <div id="sidebar">
        <div class="brand">
            <svg class="brand-logo-svg" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M50 10 L85 35 L50 90 L15 35 Z" stroke="#ff4b4b" stroke-width="4" fill="none" />
                <circle cx="50" cy="48" r="14" fill="#ff4b4b" opacity="0.25" />
                <path d="M42 45 Q46 40 50 45 Q54 40 58 45 Q60 52 50 56 Q40 52 42 45 Z" stroke="#ffffff" stroke-width="2.5" fill="none" />
            </svg>
            <div>
                <h2>Rubinov AI <span class="vip-badge">VIP</span></h2>
                <span id="user-display-status">Не авторизован</span>
            </div>
        </div>

        <div id="auth-section" class="auth-box">
            <span>Вход через Telegram (код живет 1 мин):</span>
            <a href="#" id="tg-auth-link" class="btn-telegram-auth" target="_blank">🤖 Открыть бота</a>
            <div style="font-size: 11px; color: #a855f7; text-align: center;" id="auth-code-display">Нажмите кнопку, получите код в боте</div>
            <div class="auth-input-row">
                <input type="text" id="auth-code-input" class="auth-input" placeholder="Код (6 симв)" maxlength="6">
                <button class="btn-auth-submit" onclick="submitAuthCode()">Ввести</button>
            </div>
            <span id="auth-error-hint" style="font-size: 10px; color: #f87171; text-align: center; display:none;"></span>
        </div>

        <button class="btn-new-chat" onclick="createNewChat()">+ Новый диалог</button>
        <div class="chats-header"><span>Чаты (<span id="chat-count">1</span>/5)</span></div>
        <div id="chats-list"></div>

        <div class="sidebar-footer">
            <div class="status-info"><span class="status-dot"></span><span id="plan-text">Free план</span></div>
            <span id="user-id-text" style="font-size: 10px;"></span>
        </div>
    </div>

    <div id="main">
        <div id="chat-header">
            <div class="header-left">
                <button class="menu-toggle" onclick="toggleSidebar()">☰</button>
                <h3 id="current-chat-title">Чаты</h3>
            </div>
        </div>

        <div id="chat-container"></div>

        <div id="input-wrapper">
            <div id="input-container">
                <div id="file-info-bar">
                    <span id="file-name-text">Файл прикреплен</span>
                    <button onclick="removeSelectedFile()" style="background:none;border:none;color:#f87171;cursor:pointer;">✕</button>
                </div>
                <div class="input-row">
                    <input type="file" id="file-input" style="display: none;" onchange="handleFileSelect(event)" />
                    <button class="mini-btn" onclick="triggerFileButton()" title="Файл (VIP)">📎</button>
                    <button class="mini-btn" onclick="triggerImageGenerationPrompt()" title="Картинка">🎨</button>
                    <input type="text" id="prompt-input" placeholder="Введите сообщение..." onkeydown="handleKeyPress(event)" />
                    <button class="btn-action" id="action-btn" onclick="handleActionButton()">Отправить</button>
                </div>
            </div>
        </div>
    </div>

    <script>
        let chats = JSON.parse(localStorage.getItem('rubinov_chats_v3') || '[]');
        let currentChatId = localStorage.getItem('rubinov_active_chat_v3') || null;
        let selectedFile = null;
        let activeController = null;
        let isGenerating = false;
        let isVip = false;
        let isLogged = false;

        async function checkUserStatus() {
            try {
                const res = await fetch('/api/user/status');
                const data = await res.json();
                if (data.logged_in) {
                    if (data.banned) {
                        document.getElementById('ban-overlay').style.display = 'flex';
                        return;
                    }
                    isLogged = true;
                    isVip = data.is_vip;
                    document.getElementById('auth-section').style.display = 'none';
                    document.getElementById('user-display-status').textContent = data.first_name;
                    document.getElementById('user-id-text').textContent = `ID: ${data.telegram_id}`;
                    if (isVip) {
                        document.body.classList.add('is-vip');
                        document.getElementById('plan-text').textContent = 'VIP План ⭐';
                    }
                } else {
                    // Автоматически запрашиваем новый код при загрузке, если не авторизован
                    fetchNewAuthCode();
                }
            } catch(e) { console.error(e); }
        }

        async function fetchNewAuthCode() {
            try {
                const res = await fetch('/api/auth/start-code');
                const data = await res.json();
                document.getElementById('tg-auth-link').href = data.bot_url;
                document.getElementById('auth-code-display').innerHTML = `Ваш код: <b style="color:#fff; font-size:13px; letter-spacing:1px;">${data.code}</b>`;
            } catch(e) { console.error(e); }
        }

        async function submitAuthCode() {
            const codeInput = document.getElementById('auth-code-input');
            const code = codeInput.value.trim();
            const hint = document.getElementById('auth-error-hint');
            hint.style.display = 'none';

            if (!code || code.length !== 6) {
                hint.textContent = 'Введите 6-значный код';
                hint.style.display = 'block';
                return;
            }

            try {
                const formData = new FormData();
                formData.append('code', code);
                const res = await fetch('/api/auth/verify-code', { method: 'POST', body: formData });
                const data = await res.json();

                if (data.status === 'success') {
                    location.reload();
                } else if (data.status === 'expired') {
                    hint.textContent = '⚠️ Код истек (прошла 1 минута). Обновите страницу.';
                    hint.style.display = 'block';
                } else if (data.status === 'banned') {
                    document.getElementById('ban-overlay').style.display = 'flex';
                } else {
                    hint.textContent = '⚠️ Неверный код или бот еще не подтвердил его.';
                    hint.style.display = 'block';
                }
            } catch(e) {
                hint.textContent = 'Ошибка соединения';
                hint.style.display = 'block';
            }
        }

        checkUserStatus();

        if (chats.length === 0) {
            const initialChat = { id: Date.now().toString(), name: 'Новый чат 1', messages: [] };
            chats.push(initialChat);
            currentChatId = initialChat.id;
            saveState();
        } else if (!currentChatId || !chats.find(c => c.id === currentChatId)) {
            currentChatId = chats[0].id;
        }

        function saveState() {
            localStorage.setItem('rubinov_chats_v3', JSON.stringify(chats));
            localStorage.setItem('rubinov_active_chat_v3', currentChatId);
            renderChats();
        }

        function toggleSidebar() {
            if (window.innerWidth <= 768) {
                document.getElementById('sidebar').classList.toggle('mobile-open');
                document.getElementById('sidebar-overlay').classList.toggle('active');
            } else {
                document.body.classList.toggle('sidebar-collapsed');
            }
        }

        function renderChats() {
            const list = document.getElementById('chats-list');
            list.innerHTML = '';
            document.getElementById('chat-count').textContent = chats.length;
            chats.forEach(chat => {
                const item = document.createElement('div');
                item.className = `chat-item ${chat.id === currentChatId ? 'active' : ''}`;
                item.onclick = () => switchChat(chat.id);
                item.innerHTML = `<span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:160px;">${escapeHtml(chat.name)}</span>`;
                list.appendChild(item);
            });
            const active = chats.find(c => c.id === currentChatId);
            if (active) {
                document.getElementById('current-chat-title').textContent = active.name;
                renderMessages(active.messages);
            }
        }

        function switchChat(id) {
            if (activeController) activeController.abort();
            currentChatId = id;
            setGeneratingState(false);
            saveState();
            if (window.innerWidth <= 768) toggleSidebar();
        }

        function createNewChat() {
            if (chats.length >= 5) return;
            if (activeController) activeController.abort();
            const newChat = { id: Date.now().toString(), name: `Новый чат ${chats.length + 1}`, messages: [] };
            chats.push(newChat);
            currentChatId = newChat.id;
            setGeneratingState(false);
            saveState();
        }

        function triggerImageGenerationPrompt() {
            document.getElementById('prompt-input').value = "Нарисуй: ";
            document.getElementById('prompt-input').focus();
        }

        function triggerFileButton() {
            if (!isLogged) { alert("Сначала авторизуйтесь!"); return; }
            if (!isVip) { alert("⭐ Файлы доступны только VIP пользователям!"); return; }
            document.getElementById('file-input').click();
        }

        function renderMessages(messages) {
            const chatContainer = document.getElementById('chat-container');
            chatContainer.innerHTML = '';
            if (messages.length === 0) {
                chatContainer.innerHTML = `
                    <div class="welcome-screen">
                        <div class="welcome-avatar-glow">
                            <svg class="welcome-avatar-svg" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
                                <path d="M50 10 L85 35 L50 90 L15 35 Z" stroke="#ff4b4b" stroke-width="4" fill="none" />
                                <circle cx="50" cy="48" r="14" fill="#ff4b4b" opacity="0.25" />
                                <path d="M42 45 Q46 40 50 45 Q54 40 58 45 Q60 52 50 56 Q40 52 42 45 Z" stroke="#ffffff" stroke-width="2.5" fill="none" />
                            </svg>
                        </div>
                        <h1>Rubinov AI</h1>
                        <p>Чем я могу помочь вам сегодня?</p>
                    </div>`;
                return;
            }
            messages.forEach(msg => {
                const row = document.createElement('div');
                row.className = `msg-row ${msg.role === 'user' ? 'user-row' : 'bot-row'}`;
                const box = document.createElement('div');
                box.className = msg.role === 'user' ? 'msg-user' : 'msg-bot';
                if (msg.role === 'user') {
                    box.innerHTML = (msg.file ? `<div class="file-preview-tag">📷 ${escapeHtml(msg.file)}</div><br>` : '') + escapeHtml(msg.text);
                } else {
                    box.innerHTML = msg.text.includes('<img') ? msg.text : marked.parse(msg.text);
                }
                row.appendChild(box);
                chatContainer.appendChild(row);
            });
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }

        function handleFileSelect(event) {
            const file = event.target.files[0];
            if (file) {
                selectedFile = file;
                document.getElementById('file-name-text').textContent = `📷 ${file.name}`;
                document.getElementById('file-info-bar').style.display = 'flex';
            }
        }

        function removeSelectedFile() {
            selectedFile = null;
            document.getElementById('file-input').value = '';
            document.getElementById('file-info-bar').style.display = 'none';
        }

        function handleKeyPress(e) { if (e.key === 'Enter') handleActionButton(); }

        function setGeneratingState(generating) {
            isGenerating = generating;
            const btn = document.getElementById('action-btn');
            const inp = document.getElementById('prompt-input');
            if (generating) {
                btn.textContent = 'Отменить';
                btn.className = 'btn-action cancel-mode';
                inp.disabled = true;
            } else {
                btn.textContent = 'Отправить';
                btn.className = 'btn-action';
                inp.disabled = false;
                inp.focus();
            }
        }

        function handleActionButton() {
            if (isGenerating) {
                if (activeController) activeController.abort();
                setGeneratingState(false);
            } else {
                sendMessage();
            }
        }

        async function sendMessage() {
            if (!isLogged) { alert("Сначала войдите через Telegram в боковой панели!"); return; }
            const input = document.getElementById('prompt-input');
            const text = input.value.trim();
            if (!text && !selectedFile) return;

            const activeChat = chats.find(c => c.id === currentChatId);
            activeChat.messages.push({ role: 'user', text: text, file: selectedFile ? selectedFile.name : null });
            if (activeChat.messages.length === 1 && text) activeChat.name = text.slice(0, 18) + '...';
            renderMessages(activeChat.messages);

            const formData = new FormData();
            formData.append('prompt', text);
            if (selectedFile) formData.append('file', selectedFile);

            input.value = '';
            removeSelectedFile();
            setGeneratingState(true);

            const chatContainer = document.getElementById('chat-container');
            const botRow = document.createElement('div');
            botRow.className = 'msg-row bot-row';
            botRow.id = 'temp-loader-row';
            botRow.innerHTML = `<div class="loader-box"><div class="spinner"></div><span>Думаю...</span></div>`;
            chatContainer.appendChild(botRow);
            chatContainer.scrollTop = chatContainer.scrollHeight;

            activeController = new AbortController();
            try {
                const res = await fetch('/api/chat', { method: 'POST', body: formData, signal: activeController.signal });
                const data = await res.json();
                document.getElementById('temp-loader-row')?.remove();
                setGeneratingState(false);
                if (res.ok) {
                    activeChat.messages.push({ role: 'bot', text: data.response });
                } else {
                    if (res.status === 403) { document.getElementById('ban-overlay').style.display = 'flex'; return; }
                    activeChat.messages.push({ role: 'bot', text: 'Ошибка: ' + data.detail });
                }
            } catch (e) {
                if (e.name === 'AbortError') return;
                document.getElementById('temp-loader-row')?.remove();
                setGeneratingState(false);
                activeChat.messages.push({ role: 'bot', text: 'Ошибка соединения.' });
            }
            saveState();
        }

        function escapeHtml(text) {
            return (text || '').replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        }

        renderChats();
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def get_chat_ui():
    return HTML_TEMPLATE

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)

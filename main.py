import os
import time
import sqlite3
import hmac
import hashlib
import requests
from typing import Optional
from fastapi import FastAPI, HTTPException, File, Form, UploadFile, Query, Request, Response, Cookie
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from google import genai
from google.genai import types
from google.genai.errors import APIError

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

def send_telegram_message(chat_id: int, text: str):
    token = get_bot_token()
    if not token:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})
    except Exception:
        pass

def verify_telegram_auth(query_params: dict) -> Optional[dict]:
    bot_token = get_bot_token()
    if not bot_token:
        return {"id": query_params.get("id"), "first_name": query_params.get("first_name", "User"), "username": query_params.get("username", "")}
    
    check_hash = query_params.get("hash")
    if not check_hash:
        return None
    
    data_check_arr = []
    for k, v in sorted(query_params.items()):
        if k != "hash" and v is not None:
            data_check_arr.append(f"{k}={v}")
    data_check_string = "\n".join(data_check_arr)
    
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    h = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    
    if h == check_hash:
        return {
            "id": int(query_params["id"]),
            "first_name": query_params.get("first_name", ""),
            "username": query_params.get("username", "")
        }
    return None

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
    <a href="{img_url}" target="_blank" download="rubinov_ai.jpg" style="display:inline-flex; align-items: center; gap: 8px; background: linear-gradient(135deg, #6366f1, #a855f7); color:#fff; padding:9px 18px; border-radius:12px; font-size:12px; text-decoration:none; font-weight:600; box-shadow: 0 4px 20px rgba(99, 102, 241, 0.35);">📥 Скачать в высоком разрешении</a>
</div>"""

    api_keys = get_api_keys()
    if not api_keys:
        raise HTTPException(status_code=500, detail="API-ключи не найдены.")

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
            client = genai.Client(api_key=active_key)
            response = client.models.generate_content(model=active_model, contents=contents)
            return response.text
        except APIError as e:
            if e.code in [503, 429] or "RESOURCE_EXHAUSTED" in str(e) or "UNAVAILABLE" in str(e):
                current_model_idx +=1
                if current_model_idx >= num_models:
                    current_model_idx = 0
                    current_key_idx = (current_key_idx + 1) % num_keys
                time.sleep(0.5)
                continue
            else:
                break
        except Exception:
            break

    raise HTTPException(status_code=500, detail="Сервис ИИ перегружен.")

@app.get("/health")
def health_check():
    return {"status": "ok"}

# --- TELEGRAM WEBHOOK БОТА ---
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

        # Регистрируем или обновляем пользователя в базе при любом сообщении/команде
        upsert_user_db(user_id, username, first_name)

        if text.startswith("/start"):
            send_telegram_message(
                chat_id, 
                f"Привет, *{first_name}*! 👋\nДобро пожаловать в **Rubinov AI**.\n\nТвой Telegram ID: `{user_id}`\nИспользуй сайт для общения с нейросетью!"
            )
        elif text.startswith("/vip "):
            # Команда админа для выдачи VIP: /vip <telegram_id>
            try:
                target_id = int(text.split()[1])
                set_vip_db(target_id, 1)
                send_telegram_message(chat_id, f"⭐ Пользователю `{target_id}` успешно выдан VIP статус!")
                send_telegram_message(target_id, "🎉 Поздравляем! Администратор выдал вам **VIP статус** на сайте!")
            except Exception:
                send_telegram_message(chat_id, "Ошибка. Использование: `/vip ID`")
        elif text.startswith("/unvip "):
            try:
                target_id = int(text.split()[1])
                set_vip_db(target_id, 0)
                send_telegram_message(chat_id, f"🔒 У пользователя `{target_id}` снят VIP статус.")
            except Exception:
                send_telegram_message(chat_id, "Ошибка. Использование: `/unvip ID`")
        elif text.startswith("/ban "):
            try:
                target_id = int(text.split()[1])
                set_ban_db(target_id, 1)
                send_telegram_message(chat_id, f"⛔ Пользователь `{target_id}` заблокирован.")
            except Exception:
                send_telegram_message(chat_id, "Ошибка. Использование: `/ban ID`")
        else:
            send_telegram_message(chat_id, "Я получил ваше сообщение. Переходите на сайт для работы с ИИ!")

    return {"ok": True}

@app.get("/api/auth/telegram")
def telegram_auth_callback(
    id: int,
    first_name: str,
    username: Optional[str] = "",
    auth_date: int = 0,
    hash: str = ""
):
    params = {"id": id, "first_name": first_name, "username": username, "auth_date": auth_date, "hash": hash}
    user_data = verify_telegram_auth(params)
    if not user_data:
        raise HTTPException(status_code=400, detail="Ошибка авторизации Telegram")
    
    upsert_user_db(id, username, first_name)
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="tg_user_id", value=str(id), httponly=True, max_age=30*86400)
    return response

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
        raise HTTPException(status_code=403, detail="Доступ заблокирован")
    if file and not user["is_vip"]:
        raise HTTPException(status_code=403, detail="Отправка файлов доступна только VIP пользователям")

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
            --border-color: rgba(255, 255, 255, 0.05);
            --accent-gradient: linear-gradient(135deg, #6366f1 0%, #a855f7 100%);
            --vip-gradient: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
            --text-main: #f1f5f9;
            --text-muted: #94a3b8;
            --user-msg-bg: linear-gradient(135deg, rgba(99, 102, 241, 0.16) 0%, rgba(168, 85, 247, 0.14) 100%);
            --bot-msg-bg: rgba(15, 18, 26, 0.65);
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', sans-serif; -webkit-tap-highlight-color: transparent; }
        html, body { height: 100%; height: 100dvh; overflow: hidden; background: var(--bg-main); color: var(--text-main); display: flex; }

        #sidebar { 
            width: 280px; min-width: 280px; background: var(--bg-sidebar); backdrop-filter: blur(24px);
            border-right: 1px solid var(--border-color); display: flex; flex-direction: column; padding: 20px 14px; z-index: 50;
            height: 100dvh; transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1), margin-left 0.3s ease;
        }
        body.sidebar-collapsed #sidebar { margin-left: -280px; }

        .brand { display: flex; align-items: center; gap: 12px; margin-bottom: 22px; padding: 0 4px; }
        .brand-logo-svg { width: 32px; height: 32px; flex-shrink: 0; }
        .brand h2 { font-size: 15px; font-weight: 700; color: #fff; display: flex; align-items: center; gap: 8px; }
        .brand span { font-size: 10px; color: var(--text-muted); font-weight: 500; display: block; }
        .vip-badge { background: var(--vip-gradient); color: #fff; font-size: 9px; font-weight: 800; padding: 2px 6px; border-radius: 6px; display: none; }
        body.is-vip .vip-badge { display: inline-block; }

        .btn-new-chat { background: var(--accent-gradient); color: #fff; border: none; padding: 11px 16px; border-radius: 14px; font-size: 12px; font-weight: 600; cursor: pointer; margin-bottom: 18px; }
        .chats-header { font-size: 10px; color: var(--text-muted); font-weight: 700; margin-bottom: 8px; padding: 0 4px; text-transform: uppercase; }
        #chats-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; }
        .chat-item { background: rgba(255,255,255,0.015); border: 1px solid var(--border-color); border-radius: 12px; padding: 10px 12px; font-size: 12px; color: #cbd5e1; cursor: pointer; }
        .chat-item.active { background: rgba(168, 85, 247, 0.1); border-color: rgba(168, 85, 247, 0.35); color: #fff; }

        .sidebar-footer { font-size: 11px; color: var(--text-muted); display: flex; flex-direction: column; gap: 8px; margin-top: auto; padding-top: 14px; border-top: 1px solid var(--border-color); }
        .login-box { display: flex; flex-direction: column; align-items: center; gap: 8px; background: rgba(255,255,255,0.02); padding: 12px; border-radius: 12px; border: 1px solid var(--border-color); text-align: center; }
        
        #main { flex: 1; display: flex; flex-direction: column; background: var(--bg-main); position: relative; height: 100dvh; overflow: hidden; }
        #chat-header { height: 60px; min-height: 60px; border-bottom: 1px solid var(--border-color); display: flex; align-items: center; justify-content: space-between; padding: 0 24px; background: rgba(4, 5, 8, 0.5); backdrop-filter: blur(16px); z-index: 10; }
        .menu-toggle { background: rgba(255,255,255,0.02); border: 1px solid var(--border-color); color: #fff; border-radius: 12px; padding: 8px; cursor: pointer; }

        #chat-container { flex: 1; overflow-y: auto; padding: 24px 24px 140px 24px; display: flex; flex-direction: column; gap: 22px; max-width: 900px; width: 100%; margin: 0 auto; }
        .msg-row { display: flex; flex-direction: column; width: 100%; }
        .msg-row.user-row { align-items: flex-end; }
        .msg-row.bot-row { align-items: flex-start; }
        .msg-user { background: var(--user-msg-bg); color: #fff; border: 1px solid rgba(168, 85, 247, 0.22); border-radius: 18px 18px 4px 18px; padding: 13px 18px; font-size: 13.5px; max-width: 85%; }
        .msg-bot { background: var(--bot-msg-bg); border: 1px solid var(--border-color); color: #e2e8f0; border-radius: 18px 18px 18px 4px; padding: 18px 22px; font-size: 13.5px; max-width: 90%; }
        
        .loader-box { display: flex; align-items: center; gap: 12px; background: var(--bot-msg-bg); border: 1px solid var(--border-color); border-radius: 18px; padding: 14px 20px; color: var(--text-muted); }
        .spinner { width: 16px; height: 16px; border: 2px solid rgba(168,85,247,0.2); border-top-color: #a855f7; border-radius: 50%; animation: spin 0.8s linear infinite; }
        @keyframes spin { to { transform: rotate(360deg); } }

        #input-wrapper { position: absolute; bottom: 0; left: 0; right: 0; padding: 16px 24px; background: linear-gradient(180deg, transparent 0%, var(--bg-main) 60%); z-index: 20; }
        #input-container { max-width: 900px; margin: 0 auto; background: rgba(13, 16, 24, 0.9); border: 1px solid rgba(168, 85, 247, 0.18); border-radius: 20px; padding: 8px 12px; display: flex; gap: 8px; align-items: center; }
        #prompt-input { flex: 1; background: transparent; border: none; color: #fff; font-size: 14px; outline: none; padding: 6px; }
        .btn-action { background: var(--accent-gradient); color: #fff; border: none; border-radius: 12px; padding: 11px 20px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
    </style>
</head>
<body>
    <div id="sidebar">
        <div class="brand">
            <svg class="brand-logo-svg" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M50 10 L85 35 L50 90 L15 35 Z" stroke="#ff4b4b" stroke-width="4" fill="none" />
                <circle cx="50" cy="48" r="14" fill="#ff4b4b" opacity="0.25" />
            </svg>
            <div>
                <h2>Rubinov AI <span class="vip-badge">VIP</span></h2>
                <span id="user-display-name">Не авторизован</span>
            </div>
        </div>

        <button class="btn-new-chat" onclick="createNewChat()">Новый диалог</button>
        <div class="chats-header"><span>Чаты</span></div>
        <div id="chats-list"></div>

        <div class="sidebar-footer">
            <div id="auth-container" class="login-box">
                <span style="font-size:11px; color:var(--text-muted);">Войдите через Telegram:</span>
                <div id="telegram-login-container"></div>
            </div>
            <span id="footer-status-text" style="font-size: 10px; text-align: center;">Статус: Free</span>
        </div>
    </div>

    <div id="main">
        <div id="chat-header">
            <button class="menu-toggle" onclick="document.body.classList.toggle('sidebar-collapsed')">☰</button>
            <h3 id="current-chat-title">Чаты</h3>
        </div>
        <div id="chat-container"></div>
        <div id="input-wrapper">
            <div id="input-container">
                <input type="text" id="prompt-input" placeholder="Введите сообщение..." onkeydown="if(event.key==='Enter') sendMessage()" />
                <button class="btn-action" onclick="sendMessage()">Отправить</button>
            </div>
        </div>
    </div>

    <script>
        let isVip = false;
        let isLogged = false;
        let chats = JSON.parse(localStorage.getItem('rubinov_chats') || '[]');
        let currentChatId = localStorage.getItem('rubinov_active_chat') || null;

        async function checkAuth() {
            try {
                const res = await fetch('/api/user/status');
                const data = await res.json();
                if (data.logged_in) {
                    if (data.banned) { alert("Ваш аккаунт заблокирован."); return; }
                    isLogged = true;
                    isVip = data.is_vip;
                    document.getElementById('user-display-name').textContent = data.first_name;
                    document.getElementById('auth-container').style.display = 'none';
                    document.getElementById('footer-status-text').textContent = isVip ? 'VIP Статус Активен ⭐' : 'Free План';
                    if (isVip) document.body.classList.add('is-vip');
                } else {
                    renderTelegramButton();
                }
            } catch(e) { console.error(e); }
        }

        function renderTelegramButton() {
            const container = document.getElementById('telegram-login-container');
            container.innerHTML = '';
            const script = document.createElement('script');
            script.async = true;
            script.src = "https://telegram.org/js/telegram-widget.js?22";
            script.setAttribute('data-telegram-login', 'rubinov_ai_bot'); // Укажите имя вашего бота без @
            script.setAttribute('data-size', 'medium');
            script.setAttribute('data-auth-url', window.location.origin + '/api/auth/telegram');
            script.setAttribute('data-request-access', 'write');
            container.appendChild(script);
        }

        document.addEventListener("DOMContentLoaded", checkAuth);

        if (chats.length === 0) {
            const initial = { id: Date.now().toString(), name: 'Новый чат', messages: [] };
            chats.push(initial);
            currentChatId = initial.id;
        }

        function saveState() {
            localStorage.setItem('rubinov_chats', JSON.stringify(chats));
            localStorage.setItem('rubinov_active_chat', currentChatId);
            renderChats();
        }

        function renderChats() {
            const list = document.getElementById('chats-list');
            list.innerHTML = '';
            chats.forEach(chat => {
                const item = document.createElement('div');
                item.className = `chat-item ${chat.id === currentChatId ? 'active' : ''}`;
                item.onclick = () => { currentChatId = chat.id; saveState(); };
                item.innerHTML = `<span>${chat.name}</span>`;
                list.appendChild(item);
            });
            const active = chats.find(c => c.id === currentChatId);
            if (active) {
                document.getElementById('current-chat-title').textContent = active.name;
                renderMessages(active.messages);
            }
        }

        function createNewChat() {
            const newC = { id: Date.now().toString(), name: `Чат ${chats.length + 1}`, messages: [] };
            chats.push(newC);
            currentChatId = newC.id;
            saveState();
        }

        function renderMessages(msgs) {
            const container = document.getElementById('chat-container');
            container.innerHTML = '';
            msgs.forEach(m => {
                const row = document.createElement('div');
                row.className = `msg-row ${m.role === 'user' ? 'user-row' : 'bot-row'}`;
                const box = document.createElement('div');
                box.className = m.role === 'user' ? 'msg-user' : 'msg-bot';
                box.innerHTML = m.role === 'user' ? escapeHtml(m.text) : marked.parse(m.text);
                row.appendChild(box);
                container.appendChild(row);
            });
            container.scrollTop = container.scrollHeight;
        }

        async function sendMessage() {
            if (!isLogged) { alert("Пожалуйста, войдите через Telegram в сайдбаре слева!"); return; }
            const input = document.getElementById('prompt-input');
            const text = input.value.trim();
            if (!text) return;

            const active = chats.find(c => c.id === currentChatId);
            active.messages.push({ role: 'user', text: text });
            input.value = '';
            renderMessages(active.messages);

            const formData = new FormData();
            formData.append('prompt', text);

            const container = document.getElementById('chat-container');
            const loaderRow = document.createElement('div');
            loaderRow.className = 'msg-row bot-row';
            loaderRow.id = 'loader';
            loaderRow.innerHTML = `<div class="loader-box"><div class="spinner"></div><span>Думаю...</span></div>`;
            container.appendChild(loaderRow);
            container.scrollTop = container.scrollHeight;

            try {
                const res = await fetch('/api/chat', { method: 'POST', body: formData });
                const data = await res.json();
                document.getElementById('loader')?.remove();
                if (res.ok) {
                    active.messages.push({ role: 'bot', text: data.response });
                } else {
                    active.messages.push({ role: 'bot', text: 'Ошибка: ' + data.detail });
                }
            } catch(e) {
                document.getElementById('loader')?.remove();
                active.messages.push({ role: 'bot', text: 'Ошибка соединения с сервером.' });
            }
            saveState();
        }

        function escapeHtml(t) { return (t||'').replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
        renderChats();
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def get_index():
    return HTML_TEMPLATE

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)

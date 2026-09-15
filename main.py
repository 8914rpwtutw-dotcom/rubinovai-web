import os
import time
import sqlite3
import random
import string
from typing import Optional
from fastapi import FastAPI, HTTPException, File, Form, UploadFile, Request, Response, Cookie
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from google import genai
from google.genai import types
from google.genai.errors import APIError
import requests

# ==========================================
# 1. БАЗА ДАННЫХ И МОДЕЛИ
# ==========================================
DB_NAME = "database.sqlite"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Таблица пользователей
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
    
    # Таблица для одноразовых кодов авторизации
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS auth_codes (
            code TEXT PRIMARY KEY,
            telegram_id INTEGER,
            username TEXT,
            first_name TEXT,
            expires_at REAL
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_user_db(telegram_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT telegram_id, username, first_name, is_vip, is_banned FROM users WHERE telegram_id = ?", 
        (telegram_id,)
    )
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            "telegram_id": row[0], 
            "username": row[1], 
            "first_name": row[2], 
            "is_vip": bool(row[3]), 
            "is_banned": bool(row[4])
        }
    return None

def save_user_db(telegram_id: int, username: str, first_name: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (telegram_id, username, first_name) 
        VALUES (?, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET 
            username = excluded.username, 
            first_name = excluded.first_name
    """, (telegram_id, username, first_name))
    conn.commit()
    conn.close()

def generate_telegram_code(telegram_id: int, username: str, first_name: str) -> str:
    code = "".join(random.choices(string.digits, k=6))
    expires_at = time.time() + 300  # Срок действия 5 минут
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # Удаляем старые просроченные коды
    cursor.execute("DELETE FROM auth_codes WHERE expires_at < ?", (time.time(),))
    cursor.execute("""
        INSERT OR REPLACE INTO auth_codes (code, telegram_id, username, first_name, expires_at) 
        VALUES (?, ?, ?, ?, ?)
    """, (code, telegram_id, username, first_name, expires_at))
    conn.commit()
    conn.close()
    return code

# ==========================================
# 2. FASTAPI И КОНФИГУРАЦИЯ
# ==========================================
app = FastAPI(title="Rubinov AI Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    except Exception as e:
        print(f"Ошибка отправки Telegram сообщения: {e}")

# ==========================================
# 3. ЛОГИКА ИИ (GEMINI + GENERATION)
# ==========================================
def get_gemini_response(prompt: str, file_bytes: Optional[bytes] = None, mime_type: Optional[str] = None) -> str:
    global current_key_idx, current_model_idx
    lowered = prompt.lower()
    
    # Генерация картинок по ключевым словам
    if any(keyword in lowered for keyword in ["нарисуй", "draw", "сгенерируй"]):
        clean_prompt = prompt.replace("Нарисуй:", "").replace("нарисуй", "").replace("сгенерируй", "").strip()
        if not clean_prompt:
            clean_prompt = "futuristic cyberpunk city with neon lights"
            
        import urllib.parse
        encoded_prompt = urllib.parse.quote(clean_prompt)
        img_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true"
        
        return f"""Вот ваше сгенерированное изображение по запросу: *"{clean_prompt}"*

<div class="generated-img-card">
    <img src="{img_url}" alt="{clean_prompt}" />
    <a href="{img_url}" target="_blank" class="download-btn">📥 Скачать в оригинале</a>
</div>"""

    api_keys = get_api_keys()
    if not api_keys:
        raise HTTPException(status_code=500, detail="API-ключи Gemini не настроены в переменных окружения.")

    num_keys = len(api_keys)
    num_models = len(MODELS)
    
    contents = []
    if file_bytes and mime_type:
        contents.append(types.Part.from_bytes(data=file_bytes, mime_type=mime_type))
    if prompt:
        contents.append(prompt)

    # Цикл ротации ключей и моделей
    for _ in range(num_keys * num_models):
        active_key = api_keys[current_key_idx % num_keys]
        active_model = MODELS[current_model_idx % num_models]
        try:
            client = genai.Client(api_key=active_key)
            response = client.models.generate_content(
                model=active_model, 
                contents=contents
            )
            return response.text
        except APIError:
            current_model_idx = (current_model_idx + 1) % num_models
            if current_model_idx == 0:
                current_key_idx = (current_key_idx + 1) % num_keys
            time.sleep(0.3)
            continue
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка генерации: {str(e)}")
            
    raise HTTPException(status_code=500, detail="Все API-ключи перегружены. Повторите попытку позже.")

# ==========================================
# 4. API ЭНДПОИНТЫ
# ==========================================
@app.post("/api/telegram/webhook")
async def telegram_webhook(req: Request):
    data = await req.json()
    if "message" in data:
        msg = data["message"]
        chat_id = msg["chat"]["id"]
        user = msg.get("from", {})
        user_id = user.get("id")
        username = user.get("username", "")
        first_name = user.get("first_name", "Пользователь")

        text = msg.get("text", "")
        if text.startswith("/start"):
            code = generate_telegram_code(user_id, username, first_name)
            message_text = (
                f"👋 Привет, *{first_name}*!\n\n"
                f"🔑 Твой одноразовый код для входа на сайт: `{code}`\n\n"
                f"Введи этот код на сайте в поле авторизации.\n"
                f"⏳ Код действителен 5 минут."
            )
            send_telegram_message(chat_id, message_text)
            
    return {"ok": True}

@app.post("/api/auth/login-with-code")
def api_login_with_code(code: str = Form(...)):
    code_clean = code.strip()
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT telegram_id, username, first_name, expires_at FROM auth_codes WHERE code = ?", 
        (code_clean,)
    )
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        return {"status": "error", "message": "Неверный или несуществующий код."}

    telegram_id, username, first_name, expires_at = row
    if time.time() > expires_at:
        cursor.execute("DELETE FROM auth_codes WHERE code = ?", (code_clean,))
        conn.commit()
        conn.close()
        return {"status": "error", "message": "Срок действия кода истек. Запросите новый в боте."}

    save_user_db(telegram_id, username, first_name)
    cursor.execute("DELETE FROM auth_codes WHERE code = ?", (code_clean,))
    conn.commit()
    conn.close()

    resp = Response(content='{"status": "success"}', media_type="application/json")
    resp.set_cookie(
        key="tg_user_id", 
        value=str(telegram_id), 
        httponly=True, 
        max_age=30*86400,
        samesite="lax"
    )
    return resp

@app.get("/api/user/status")
def get_user_status(tg_user_id: Optional[str] = Cookie(None)):
    if not tg_user_id:
        return {"logged_in": False}
    user = get_user_db(int(tg_user_id))
    if not user:
        return {"logged_in": False}
    return {
        "logged_in": True,
        "telegram_id": user["telegram_id"],
        "first_name": user["first_name"],
        "username": user["username"],
        "is_vip": user["is_vip"],
        "is_banned": user["is_banned"]
    }

@app.post("/api/chat")
async def chat_endpoint(
    prompt: str = Form(""),
    file: Optional[UploadFile] = File(None),
    tg_user_id: Optional[str] = Cookie(None)
):
    if not tg_user_id:
        raise HTTPException(status_code=401, detail="Авторизуйтесь через Telegram для отправки сообщений")
    
    user = get_user_db(int(tg_user_id))
    if not user or user["is_banned"]:
        raise HTTPException(status_code=403, detail="Ваш аккаунт заблокирован.")

    if file and not user["is_vip"]:
        raise HTTPException(status_code=403, detail="Отправка файлов доступна только для VIP пользователей.")

    file_bytes = await file.read() if file else None
    mime_type = file.content_type if file else None

    answer = get_gemini_response(prompt, file_bytes, mime_type)
    return {"response": answer}

# ==========================================
# 5. ПОЛНОЦЕННЫЙ КРАСИВЫЙ ИНТЕРФЕЙС (HTML/CSS/JS)
# ==========================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Рубинов ИИ — Интеллектуальный Помощник</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <style>
        :root {
            --bg-main: #06080e;
            --bg-sidebar: #0b0f19;
            --card-bg: rgba(23, 31, 48, 0.5);
            --accent-color: #6366f1;
            --accent-hover: #4f46e5;
            --accent-glow: rgba(99, 102, 241, 0.35);
            --border-color: rgba(255, 255, 255, 0.08);
            --text-main: #f3f4f6;
            --text-muted: #9ca3af;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: 'Plus Jakarta Sans', sans-serif;
        }

        body {
            background-color: var(--bg-main);
            color: var(--text-main);
            display: flex;
            height: 100vh;
            overflow: hidden;
        }

        /* Sidebar Styles */
        #sidebar {
            width: 320px;
            background-color: var(--bg-sidebar);
            border-right: 1px solid var(--border-color);
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            padding: 24px;
            z-index: 10;
        }

        .brand-header {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 24px;
        }

        .brand-logo {
            width: 40px;
            height: 40px;
            background: linear-gradient(135deg, #6366f1, #a855f7);
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 0 15px var(--accent-glow);
            font-weight: 700;
            font-size: 18px;
        }

        .brand-title {
            font-size: 20px;
            font-weight: 700;
            letter-spacing: -0.5px;
            background: linear-gradient(to right, #ffffff, #a855f7);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .auth-container {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 20px;
            backdrop-filter: blur(10px);
        }

        .auth-step {
            font-size: 12px;
            color: var(--text-muted);
            margin-bottom: 10px;
            line-height: 1.4;
        }

        .tg-link-btn {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            background: #229ed9;
            color: #ffffff;
            text-decoration: none;
            padding: 10px 14px;
            border-radius: 10px;
            font-size: 13px;
            font-weight: 600;
            margin-bottom: 16px;
            transition: all 0.2s ease;
        }

        .tg-link-btn:hover {
            background: #1c87bc;
            box-shadow: 0 0 12px rgba(34, 158, 217, 0.4);
        }

        .code-input-group {
            display: flex;
            gap: 8px;
        }

        .code-input {
            flex: 1;
            background: rgba(0, 0, 0, 0.4);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 10px;
            color: #fff;
            text-align: center;
            font-size: 14px;
            letter-spacing: 2px;
            outline: none;
        }

        .code-input:focus {
            border-color: var(--accent-color);
            box-shadow: 0 0 8px var(--accent-glow);
        }

        .submit-btn {
            background: var(--accent-color);
            color: #fff;
            border: none;
            padding: 10px 16px;
            border-radius: 10px;
            cursor: pointer;
            font-size: 13px;
            font-weight: 600;
            transition: all 0.2s ease;
        }

        .submit-btn:hover {
            background: var(--accent-hover);
        }

        .error-message {
            color: #ef4444;
            font-size: 11px;
            margin-top: 8px;
            display: none;
        }

        .user-profile-card {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 16px;
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .avatar {
            width: 44px;
            height: 44px;
            border-radius: 50%;
            background: linear-gradient(135deg, #3b82f6, #8b5cf6);
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 16px;
        }

        .user-details {
            display: flex;
            flex-direction: column;
        }

        .user-name {
            font-weight: 600;
            font-size: 14px;
        }

        .user-badge {
            font-size: 11px;
            color: #a855f7;
            font-weight: 500;
        }

        /* Main Workspace */
        #main-content {
            flex: 1;
            display: flex;
            flex-direction: column;
            position: relative;
            background: radial-gradient(circle at top right, rgba(99, 102, 241, 0.05), transparent 40%);
        }

        #chat-container {
            flex: 1;
            overflow-y: auto;
            padding: 30px;
            display: flex;
            flex-direction: column;
            gap: 20px;
            scroll-behavior: smooth;
        }

        .message-row {
            display: flex;
            max-width: 75%;
            flex-direction: column;
        }

        .message-row.user {
            align-self: flex-end;
        }

        .message-row.bot {
            align-self: flex-start;
        }

        .message-bubble {
            padding: 14px 18px;
            border-radius: 18px;
            font-size: 14px;
            line-height: 1.6;
            word-break: break-word;
        }

        .message-row.user .message-bubble {
            background: var(--accent-color);
            color: #fff;
            border-bottom-right-radius: 4px;
            box-shadow: 0 4px 12px var(--accent-glow);
        }

        .message-row.bot .message-bubble {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            color: var(--text-main);
            border-bottom-left-radius: 4px;
            backdrop-filter: blur(8px);
        }

        /* Generated Images Styling */
        .generated-img-card {
            margin-top: 12px;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        .generated-img-card img {
            max-width: 100%;
            border-radius: 12px;
            border: 1px solid var(--border-color);
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
        }

        .download-btn {
            display: inline-block;
            align-self: flex-start;
            background: rgba(255, 255, 255, 0.08);
            color: #fff;
            padding: 8px 14px;
            border-radius: 8px;
            text-decoration: none;
            font-size: 12px;
            border: 1px solid var(--border-color);
            transition: background 0.2s;
        }

        .download-btn:hover {
            background: rgba(255, 255, 255, 0.15);
        }

        /* Input Control Panel */
        #input-panel {
            padding: 20px 30px;
            background: rgba(11, 15, 25, 0.8);
            border-top: 1px solid var(--border-color);
            backdrop-filter: blur(12px);
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        .input-box-wrapper {
            display: flex;
            align-items: center;
            background: rgba(0, 0, 0, 0.4);
            border: 1px solid var(--border-color);
            border-radius: 14px;
            padding: 8px 14px;
            gap: 10px;
            transition: border-color 0.2s;
        }

        .input-box-wrapper:focus-within {
            border-color: var(--accent-color);
            box-shadow: 0 0 10px var(--accent-glow);
        }

        .chat-input {
            flex: 1;
            background: transparent;
            border: none;
            outline: none;
            color: #fff;
            font-size: 14px;
            padding: 6px 0;
        }

        .file-upload-label {
            cursor: pointer;
            color: var(--text-muted);
            transition: color 0.2s;
            display: flex;
            align-items: center;
        }

        .file-upload-label:hover {
            color: #fff;
        }

        .file-upload-input {
            display: none;
        }

        .send-btn {
            background: var(--accent-color);
            color: #fff;
            border: none;
            border-radius: 10px;
            width: 36px;
            height: 36px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            transition: background 0.2s;
        }

        .send-btn:hover {
            background: var(--accent-hover);
        }

        .file-preview-bar {
            font-size: 11px;
            color: var(--accent-color);
            display: none;
        }

        /* Custom Scrollbar */
        ::-webkit-scrollbar {
            width: 6px;
        }
        ::-webkit-scrollbar-track {
            background: transparent;
        }
        ::-webkit-scrollbar-thumb {
            background: rgba(255, 255, 255, 0.1);
            border-radius: 3px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: rgba(255, 255, 255, 0.2);
        }
    </style>
</head>
<body>

    <!-- SIDEBAR -->
    <div id="sidebar">
        <div>
            <div class="brand-header">
                <div class="brand-logo">R</div>
                <div class="brand-title">Рубинов ИИ</div>
            </div>

            <!-- AUTH SECTION -->
            <div id="auth-section" class="auth-container">
                <p class="auth-step">1. Перейдите в Telegram-бота и запустите его (/start):</p>
                <a href="https://t.me/rubinov_ai_bot" target="_blank" class="tg-link-btn">
                    <span>🤖 Открыть бота</span>
                </a>
                
                <p class="auth-step">2. Введите 6-значный код, который пришлет бот:</p>
                <div class="code-input-group">
                    <input type="text" id="auth-code" class="code-input" placeholder="000000" maxlength="6">
                    <button class="submit-btn" onclick="submitAuthCode()">Войти</button>
                </div>
                <div id="auth-error" class="error-message"></div>
            </div>

            <!-- USER INFO SECTION -->
            <div id="user-section" class="user-profile-card" style="display: none;">
                <div class="avatar" id="u-avatar">U</div>
                <div class="user-details">
                    <span class="user-name" id="u-name">Пользователь</span>
                    <span class="user-badge" id="u-status">Обычный доступ</span>
                </div>
            </div>
        </div>

        <div style="font-size: 11px; color: var(--text-muted); text-align: center;">
            &copy; 2026 Rubinov AI Systems
        </div>
    </div>

    <!-- MAIN CONTENT -->
    <div id="main-content">
        <div id="chat-container">
            <div class="message-row bot">
                <div class="message-bubble">
                    Привет! Я интеллектуальный ассистент <b>Рубинов ИИ</b>. Чем я могу помочь вам сегодня?
                </div>
            </div>
        </div>

        <!-- INPUT PANEL -->
        <div id="input-panel">
            <div id="file-preview" class="file-preview-bar"></div>
            <div class="input-box-wrapper">
                <label class="file-upload-label" title="Прикрепить файл (только VIP)">
                    📎
                    <input type="file" id="file-input" class="file-upload-input" onchange="handleFileSelect()">
                </label>
                <input type="text" id="prompt-input" class="chat-input" placeholder="Напишите сообщение или 'Нарисуй...'" onkeydown="if(event.key==='Enter') sendMessage()">
                <button class="send-btn" onclick="sendMessage()">➔</button>
            </div>
        </div>
    </div>

    <!-- JAVASCRIPT LOGIC -->
    <script>
        let selectedFile = null;

        async function checkUserAuth() {
            try {
                const response = await fetch('/api/user/status');
                const data = await response.json();
                
                if (data.logged_in) {
                    document.getElementById('auth-section').style.display = 'none';
                    document.getElementById('user-section').style.display = 'flex';
                    
                    document.getElementById('u-name').textContent = data.first_name || 'Пользователь';
                    document.getElementById('u-avatar').textContent = (data.first_name || 'U')[0].toUpperCase();
                    document.getElementById('u-status').textContent = data.is_vip ? 'VIP Доступ ⭐' : 'Базовый доступ';
                }
            } catch (err) {
                console.error("Ошибка проверки авторизации:", err);
            }
        }

        async function submitAuthCode() {
            const codeInput = document.getElementById('auth-code');
            const errorDiv = document.getElementById('auth-error');
            const code = codeInput.value.trim();

            errorDiv.style.display = 'none';

            if (!code || code.length < 6) {
                errorDiv.textContent = 'Введите 6-значный код.';
                errorDiv.style.display = 'block';
                return;
            }

            const formData = new FormData();
            formData.append('code', code);

            try {
                const response = await fetch('/api/auth/login-with-code', {
                    method: 'POST',
                    body: formData
                });
                const data = await response.json();

                if (data.status === 'success') {
                    window.location.reload();
                } else {
                    errorDiv.textContent = data.message || 'Ошибка входа';
                    errorDiv.style.display = 'block';
                }
            } catch (err) {
                errorDiv.textContent = 'Ошибка соединения с сервером.';
                errorDiv.style.display = 'block';
            }
        }

        function handleFileSelect() {
            const input = document.getElementById('file-input');
            const preview = document.getElementById('file-preview');
            if (input.files && input.files[0]) {
                selectedFile = input.files[0];
                preview.textContent = `Выбран файл: ${selectedFile.name}`;
                preview.style.display = 'block';
            }
        }

        async function sendMessage() {
            const promptInput = document.getElementById('prompt-input');
            const text = promptInput.value.trim();
            const chatContainer = document.getElementById('chat-container');

            if (!text && !selectedFile) return;

            // Рендер сообщения пользователя
            const userRow = document.createElement('div');
            userRow.className = 'message-row user';
            userRow.innerHTML = `<div class="message-bubble">${text}</div>`;
            chatContainer.appendChild(userRow);

            promptInput.value = '';
            chatContainer.scrollTop = chatContainer.scrollHeight;

            // Формирование данных для отправки
            const formData = new FormData();
            formData.append('prompt', text);
            if (selectedFile) {
                formData.append('file', selectedFile);
            }

            // Сброс файла
            selectedFile = null;
            document.getElementById('file-input').value = '';
            document.getElementById('file-preview').style.display = 'none';

            // Индикатор загрузки
            const botRow = document.createElement('div');
            botRow.className = 'message-row bot';
            botRow.innerHTML = `<div class="message-bubble">Печатает...</div>`;
            chatContainer.appendChild(botRow);
            chatContainer.scrollTop = chatContainer.scrollHeight;

            try {
                const response = await fetch('/api/chat', {
                    method: 'POST',
                    body: formData
                });
                const data = await response.json();

                if (response.ok) {
                    botRow.querySelector('.message-bubble').innerHTML = marked.parse(data.response);
                } else {
                    botRow.querySelector('.message-bubble').innerHTML = `<span style="color:#ef4444;">${data.detail || 'Ошибка получения ответа'}</span>`;
                }
            } catch (err) {
                botRow.querySelector('.message-bubble').innerHTML = `<span style="color:#ef4444;">Ошибка подключения к серверу</span>`;
            }

            chatContainer.scrollTop = chatContainer.scrollHeight;
        }

        // Автоматическая проверка авторизации при загрузке страницы
        checkUserAuth();
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def get_ui():
    return HTML_TEMPLATE

# ==========================================
# 6. ТОЧКА ВХОДА И ЗАПУСК UVIORN
# ==========================================
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)

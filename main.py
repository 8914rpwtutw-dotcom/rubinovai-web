import os, time, secrets, urllib.parse
from typing import Optional
from fastapi import FastAPI, HTTPException, File, Form, UploadFile, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select

from google import genai
from google.genai import types
from google.genai.errors import APIError

from database import AsyncSessionLocal, AuthCode, User, AuthSession, init_db

app = FastAPI(title="Rubinov AI Web Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MODELS = ["gemini-2.5-flash", "gemini-3.1-flash-lite", "gemini-2.5-pro"]

@app.on_event("startup")
async def startup():
    await init_db()

class CodeVerifyRequest(BaseModel):
    code: str

@app.post("/api/verify-code")
async def verify_code(data: CodeVerifyRequest):
    user_code = data.code.strip()
    async with AsyncSessionLocal() as session:
        stmt = select(AuthCode).where(AuthCode.code == user_code, AuthCode.is_used == False)
        auth_entry = (await session.execute(stmt)).scalars().first()

        if not auth_entry:
            raise HTTPException(status_code=400, detail="Неверный или использованный код.")

        user_stmt = select(User).where(User.telegram_id == auth_entry.telegram_id)
        user = (await session.execute(user_stmt)).scalars().first()

        if user and user.is_banned:
            raise HTTPException(status_code=403, detail=f"Аккаунт заблокирован. Причина: {user.ban_reason or 'Не указана'}")

        auth_entry.is_used = True
        token = secrets.token_hex(32)
        session.add(AuthSession(token=token, telegram_id=auth_entry.telegram_id))
        await session.commit()

        return {
            "status": "success",
            "token": token,
            "is_vip": user.is_vip if user else False
        }

@app.get("/api/user-status")
async def check_user_status(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization.replace("Bearer ", "").strip()
    
    async with AsyncSessionLocal() as session:
        sess_stmt = select(AuthSession).where(AuthSession.token == token)
        auth_sess = (await session.execute(sess_stmt)).scalars().first()
        if not auth_sess:
            raise HTTPException(status_code=401, detail="Session expired")

        user_stmt = select(User).where(User.telegram_id == auth_sess.telegram_id)
        user = (await session.execute(user_stmt)).scalars().first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        return {
            "is_banned": user.is_banned,
            "ban_reason": user.ban_reason,
            "is_vip": user.is_vip
        }

def get_api_keys() -> list[str]:
    raw_keys = [os.getenv("GEMINI_KEY_1"), os.getenv("GEMINI_KEY_2"), os.getenv("GEMINI_KEY_3"), os.getenv("GEMINI_API_KEY")]
    return [k.strip() for k in raw_keys if k and k.strip()]

def generate_image_response(prompt: str) -> str:
    clean_prompt = prompt.replace("Нарисуй:", "").replace("нарисуй", "").replace("сгенерируй", "").strip() or "neon cyber ruby crystal"
    encoded_prompt = urllib.parse.quote(clean_prompt)
    img_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true"
    return f"""Вот ваше сгенерированное изображение по запросу: *"{clean_prompt}"*

<div style="margin-top:14px;">
    <img src="{img_url}" alt="{clean_prompt}" style="max-width:100%; border-radius:16px; display:block; margin-bottom:12px; box-shadow: 0 12px 40px rgba(168, 85, 247, 0.25); border: 1px solid rgba(255,255,255,0.1);" />
    <a href="{img_url}" target="_blank" download="rubinov_ai.jpg" style="display:inline-flex; align-items: center; gap: 8px; background: linear-gradient(135deg, #8b5cf6, #d946ef); color:#fff; padding:10px 20px; border-radius:12px; font-size:13px; text-decoration:none; font-weight:600;">📥 Скачать в высоком разрешении</a>
</div>"""

def get_gemini_response(prompt: str, file_bytes: Optional[bytes] = None, mime_type: Optional[str] = None) -> str:
    if any(k in prompt.lower() for k in ["нарисуй", "draw", "сгенерируй"]):
        return generate_image_response(prompt)

    api_keys = get_api_keys()
    if not api_keys:
        raise HTTPException(status_code=500, detail="API-ключи не найдены.")

    contents = []
    if file_bytes and mime_type:
        contents.append(types.Part.from_bytes(data=file_bytes, mime_type=mime_type))
    if prompt.strip():
        contents.append(prompt)

    for api_key in api_keys:
        client = genai.Client(api_key=api_key)
        for model in MODELS:
            try:
                response = client.models.generate_content(model=model, contents=contents)
                if response.text:
                    return response.text
            except APIError as e:
                if e.code in [429, 503] or "RESOURCE_EXHAUSTED" in str(e):
                    time.sleep(0.3)
                    continue
                elif e.code == 404: continue
                else: break
            except Exception: continue

    raise HTTPException(status_code=503, detail="Сервис ИИ перегружен. Попробуйте через пару секунд.")

@app.post("/api/chat")
async def chat_endpoint(
    prompt: str = Form(""),
    file: Optional[UploadFile] = File(None),
    authorization: Optional[str] = Header(None)
):
    if not authorization:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    
    token = authorization.replace("Bearer ", "").strip()
    
    async with AsyncSessionLocal() as session:
        sess_stmt = select(AuthSession).where(AuthSession.token == token)
        auth_sess = (await session.execute(sess_stmt)).scalars().first()
        if not auth_sess:
            raise HTTPException(status_code=401, detail="Сессия недействительна")

        user_stmt = select(User).where(User.telegram_id == auth_sess.telegram_id)
        user = (await session.execute(user_stmt)).scalars().first()

        if user and user.is_banned:
            raise HTTPException(status_code=403, detail=f"ВЫ ЗАБАНЕНЫ: {user.ban_reason or 'Нарушение правил'}")

        if file and (not user or not user.is_vip):
            raise HTTPException(status_code=403, detail="⭐ Прикрепление файлов доступно только VIP-пользователям!")

    file_bytes, mime_type = None, None
    if file:
        file_bytes = await file.read()
        mime_type = file.content_type

    answer = get_gemini_response(prompt, file_bytes, mime_type)
    return {"response": answer}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <title>Rubinov AI</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <style>
        :root {
            --bg-main: #06070b;
            --bg-sidebar: rgba(13, 15, 23, 0.75);
            --border-color: rgba(255, 255, 255, 0.07);
            --accent-gradient: linear-gradient(135deg, #6366f1 0%, #a855f7 50%, #ec4899 100%);
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --user-msg-bg: linear-gradient(135deg, rgba(99, 102, 241, 0.2) 0%, rgba(168, 85, 247, 0.18) 100%);
            --bot-msg-bg: rgba(18, 22, 32, 0.7);
        }

        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', sans-serif; }
        html, body { height: 100%; overflow: hidden; background: var(--bg-main); color: var(--text-main); }
        body { display: flex; position: relative; }

        #ban-overlay {
            display: none; position: fixed; top: 0; left: 0; width: 100vw; height: 100dvh;
            background: rgba(15, 3, 3, 0.95); backdrop-filter: blur(25px); z-index: 2000;
            flex-direction: column; align-items: center; justify-content: center; padding: 24px; text-align: center;
        }
        .ban-card { background: rgba(30, 10, 10, 0.8); border: 1px solid rgba(248, 113, 113, 0.4); padding: 40px 30px; border-radius: 24px; max-width: 440px; box-shadow: 0 0 50px rgba(248, 113, 113, 0.2); }
        .ban-card h1 { color: #f87171; font-size: 24px; margin-bottom: 12px; }
        .ban-card p { color: #cbd5e1; font-size: 14px; line-height: 1.6; margin-bottom: 20px; }

        .vip-badge { background: linear-gradient(135deg, #f59e0b, #ec4899); color: #fff; font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 20px; text-transform: uppercase; letter-spacing: 0.5px; box-shadow: 0 0 12px rgba(245, 158, 11, 0.4); }
        .free-badge { background: rgba(255, 255, 255, 0.08); color: var(--text-muted); font-size: 11px; font-weight: 600; padding: 4px 10px; border-radius: 20px; }

        #auth-modal { position: fixed; top: 0; left: 0; width: 100vw; height: 100dvh; background: rgba(4, 5, 8, 0.9); backdrop-filter: blur(20px); z-index: 1000; display: flex; align-items: center; justify-content: center; padding: 20px; }
        .auth-card { background: rgba(18, 22, 34, 0.85); border: 1px solid rgba(168, 85, 247, 0.3); border-radius: 28px; padding: 36px 28px; max-width: 420px; width: 100%; text-align: center; }
        .btn-telegram { display: flex; align-items: center; justify-content: center; gap: 10px; width: 100%; padding: 14px; background: #229ED9; color: #fff; text-decoration: none; font-weight: 600; border-radius: 16px; margin-bottom: 20px; }
        .code-input-field { width: 100%; background: rgba(10, 12, 18, 0.6); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 16px; padding: 14px; color: #fff; font-size: 18px; text-align: center; letter-spacing: 4px; outline: none; margin-bottom: 16px; }
        .btn-auth-submit { width: 100%; padding: 14px; background: var(--accent-gradient); border: none; border-radius: 16px; color: #fff; font-weight: 600; cursor: pointer; }

        #sidebar { width: 280px; background: var(--bg-sidebar); backdrop-filter: blur(28px); border-right: 1px solid var(--border-color); display: flex; flex-direction: column; padding: 20px 14px; z-index: 50; height: 100dvh; }
        .brand { display: flex; align-items: center; justify-content: space-between; margin-bottom: 22px; padding: 0 6px; }
        .brand-title { display: flex; align-items: center; gap: 10px; }
        .btn-new-chat { background: var(--accent-gradient); color: #fff; border: none; padding: 12px; border-radius: 14px; font-weight: 600; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 8px; margin-bottom: 20px; }

        #chats-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; }
        .chat-item { background: rgba(255, 255, 255, 0.02); border: 1px solid var(--border-color); border-radius: 12px; padding: 10px 12px; font-size: 13px; color: #cbd5e1; cursor: pointer; display: flex; justify-content: space-between; }
        .chat-item.active { background: rgba(168, 85, 247, 0.12); border-color: rgba(168, 85, 247, 0.4); color: #fff; }

        #main { flex: 1; display: flex; flex-direction: column; position: relative; height: 100dvh; }
        #chat-header { height: 64px; border-bottom: 1px solid var(--border-color); display: flex; align-items: center; justify-content: space-between; padding: 0 24px; background: rgba(6, 7, 11, 0.6); backdrop-filter: blur(20px); }
        #chat-container { flex: 1; overflow-y: auto; padding: 24px 24px 160px 24px; display: flex; flex-direction: column; gap: 20px; max-width: 860px; width: 100%; margin: 0 auto; }

        .msg-row { display: flex; flex-direction: column; width: 100%; }
        .msg-row.user-row { align-items: flex-end; }
        .msg-row.bot-row { align-items: flex-start; }
        .msg-user { background: var(--user-msg-bg); border: 1px solid rgba(168, 85, 247, 0.3); border-radius: 20px 20px 4px 20px; padding: 14px 20px; max-width: 82%; font-size: 14px; word-break: break-word; }
        .msg-bot { background: var(--bot-msg-bg); border: 1px solid var(--border-color); border-radius: 20px 20px 20px 4px; padding: 20px; max-width: 88%; font-size: 14px; word-break: break-word; }

        #input-wrapper { position: absolute; bottom: 0; left: 0; right: 0; padding: 16px 24px 20px 24px; background: linear-gradient(180deg, transparent 0%, var(--bg-main) 100%); }
        #input-container { max-width: 860px; margin: 0 auto; background: rgba(15, 18, 28, 0.85); backdrop-filter: blur(28px); border: 1px solid rgba(168, 85, 247, 0.22); border-radius: 22px; padding: 10px 14px; display: flex; flex-direction: column; gap: 8px; }
        .input-row { display: flex; gap: 10px; align-items: flex-end; }
        
        .mini-btn { background: rgba(255, 255, 255, 0.03); border: 1px solid var(--border-color); color: var(--text-muted); width: 40px; height: 40px; border-radius: 12px; cursor: pointer; display: flex; align-items: center; justify-content: center; }
        .mini-btn.disabled { opacity: 0.3; cursor: not-allowed; }
        #prompt-input { flex: 1; background: transparent; border: none; color: #fff; font-size: 14.5px; outline: none; resize: none; max-height: 180px; min-height: 24px; line-height: 1.5; }
        .btn-action { background: var(--accent-gradient); color: #fff; border: none; border-radius: 12px; padding: 0 20px; height: 40px; font-weight: 600; cursor: pointer; }
    </style>
</head>
<body>
    <div id="ban-overlay">
        <div class="ban-card">
            <h1>⛔️ Доступ заблокирован</h1>
            <p id="ban-reason-text">Ваш аккаунт был заблокирован за нарушение правил.</p>
            <p style="font-size:12px; color:#94a3b8;">Для апелляции напишите команду <b>/ticket</b> в нашего Telegram бота.</p>
        </div>
    </div>

    <div id="auth-modal">
        <div class="auth-card">
            <h2>Авторизация</h2>
            <p style="font-size:13px; color:var(--text-muted); margin: 10px 0 20px 0;">Введите 6-значный код из Telegram бота</p>
            <a href="https://t.me/ТВОЙ_БОТ" target="_blank" class="btn-telegram">Перейти в Telegram бота</a>
            <input type="text" id="auth-code-input" class="code-input-field" placeholder="000000" maxlength="6" />
            <button class="btn-auth-submit" onclick="submitAuthCode()">Войти</button>
            <div id="auth-error" style="color:#f87171; font-size:12px; margin-top:10px; display:none;"></div>
        </div>
    </div>

    <div id="sidebar">
        <div class="brand">
            <div class="brand-title">
                <span style="font-weight:700;">Rubinov AI</span>
            </div>
            <span id="user-vip-status" class="free-badge">FREE</span>
        </div>
        <button class="btn-new-chat" onclick="createNewChat()">+ Новый диалог</button>
        <div id="chats-list"></div>
    </div>

    <div id="main">
        <div id="chat-header">
            <h3 id="current-chat-title">Чат</h3>
        </div>
        <div id="chat-container"></div>
        <div id="input-wrapper">
            <div id="input-container">
                <div id="file-info-bar" style="display:none; justify-content:space-between; font-size:12px; color:#a855f7;">
                    <span id="file-name-text"></span>
                    <button onclick="removeSelectedFile()" style="background:none; border:none; color:#f87171; cursor:pointer;">✕</button>
                </div>
                <div class="input-row">
                    <input type="file" id="file-input" accept="image/*" style="display:none;" onchange="handleFileSelect(event)" />
                    
                    <button class="mini-btn" id="file-btn" onclick="triggerFileClick()" title="Прикрепить фото (Только VIP)">
                        📷
                    </button>

                    <textarea id="prompt-input" rows="1" placeholder="Введите сообщение..." onkeydown="handleKeyPress(event)"></textarea>
                    <button class="btn-action" onclick="sendMessage()">Отправить</button>
                </div>
            </div>
        </div>
    </div>

    <script>
        let authToken = localStorage.getItem('rubinov_token');
        let isVip = false;
        let selectedFile = null;
        let chats = JSON.parse(localStorage.getItem('rubinov_chats') || '[]');
        let currentChatId = localStorage.getItem('rubinov_active_chat');

        async function checkStatus() {
            if (!authToken) return;
            try {
                const res = await fetch('/api/user-status', {
                    headers: { 'Authorization': 'Bearer ' + authToken }
                });
                if (res.status === 401) {
                    localStorage.removeItem('rubinov_token');
                    location.reload();
                    return;
                }
                const data = await res.json();
                
                if (data.is_banned) {
                    document.getElementById('ban-reason-text').textContent = 'Причина бана: ' + (data.ban_reason || 'Не указана');
                    document.getElementById('ban-overlay').style.display = 'flex';
                    return;
                } else {
                    document.getElementById('ban-overlay').style.display = 'none';
                }

                isVip = data.is_vip;
                updateVipUI();
            } catch (e) {}
        }

        function updateVipUI() {
            const badge = document.getElementById('user-vip-status');
            const fileBtn = document.getElementById('file-btn');
            if (isVip) {
                badge.className = 'vip-badge';
                badge.textContent = '⭐ VIP';
                fileBtn.classList.remove('disabled');
            } else {
                badge.className = 'free-badge';
                badge.textContent = 'FREE';
                fileBtn.classList.add('disabled');
            }
        }

        function triggerFileClick() {
            if (!isVip) {
                alert('⭐ Прикреплять файлы могут только VIP-пользователи!');
                return;
            }
            document.getElementById('file-input').click();
        }

        async function submitAuthCode() {
            const code = document.getElementById('auth-code-input').value.trim();
            const err = document.getElementById('auth-error');
            try {
                const res = await fetch('/api/verify-code', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ code })
                });
                const data = await res.json();
                if (res.ok) {
                    authToken = data.token;
                    localStorage.setItem('rubinov_token', authToken);
                    document.getElementById('auth-modal').style.display = 'none';
                    checkStatus();
                } else {
                    err.textContent = data.detail;
                    err.style.display = 'block';
                }
            } catch (e) {
                err.textContent = 'Ошибка проверки кода.';
                err.style.display = 'block';
            }
        }

        function handleFileSelect(e) {
            const file = e.target.files[0];
            if (file) {
                selectedFile = file;
                document.getElementById('file-name-text').textContent = '📷 ' + file.name;
                document.getElementById('file-info-bar').style.display = 'flex';
            }
        }

        function removeSelectedFile() {
            selectedFile = null;
            document.getElementById('file-input').value = '';
            document.getElementById('file-info-bar').style.display = 'none';
        }

        async function sendMessage() {
            const input = document.getElementById('prompt-input');
            const text = input.value.trim();
            if (!text && !selectedFile) return;

            const activeChat = chats.find(c => c.id === currentChatId);
            if (!activeChat) return;

            activeChat.messages.push({ role: 'user', text, file: selectedFile ? selectedFile.name : null });
            renderMessages();
            input.value = '';

            const formData = new FormData();
            formData.append('prompt', text);
            if (selectedFile) formData.append('file', selectedFile);
            removeSelectedFile();

            try {
                const res = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + authToken },
                    body: formData
                });
                const data = await res.json();
                if (res.status === 403 && data.detail.includes('ЗАБАНЕНЫ')) {
                    checkStatus();
                    return;
                }
                if (res.ok) {
                    activeChat.messages.push({ role: 'bot', text: data.response });
                } else {
                    activeChat.messages.push({ role: 'bot', text: 'Ошибка: ' + data.detail });
                }
            } catch (e) {
                activeChat.messages.push({ role: 'bot', text: 'Ошибка соединения.' });
            }
            saveState();
        }

        function saveState() {
            localStorage.setItem('rubinov_chats', JSON.stringify(chats));
            localStorage.setItem('rubinov_active_chat', currentChatId);
            renderChats();
            renderMessages();
        }

        function createNewChat() {
            const newChat = { id: Date.now().toString(), name: 'Чат ' + (chats.length + 1), messages: [] };
            chats.push(newChat);
            currentChatId = newChat.id;
            saveState();
        }

        function renderChats() {
            const list = document.getElementById('chats-list');
            list.innerHTML = '';
            chats.forEach(c => {
                const el = document.createElement('div');
                el.className = 'chat-item ' + (c.id === currentChatId ? 'active' : '');
                el.textContent = c.name;
                el.onclick = () => { currentChatId = c.id; saveState(); };
                list.appendChild(el);
            });
        }

        function renderMessages() {
            const container = document.getElementById('chat-container');
            container.innerHTML = '';
            const activeChat = chats.find(c => c.id === currentChatId);
            if (!activeChat) return;

            activeChat.messages.forEach(m => {
                const row = document.createElement('div');
                row.className = 'msg-row ' + (m.role === 'user' ? 'user-row' : 'bot-row');
                const box = document.createElement('div');
                box.className = m.role === 'user' ? 'msg-user' : 'msg-bot';
                box.innerHTML = m.role === 'user' ? (m.file ? `📷 <i>${m.file}</i><br>` : '') + m.text : marked.parse(m.text);
                row.appendChild(box);
                container.appendChild(row);
            });
            container.scrollTop = container.scrollHeight;
        }

        function handleKeyPress(e) {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
        }

        if (authToken) {
            document.getElementById('auth-modal').style.display = 'none';
            checkStatus();
            setInterval(checkStatus, 5000);
        }

        if (chats.length === 0) createNewChat();
        else renderChats();
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def get_chat_ui():
    return HTML_TEMPLATE

import os
import asyncio
import random
import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select

from database import init_db, AsyncSessionLocal, AuthCode, User
from bot import bot, dp

app = FastAPI()

GEMINI_KEYS = [
    os.getenv("GEMINI_KEY_1"),
    os.getenv("GEMINI_KEY_2"),
    os.getenv("GEMINI_KEY_3")
]
GEMINI_KEYS = [k for k in GEMINI_KEYS if k]

def generate_gemini_response(prompt: str) -> str:
    if not GEMINI_KEYS:
        raise HTTPException(status_code=500, detail="Ключи Gemini не найдены в Environment Variables")

    keys_to_try = GEMINI_KEYS.copy()
    random.shuffle(keys_to_try)
    last_error = "Не удалось получить ответ от Gemini API."

    for key in keys_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={key}"
        headers = {"Content-Type": "application/json"}
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            if response.status_code == 200:
                data = response.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
            else:
                last_error = f"Ошибка API ({response.status_code})"
        except Exception as e:
            last_error = f"Ошибка подключения: {str(e)}"

    raise HTTPException(status_code=500, detail=f"Все ключи заняты. {last_error}")

@app.on_event("startup")
async def startup_event():
    await init_db()
    asyncio.create_task(dp.start_polling(bot))

class CodeVerifyRequest(BaseModel):
    code: str

class PromptRequest(BaseModel):
    prompt: str

@app.post("/api/verify-code")
async def verify_code(data: CodeVerifyRequest):
    async with AsyncSessionLocal() as session:
        stmt = select(AuthCode).where(AuthCode.code == data.code.strip())
        auth = (await session.execute(stmt)).scalars().first()
        if not auth:
            raise HTTPException(status_code=400, detail="Неверный или истекший код")

        user = (await session.execute(select(User).where(User.telegram_id == auth.telegram_id))).scalars().first()
        if user and user.is_banned:
            raise HTTPException(status_code=403, detail=f"Аккаунт заблокирован: {user.ban_reason}")

        await session.delete(auth)
        await session.commit()
        return {"status": "ok", "telegram_id": auth.telegram_id, "is_vip": user.is_vip if user else False}

@app.post("/api/generate")
async def generate_ai(data: PromptRequest):
    if not data.prompt.strip():
        raise HTTPException(status_code=400, detail="Запрос пустой")
    return {"response": generate_gemini_response(data.prompt)}

@app.get("/", response_class=HTMLResponse)
async def get_chat_ui():
    return """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <title>Rubinov AI</title>
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body { background: #0b0c10; color: #c5c6c7; font-family: sans-serif; display: flex; height: 100vh; overflow: hidden; }
            #auth-overlay { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: #0b0c10; display: flex; justify-content: center; align-items: center; z-index: 1000; }
            .auth-card { background: #1f2833; padding: 40px; border-radius: 16px; border: 1px solid #45a29e; text-align: center; width: 360px; box-shadow: 0 0 20px rgba(102,252,241,0.2); }
            .auth-card h2 { color: #66fcf1; margin-bottom: 10px; }
            .auth-card input { width: 100%; padding: 12px; border-radius: 8px; border: 1px solid #45a29e; background: #0b0c10; color: #66fcf1; text-align: center; font-size: 20px; margin-bottom: 20px; outline: none; }
            .auth-card button { width: 100%; padding: 12px; border-radius: 8px; border: none; background: #66fcf1; color: #0b0c10; font-weight: bold; cursor: pointer; }
            .auth-card a { color: #66fcf1; display: inline-block; margin-top: 15px; font-size: 13px; text-decoration: none; }
            .sidebar { width: 260px; background: #1f2833; padding: 20px; border-right: 1px solid #333; display: flex; flex-direction: column; justify-content: space-between; }
            .logo { font-size: 22px; font-weight: bold; color: #66fcf1; text-align: center; }
            .user-info { background: #0b0c10; padding: 15px; border-radius: 10px; border: 1px solid #45a29e; font-size: 13px; }
            .main-content { flex: 1; display: flex; flex-direction: column; background: #0b0c10; }
            .chat-header { padding: 20px; background: #1f2833; border-bottom: 1px solid #333; color: #66fcf1; font-weight: bold; }
            .messages-container { flex: 1; padding: 20px; overflow-y: auto; display: flex; flex-direction: column; gap: 15px; }
            .msg { max-width: 80%; padding: 12px 16px; border-radius: 12px; font-size: 15px; line-height: 1.5; white-space: pre-wrap; }
            .msg.user { align-self: flex-end; background: #45a29e; color: #0b0c10; font-weight: 500; }
            .msg.ai { align-self: flex-start; background: #1f2833; color: #c5c6c7; border: 1px solid #333; }
            .input-area { padding: 20px; background: #1f2833; display: flex; gap: 10px; border-top: 1px solid #333; }
            .input-area textarea { flex: 1; padding: 12px; border-radius: 8px; border: 1px solid #45a29e; background: #0b0c10; color: #fff; resize: none; height: 50px; outline: none; }
            .input-area button { padding: 0 25px; border-radius: 8px; border: none; background: #66fcf1; color: #0b0c10; font-weight: bold; cursor: pointer; }
        </style>
    </head>
    <body>
        <div id="auth-overlay">
            <div class="auth-card">
                <h2>Rubinov AI</h2>
                <p>Введите код из Telegram</p>
                <input type="text" id="code" placeholder="123456" maxlength="6">
                <button onclick="login()">Войти</button><br>
                <a href="https://t.me/Rubinov_Ai_bot" target="_blank">Получить код в боте</a>
            </div>
        </div>
        <div class="sidebar">
            <div class="logo">💎 Rubinov AI</div>
            <div class="user-info" id="user-info-box">ID: Не авторизован</div>
        </div>
        <div class="main-content">
            <div class="chat-header">Нейросеть</div>
            <div class="messages-container" id="messages">
                <div class="msg ai">Привет! Задай вопрос ниже.</div>
            </div>
            <div class="input-area">
                <textarea id="prompt" placeholder="Спроси о чём угодно..." onkeydown="if(event.key==='Enter' && !event.shiftKey){event.preventDefault(); sendPrompt();}"></textarea>
                <button onclick="sendPrompt()">Отправить</button>
            </div>
        </div>
        <script>
            async function login() {
                const code = document.getElementById('code').value;
                const res = await fetch('/api/verify-code', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({code}) });
                const data = await res.json();
                if(res.ok) {
                    document.getElementById('auth-overlay').style.display = 'none';
                    document.getElementById('user-info-box').innerHTML = `👤 <b>ID:</b> ${data.telegram_id}<br>⭐ <b>Статус:</b> ${data.is_vip ? 'VIP' : 'FREE'}`;
                } else { alert(data.detail || 'Ошибка'); }
            }
            async function sendPrompt() {
                const input = document.getElementById('prompt');
                const text = input.value.trim();
                if(!text) return;
                const msgs = document.getElementById('messages');
                const userMsg = document.createElement('div'); userMsg.className = 'msg user'; userMsg.innerText = text; msgs.appendChild(userMsg);
                input.value = ''; msgs.scrollTop = msgs.scrollHeight;
                const aiMsg = document.createElement('div'); aiMsg.className = 'msg ai'; aiMsg.innerText = 'Думаю...'; msgs.appendChild(aiMsg); msgs.scrollTop = msgs.scrollHeight;
                const res = await fetch('/api/generate', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({prompt: text}) });
                const data = await res.json();
                aiMsg.innerText = res.ok ? data.response : 'Ошибка: ' + (data.detail || 'Сбой');
                msgs.scrollTop = msgs.scrollHeight;
            }
        </script>
    </body>
    </html>
    """

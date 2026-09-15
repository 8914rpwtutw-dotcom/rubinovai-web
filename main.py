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

# Считываем 3 ключа из Environment Variables на Render
GEMINI_KEYS = [
    os.getenv("GEMINI_KEY_1"),
    os.getenv("GEMINI_KEY_2"),
    os.getenv("GEMINI_KEY_3")
]

# Фильтруем список, оставляя только запряженные ключи
GEMINI_KEYS = [k for k in GEMINI_KEYS if k]

# Функция для запроса к Gemini с ротацией ключей
def generate_gemini_response(prompt: str) -> str:
    if not GEMINI_KEYS:
        raise HTTPException(status_code=500, detail="Ключи Gemini не найдены в Environment Variables")

    # Перемешиваем ключи для равномерной нагрузки
    keys_to_try = GEMINI_KEYS.copy()
    random.shuffle(keys_to_try)

    last_error = "Не удалось получить ответ от Gemini API."

    for key in keys_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }]
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            if response.status_code == 200:
                data = response.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
            else:
                last_error = f"Ошибка API ({response.status_code}): {response.text}"
                print(f"[Gemini Log] Ключ выдал ошибку {response.status_code}, пробуем следующий...")
        except Exception as e:
            last_error = f"Ошибка подключения: {str(e)}"
            print(f"[Gemini Log] Сбой запроса, пробуем следующий...")

    raise HTTPException(status_code=500, detail=f"Все ключи Gemini недоступны. {last_error}")


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
        res = await session.execute(stmt)
        auth = res.scalars().first()

        if not auth:
            raise HTTPException(status_code=400, detail="Неверный или истекший код")

        user_stmt = select(User).where(User.telegram_id == auth.telegram_id)
        user = (await session.execute(user_stmt)).scalars().first()

        if user and user.is_banned:
            raise HTTPException(status_code=403, detail=f"Аккаунт заблокирован: {user.ban_reason}")

        await session.delete(auth)
        await session.commit()

        return {
            "status": "ok",
            "telegram_id": auth.telegram_id,
            "is_vip": user.is_vip if user else False
        }

@app.post("/api/generate")
async def generate_ai(data: PromptRequest):
    if not data.prompt.strip():
        raise HTTPException(status_code=400, detail="Запрос не может быть пустым")

    answer = generate_gemini_response(data.prompt)
    return {"response": answer}

@app.get("/", response_class=HTMLResponse)
async def get_chat_ui():
    return """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <title>Rubinov AI</title>
        <style>
            body { background: #0f0f12; color: #fff; font-family: sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
            .card { background: #18181c; padding: 30px; border-radius: 12px; text-align: center; box-shadow: 0 4px 20px rgba(0,0,0,0.5); width: 340px; }
            input, textarea { width: 90%; padding: 10px; margin: 10px 0; border-radius: 6px; border: 1px solid #333; background: #222; color: #fff; font-size: 14px; }
            button { background: #0088cc; color: #fff; border: none; padding: 10px 20px; border-radius: 6px; cursor: pointer; font-size: 16px; width: 100%; margin-top: 10px; }
            a { color: #0088cc; text-decoration: none; display: block; margin-top: 15px; font-size: 14px; }
            #chat-box { display: none; }
            .response-area { background: #222; padding: 10px; border-radius: 6px; text-align: left; max-height: 150px; overflow-y: auto; margin-top: 10px; font-size: 13px; white-space: pre-wrap; }
        </style>
    </head>
    <body>
        <div class="card" id="auth-box">
            <h2>Rubinov AI</h2>
            <p>Введите 6-значный код из бота</p>
            <input type="text" id="code" placeholder="123456" maxlength="6">
            <button onclick="login()">Войти</button>
            <a href="https://t.me/Rubinov_Ai_bot" target="_blank">Перейти в Telegram бота</a>
        </div>

        <div class="card" id="chat-box">
            <h2>Чат с Rubinov AI</h2>
            <textarea id="prompt" rows="3" placeholder="Задай вопрос ИИ..."></textarea>
            <button onclick="sendPrompt()">Отправить</button>
            <div id="result" class="response-area" style="display:none;"></div>
        </div>

        <script>
            async function login() {
                const code = document.getElementById('code').value;
                const res = await fetch('/api/verify-code', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({code})
                });
                const data = await res.json();
                if(res.ok) {
                    document.getElementById('auth-box').style.display = 'none';
                    document.getElementById('chat-box').style.display = 'block';
                } else {
                    alert(data.detail || 'Ошибка авторизации');
                }
            }

            async function sendPrompt() {
                const prompt = document.getElementById('prompt').value;
                const resultDiv = document.getElementById('result');
                if(!prompt) return;

                resultDiv.style.display = 'block';
                resultDiv.innerText = 'Думаю...';

                const res = await fetch('/api/generate', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({prompt})
                });
                const data = await res.json();
                if(res.ok) {
                    resultDiv.innerText = data.response;
                } else {
                    resultDiv.innerText = 'Ошибка: ' + (data.detail || 'Не удалось получить ответ');
                }
            }
        </script>
    </body>
    </html>
    """

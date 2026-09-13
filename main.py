import os
import time
import json
import uuid
import io
import base64
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted, GoogleAPIError

app = FastAPI()

SERVER_BUILD_ID = str(uuid.uuid4())[:8]
IMAGE_GEN_ENABLED = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# ------------------------------------------------------------------
#  БЛОК РОТАЦИИ КЛЮЧЕЙ И МОДЕЛЕЙ (Multi-key & Fallback Strategy)
# ------------------------------------------------------------------

# Динамически считываем все ключи (GEMINI_KEY_1, GEMINI_KEY_2 и т.д.)
API_KEYS = [
    os.getenv("GEMINI_KEY_1"),
    os.getenv("GEMINI_KEY_2"),
    os.getenv("GEMINI_KEY_3"),
]
# Оставляем только те ключи, которые заданы в настройках хостинга
API_KEYS = [k for k in API_KEYS if k]

# Модели для отката (от основной к более легким)
MODELS_PRIORITY = [
    "gemini-2.0-flash",
    "gemini-1.5-flash"
]

current_key_index = 0

def get_gemini_response(prompt: str) -> str:
    """Генерация текста с автоматическим переключением ключей и моделей при 429"""
    global current_key_index
    
    if not API_KEYS:
        raise HTTPException(
            status_code=500, 
            detail="API-ключи не настроены. Добавьте GEMINI_KEY_1 в Environment Variables на Render."
        )
        
    total_keys = len(API_KEYS)
    keys_tried = 0

    while keys_tried < total_keys:
        active_key = API_KEYS[current_key_index]
        genai.configure(api_key=active_key)
        
        for model_name in MODELS_PRIORITY:
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(prompt)
                return response.text
                
            except ResourceExhausted:
                # Перебор моделей в рамках одного ключа при лимитах
                print(f"[Gemini] Модель {model_name} уперлась в лимит на ключе #{current_key_index + 1}. Пробуем следующую модель...")
                continue
                
            except GoogleAPIError as e:
                print(f"[Gemini API Error] {e}")
                break

        # Если все модели на текущем ключе исчерпаны — меняем ключ
        print(f"[Gemini] Переключаем API-ключ с #{current_key_index + 1}...")
        current_key_index = (current_key_index + 1) % total_keys
        keys_tried += 1

    raise HTTPException(status_code=429, detail="Все API-ключи и модели исчерпали доступные лимиты. Попробуйте чуть позже.")

# ------------------------------------------------------------------
#  СХЕМЫ ДАННЫХ И API ЭНДПОИНТЫ
# ------------------------------------------------------------------

class TitleRequest(BaseModel):
    message: str

class ImageGenRequest(BaseModel):
    prompt: str

class ChatPayload(BaseModel):
    prompt: str

@app.get("/health")
def health_check():
    return {"status": "ok", "build_id": SERVER_BUILD_ID}

@app.post("/api/chat")
async def chat_endpoint(payload: ChatPayload):
    if not payload.prompt.strip():
        raise HTTPException(status_code=400, detail="Текст запроса не может быть пустым")
    
    answer = get_gemini_response(payload.prompt)
    return {"response": answer}

@app.post("/api/generate-title")
async def generate_title(req: TitleRequest):
    if not req.message.strip():
        return {"title": "Новый диалог"}
        
    prompt = f"Придумай краткий заголовок (3-5 слов) для чата на основе этого сообщения: {req.message}"
    try:
        title = get_gemini_response(prompt)
        return {"title": title.strip()}
    except Exception:
        return {"title": "Диалог"}

# ------------------------------------------------------------------
#  ВЕБ-ИНТЕРФЕЙС (HTML / CSS / JS)
# ------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def get_chat_ui():
    return """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>AI Web Interface</title>
        <style>
            body { font-family: system-ui, -apple-system, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 20px; display: flex; flex-direction: column; height: 100vh; box-sizing: border-box; }
            #chat-container { flex: 1; overflow-y: auto; background: #1e293b; border-radius: 12px; padding: 20px; margin-bottom: 20px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }
            .message { margin-bottom: 15px; padding: 12px 16px; border-radius: 8px; max-width: 80%; line-height: 1.5; }
            .user { background: #2563eb; color: white; margin-left: auto; }
            .bot { background: #334155; color: #f8fafc; margin-right: auto; white-space: pre-wrap; }
            #input-container { display: flex; gap: 10px; }
            textarea { flex: 1; background: #1e293b; border: 1px solid #475569; color: white; padding: 12px; border-radius: 8px; resize: none; height: 50px; font-family: inherit; }
            button { background: #2563eb; color: white; border: none; padding: 0 24px; border-radius: 8px; font-weight: 600; cursor: pointer; transition: background 0.2s; }
            button:hover { background: #1d4ed8; }
        </style>
    </head>
    <body>
        <div id="chat-container"></div>
        <div id="input-container">
            <textarea id="prompt-input" placeholder="Введите ваш запрос..."></textarea>
            <button onclick="sendMessage()">Отправить</button>
        </div>

        <script>
            async function sendMessage() {
                const input = document.getElementById('prompt-input');
                const text = input.value.trim();
                if (!text) return;

                const chat = document.getElementById('chat-container');
                chat.innerHTML += `<div class="message user">${text}</div>`;
                input.value = '';
                chat.scrollTop = chat.scrollHeight;

                const botMsg = document.createElement('div');
                botMsg.className = 'message bot';
                botMsg.textContent = 'Думаю...';
                chat.appendChild(botMsg);
                chat.scrollTop = chat.scrollHeight;

                try {
                    const res = await fetch('/api/chat', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ prompt: text })
                    });
                    const data = await res.json();
                    botMsg.textContent = data.response || data.detail || 'Произошла ошибка';
                } catch (e) {
                    botMsg.textContent = 'Ошибка подключения к серверу.';
                }
                chat.scrollTop = chat.scrollHeight;
            }
        </script>
    </body>
    </html>
    """

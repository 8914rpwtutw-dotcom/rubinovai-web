import os
import uuid
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from google import genai
from google.genai.errors import APIError

app = FastAPI()

SERVER_BUILD_ID = str(uuid.uuid4())[:8]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# ------------------------------------------------------------------
#  БЛОК РОТАЦИИ КЛЮЧЕЙ И МОДЕЛЕЙ (google-genai SDK)
# ------------------------------------------------------------------

# Собираем ключи из переменных окружения
API_KEYS = [
    os.getenv("GEMINI_KEY_1"),
    os.getenv("GEMINI_KEY_2"),
    os.getenv("GEMINI_KEY_3"),
    os.getenv("GEMINI_API_KEY")  # на случай дефолтного имени
]
# Оставляем только заполненные
API_KEYS = [k for k in API_KEYS if k]

# Приоритет моделей
MODELS_PRIORITY = [
    "gemini-2.0-flash",
    "gemini-1.5-flash"
]

current_key_index = 0

def get_gemini_response(prompt: str) -> str:
    """Генерация ответа с ротацией ключей и моделей"""
    global current_key_index
    
    if not API_KEYS:
        raise HTTPException(
            status_code=500, 
            detail="API-ключи не найдены. Добавьте GEMINI_KEY_1 в Environment Variables на Render."
        )
        
    total_keys = len(API_KEYS)
    keys_tried = 0

    while keys_tried < total_keys:
        active_key = API_KEYS[current_key_index]
        
        # Создаем клиента с конкретным ключом
        client = genai.Client(api_key=active_key)
        
        for model_name in MODELS_PRIORITY:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                return response.text
                
            except APIError as e:
                # Если 429 (ResourceExhausted / Rate Limit) — пробуем следующую модель/ключ
                if e.code == 429 or "RESOURCE_EXHAUSTED" in str(e):
                    print(f"[Gemini] Модель {model_name} исчерпала лимит на ключе #{current_key_index + 1}.")
                    continue
                else:
                    print(f"[Gemini API Error] {e}")
                    break
            except Exception as e:
                print(f"[Unexpected Error] {e}")
                break

        # Переключаем ключ
        print(f"[Gemini] Переключаем API-ключ с #{current_key_index + 1}...")
        current_key_index = (current_key_index + 1) % total_keys
        keys_tried += 1

    raise HTTPException(
        status_code=429, 
        detail="Все API-ключи и модели исчерпали лимиты. Попробуйте позже."
    )

# ------------------------------------------------------------------
#  СХЕМЫ ДАННЫХ И API ЭНДПОИНТЫ
# ------------------------------------------------------------------

class TitleRequest(BaseModel):
    message: str

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
        
    prompt = f"Придумай краткий заголовок (3-5 слов) для чата на основе сообщения: {req.message}"
    try:
        title = get_gemini_response(prompt)
        return {"title": title.strip()}
    except Exception:
        return {"title": "Диалог"}

# ------------------------------------------------------------------
#  ВЕБ-ИНТЕРФЕЙС
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

# Запуск сервера uvicorn при вызове `python main.py`
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)

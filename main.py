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

# Порядок моделей для проверки
MODELS_PRIORITY = [
    "gemini-2.0-flash",
    "gemini-1.5-flash"
]

current_key_index = 0

def get_api_keys():
    """Собираем динамически все ключи из Environment Variables"""
    keys = [
        os.getenv("GEMINI_KEY_1"),
        os.getenv("GEMINI_KEY_2"),
        os.getenv("GEMINI_KEY_3"),
        os.getenv("GEMINI_API_KEY")
    ]
    return [k.strip() for k in keys if k and k.strip()]

def get_gemini_response(prompt: str, model_override: str = None) -> str:
    """Генерация ответа с ротацией ключей и моделей"""
    global current_key_index
    
    api_keys = get_api_keys()
    if not api_keys:
        raise HTTPException(
            status_code=500, 
            detail="API-ключи не найдены. Укажите GEMINI_KEY_1 и GEMINI_KEY_2 в Environment Variables на Render."
        )
        
    total_keys = len(api_keys)
    keys_tried = 0
    
    # Определяем список моделей для обхода
    models_to_try = [model_override] if model_override else MODELS_PRIORITY

    while keys_tried < total_keys:
        active_key = api_keys[current_key_index % total_keys]
        
        try:
            client = genai.Client(api_key=active_key)
            
            for model_name in models_to_try:
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                    )
                    return response.text
                except APIError as e:
                    if e.code == 429 or "RESOURCE_EXHAUSTED" in str(e):
                        print(f"[Gemini] Лимит исчерпан для {model_name} на ключе #{current_key_index + 1}.")
                        continue
                    else:
                        print(f"[Gemini API Error] {e}")
                        break
                except Exception as e:
                    print(f"[Unexpected Error] {e}")
                    break
        except Exception as e:
            print(f"[Client Init Error] {e}")

        # Переключаем на следующий ключ
        current_key_index = (current_key_index + 1) % total_keys
        keys_tried += 1

    raise HTTPException(
        status_code=429, 
        detail="Оба API-ключа исчерпали бесплатные лимиты Google Gemini. Пожалуйста, подождите 1-2 минуты и повторите попытку."
    )

# ------------------------------------------------------------------
#  API ЭНДПОИНТЫ
# ------------------------------------------------------------------

class TitleRequest(BaseModel):
    message: str

class ChatPayload(BaseModel):
    prompt: str
    model: str = None

@app.get("/health")
def health_check():
    return {"status": "ok", "build_id": SERVER_BUILD_ID}

@app.post("/api/chat")
async def chat_endpoint(payload: ChatPayload):
    if not payload.prompt.strip():
        raise HTTPException(status_code=400, detail="Текст запроса не может быть пустым")
    
    answer = get_gemini_response(payload.prompt, payload.model)
    return {"response": answer}

@app.post("/api/generate-title")
async def generate_title(req: TitleRequest):
    if not req.message.strip():
        return {"title": "Новый диалог"}
        
    prompt = f"Придумай краткий заголовок (3-5 слов) для чата на основе сообщения: {req.message}"
    try:
        title = get_gemini_response(prompt)
        return {"title": title.strip().strip('"')}
    except Exception:
        return {"title": "Новый чат"}

# ------------------------------------------------------------------
#  ПОЛНОЦЕННЫЙ ВЕБ-ИНТЕРФЕЙС
# ------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def get_chat_ui():
    return """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Rubinov AI UI</title>
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #0f172a; color: #f8fafc; height: 100vh; display: flex; overflow: hidden; }
            
            /* Sidebar */
            #sidebar { width: 260px; background: #1e293b; border-right: 1px solid #334155; display: flex; flex-direction: column; padding: 15px; }
            .new-chat-btn { background: #2563eb; color: white; border: none; padding: 12px; border-radius: 8px; font-weight: 600; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 8px; transition: 0.2s; }
            .new-chat-btn:hover { background: #1d4ed8; }
            #history-list { flex: 1; overflow-y: auto; margin-top: 15px; display: flex; flex-direction: column; gap: 8px; }
            .history-item { padding: 10px; border-radius: 6px; background: #334155; cursor: pointer; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
            .history-item:hover { background: #475569; }

            /* Main Area */
            #main { flex: 1; display: flex; flex-direction: column; background: #0f172a; }
            #header { padding: 15px 20px; border-bottom: 1px solid #334155; display: flex; justify-content: space-between; align-items: center; }
            #model-select { background: #1e293b; color: white; border: 1px solid #475569; padding: 8px 12px; border-radius: 6px; outline: none; }

            #chat-container { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 15px; }
            .message { max-width: 80%; padding: 12px 16px; border-radius: 12px; line-height: 1.5; font-size: 15px; white-space: pre-wrap; }
            .user { background: #2563eb; color: white; align-self: flex-end; border-bottom-right-radius: 2px; }
            .bot { background: #1e293b; color: #f8fafc; align-self: flex-start; border-bottom-left-radius: 2px; border: 1px solid #334155; }
            .error { background: #7f1d1d; color: #fca5a5; border: 1px solid #991b1b; }

            #input-area { padding: 20px; border-top: 1px solid #334155; display: flex; gap: 10px; }
            textarea { flex: 1; background: #1e293b; border: 1px solid #475569; color: white; padding: 12px; border-radius: 8px; resize: none; height: 50px; font-family: inherit; outline: none; }
            textarea:focus { border-color: #2563eb; }
            #send-btn { background: #2563eb; color: white; border: none; width: 50px; height: 50px; border-radius: 8px; cursor: pointer; font-size: 18px; transition: 0.2s; }
            #send-btn:hover { background: #1d4ed8; }
        </style>
    </head>
    <body>
        <div id="sidebar">
            <button class="new-chat-btn" onclick="startNewChat()">
                <i class="fa-solid fa-plus"></i> Новый чат
            </button>
            <div id="history-list"></div>
        </div>

        <div id="main">
            <div id="header">
                <h3 id="chat-title">Новый диалог</h3>
                <select id="model-select">
                    <option value="gemini-2.0-flash">Gemini 2.0 Flash</option>
                    <option value="gemini-1.5-flash">Gemini 1.5 Flash</option>
                </select>
            </div>

            <div id="chat-container"></div>

            <div id="input-area">
                <textarea id="prompt-input" placeholder="Введите ваш запрос..." onkeydown="handleKey(event)"></textarea>
                <button id="send-btn" onclick="sendMessage()"><i class="fa-solid fa-paper-plane"></i></button>
            </div>
        </div>

        <script>
            let currentChatMessages = [];

            function handleKey(e) {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendMessage();
                }
            }

            function startNewChat() {
                document.getElementById('chat-container').innerHTML = '';
                document.getElementById('chat-title').textContent = 'Новый диалог';
                currentChatMessages = [];
            }

            async function sendMessage() {
                const input = document.getElementById('prompt-input');
                const text = input.value.trim();
                if (!text) return;

                const model = document.getElementById('model-select').value;
                const chat = document.getElementById('chat-container');

                // Сообщение пользователя
                chat.innerHTML += `<div class="message user">${escapeHtml(text)}</div>`;
                input.value = '';
                chat.scrollTop = chat.scrollHeight;

                // Индикатор ответа
                const botMsg = document.createElement('div');
                botMsg.className = 'message bot';
                botMsg.textContent = 'Думаю...';
                chat.appendChild(botMsg);
                chat.scrollTop = chat.scrollHeight;

                try {
                    const res = await fetch('/api/chat', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ prompt: text, model: model })
                    });
                    
                    const data = await res.json();
                    
                    if (res.ok) {
                        botMsg.textContent = data.response;
                        
                        // Если это первое сообщение — создаем заголовок
                        if (currentChatMessages.length === 0) {
                            generateChatTitle(text);
                        }
                        currentChatMessages.push({ user: text, bot: data.response });
                    } else {
                        botMsg.className = 'message bot error';
                        botMsg.textContent = data.detail || 'Произошла ошибка сервера';
                    }
                } catch (e) {
                    botMsg.className = 'message bot error';
                    botMsg.textContent = 'Ошибка подключения к серверу.';
                }
                
                chat.scrollTop = chat.scrollHeight;
            }

            async function generateChatTitle(firstMessage) {
                try {
                    const res = await fetch('/api/generate-title', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ message: firstMessage })
                    });
                    const data = await res.json();
                    if (data.title) {
                        document.getElementById('chat-title').textContent = data.title;
                        
                        // Добавляем в историю слева
                        const historyList = document.getElementById('history-list');
                        const item = document.createElement('div');
                        item.className = 'history-item';
                        item.textContent = data.title;
                        historyList.prepend(item);
                    }
                } catch (e) {
                    console.error(e);
                }
            }

            function escapeHtml(text) {
                return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
            }
        </script>
    </body>
    </html>
    """

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)

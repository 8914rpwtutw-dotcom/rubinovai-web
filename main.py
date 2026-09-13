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

# Модели в порядке приоритета для каждого ключа
MODELS = ["gemini-2.0-flash", "gemini-1.5-flash"]

# Глобальные индексы для точной последовательности
current_key_idx = 0
current_model_idx = 0

def get_api_keys():
    """Собираем валидные API-ключи"""
    keys = [
        os.getenv("GEMINI_KEY_1"),
        os.getenv("GEMINI_KEY_2"),
        os.getenv("GEMINI_API_KEY")
    ]
    valid_keys = [k.strip() for k in keys if k and k.strip()]
    return valid_keys

def get_gemini_response(prompt: str) -> str:
    """
    Каскадная логика:
    Ключ 1 -> gemini-2.0-flash
    Ключ 1 -> gemini-1.5-flash
    Ключ 2 -> gemini-2.0-flash
    Ключ 2 -> gemini-1.5-flash
    ... и по кругу заново
    """
    global current_key_idx, current_model_idx
    
    api_keys = get_api_keys()
    if not api_keys:
        raise HTTPException(
            status_code=500,
            detail="API-ключи не найдены в Environment Variables на Render."
        )

    num_keys = len(api_keys)
    num_models = len(MODELS)
    total_steps = num_keys * num_models
    steps_tried = 0

    while steps_tried < total_steps:
        # Текущий ключ и текущая модель
        active_key = api_keys[current_key_idx % num_keys]
        active_model = MODELS[current_model_idx % num_models]

        try:
            client = genai.Client(api_key=active_key)
            response = client.models.generate_content(
                model=active_model,
                contents=prompt
            )
            return response.text

        except APIError as e:
            if e.code == 429 or "RESOURCE_EXHAUSTED" in str(e):
                print(f"[Quota Exceeded] Ключ #{current_key_idx + 1}, модель {active_model} исчерпана. Переключаем...")
                
                # Логика сдвига: сначала пробуем 1.5 флеш на текущем ключе, затем следующий ключ
                current_model_idx += 1
                if current_model_idx >= num_models:
                    current_model_idx = 0
                    current_key_idx = (current_key_idx + 1) % num_keys
                
                steps_tried += 1
                continue
            else:
                print(f"[API Error] {e}")
                break
        except Exception as e:
            print(f"[Unexpected Error] {e}")
            break

        # В случае нетипичной ошибки переходим к следующему шагу
        current_model_idx += 1
        if current_model_idx >= num_models:
            current_model_idx = 0
            current_key_idx = (current_key_idx + 1) % num_keys
        steps_tried += 1

    raise HTTPException(
        status_code=429,
        detail="Все ключи и модели исчерпали лимиты. Попробуйте через 1-2 минуты."
    )

# ------------------------------------------------------------------
#  API ENDPOINTS
# ------------------------------------------------------------------

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

# ------------------------------------------------------------------
#  HTML/CSS/JS ИНТЕРФЕЙС (Точная копия интерфейса со скриншота)
# ------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def get_chat_ui():
    return """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Rubinov-AI Web</title>
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
            body { background: #050505; color: #e2e8f0; height: 100vh; display: flex; overflow: hidden; }

            /* Sidebar */
            #sidebar { width: 260px; background: #0b0d0f; border-right: 1px solid #1e232a; display: flex; flex-direction: column; padding: 16px; }
            .brand { margin-bottom: 20px; }
            .brand h2 { font-size: 16px; font-weight: 700; color: #ffffff; letter-spacing: 0.5px; }
            .brand span { font-size: 11px; color: #64748b; font-weight: 600; }

            .btn-new-chat { background: transparent; color: #ffffff; border: 1px solid #2a303c; padding: 10px 14px; border-radius: 20px; font-size: 13px; font-weight: 500; cursor: pointer; text-align: left; margin-bottom: 24px; transition: 0.2s; }
            .btn-new-chat:hover { background: #161b22; border-color: #3b4454; }

            .chats-header { display: flex; justify-content: space-between; font-size: 11px; color: #475569; font-weight: 700; margin-bottom: 12px; letter-spacing: 0.5px; }
            
            #chats-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; }
            .chat-item { background: #12161b; border: 1px solid #1e242d; border-radius: 10px; padding: 12px 14px; font-size: 13px; color: #e2e8f0; display: flex; justify-content: space-between; align-items: center; cursor: pointer; }
            .chat-item:hover { background: #1a2029; }
            .chat-item .close-btn { color: #64748b; font-size: 14px; cursor: pointer; }
            .chat-item .close-btn:hover { color: #ef4444; }

            .sidebar-footer { font-size: 12px; color: #64748b; display: flex; align-items: center; gap: 8px; margin-top: auto; padding-top: 12px; }
            .status-dot { width: 8px; height: 8px; background: #22c55e; border-radius: 50%; display: inline-block; }

            /* Main Chat Area */
            #main { flex: 1; display: flex; flex-direction: column; background: #000000; }
            
            #chat-header { height: 55px; border-bottom: 1px solid #14181d; display: flex; align-items: center; justify-content: space-between; padding: 0 24px; }
            #chat-header h3 { font-size: 15px; font-weight: 500; color: #e2e8f0; }
            .btn-clear { background: #12161b; color: #94a3b8; border: 1px solid #1e242d; padding: 6px 12px; border-radius: 6px; font-size: 12px; cursor: pointer; display: flex; align-items: center; gap: 6px; }
            .btn-clear:hover { background: #1a2029; color: #ffffff; }

            #chat-container { flex: 1; overflow-y: auto; padding: 24px; display: flex; flex-direction: column; gap: 20px; }
            
            /* Message Blocks */
            .msg-row { display: flex; width: 100%; }
            .msg-row.user-row { justify-content: flex-end; }
            .msg-row.bot-row { justify-content: flex-start; }

            .msg-user { background: #22262c; color: #ffffff; border-radius: 10px; padding: 12px 18px; font-size: 14px; max-width: 75%; }
            .msg-bot { background: #0c0e12; border: 1px solid #1e242d; color: #e2e8f0; border-radius: 12px; padding: 16px 20px; font-size: 14px; max-width: 85%; font-family: monospace; white-space: pre-wrap; line-height: 1.5; }
            .msg-error { background: #2a1215; border-color: #5c1d24; color: #f87171; }

            /* Input Area */
            #input-container { padding: 16px 24px 24px 24px; display: flex; gap: 12px; align-items: center; }
            #prompt-input { flex: 1; background: #0b0d0f; border: 1px solid #1e242d; border-radius: 12px; padding: 14px 18px; color: #ffffff; font-size: 14px; outline: none; transition: 0.2s; }
            #prompt-input:focus { border-color: #3b4454; }
            
            .btn-send { background: #22262c; color: #ffffff; border: 1px solid #333943; border-radius: 20px; padding: 12px 24px; font-size: 14px; font-weight: 500; cursor: pointer; transition: 0.2s; }
            .btn-send:hover { background: #333943; }
        </style>
    </head>
    <body>
        <div id="sidebar">
            <div class="brand">
                <h2>RUBINOV-AI</h2>
                <span>AI-ASSISTANT</span>
            </div>

            <button class="btn-new-chat" onclick="createNewChat()">+ Новый чат</button>

            <div class="chats-header">
                <span>ЧАТЫ</span>
                <span>MAX 5</span>
            </div>

            <div id="chats-list">
                <div class="chat-item">
                    <span>Закат в нейросети</span>
                    <span class="close-btn" onclick="deleteChat(this)">×</span>
                </div>
            </div>

            <div class="sidebar-footer">
                <span class="status-dot"></span>
                <span>Streaming Active</span>
            </div>
        </div>

        <div id="main">
            <div id="chat-header">
                <h3>Диалог</h3>
                <button class="btn-clear" onclick="clearMessages()">🗑 Очистить</button>
            </div>

            <div id="chat-container"></div>

            <div id="input-container">
                <input type="text" idprompt-input" id="prompt-input" placeholder="Введите сообщение..." onkeydown="handleKeyPress(event)" />
                <button class="btn-send" onclick="sendMessage()">Отправить</button>
            </div>
        </div>

        <script>
            function handleKeyPress(e) {
                if (e.key === 'Enter') {
                    sendMessage();
                }
            }

            function clearMessages() {
                document.getElementById('chat-container').innerHTML = '';
            }

            function createNewChat() {
                clearMessages();
            }

            function deleteChat(element) {
                element.parentElement.remove();
            }

            async function sendMessage() {
                const input = document.getElementById('prompt-input');
                const text = input.value.trim();
                if (!text) return;

                const chat = document.getElementById('chat-container');

                // Сообщение пользователя
                const userRow = document.createElement('div');
                userRow.className = 'msg-row user-row';
                userRow.innerHTML = `<div class="msg-user">${escapeHtml(text)}</div>`;
                chat.appendChild(userRow);
                
                input.value = '';
                chat.scrollTop = chat.scrollHeight;

                // Блок ответа бота
                const botRow = document.createElement('div');
                botRow.className = 'msg-row bot-row';
                const botMsg = document.createElement('div');
                botMsg.className = 'msg-bot';
                botMsg.textContent = 'Думаю...';
                botRow.appendChild(botMsg);
                chat.appendChild(botRow);
                chat.scrollTop = chat.scrollHeight;

                try {
                    const res = await fetch('/api/chat', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ prompt: text })
                    });
                    
                    const data = await res.json();

                    if (res.ok) {
                        botMsg.textContent = data.response;
                    } else {
                        botMsg.className = 'msg-bot msg-error';
                        botMsg.textContent = data.detail || 'Произошла ошибка при обработке запроса.';
                    }
                } catch (e) {
                    botMsg.className = 'msg-bot msg-error';
                    botMsg.textContent = 'Ошибка подключения к серверу.';
                }

                chat.scrollTop = chat.scrollHeight;
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

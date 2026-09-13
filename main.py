import os
import time
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

def get_gemini_response(prompt: str) -> str:
    global current_key_idx, current_model_idx
    
    api_keys = get_api_keys()
    if not api_keys:
        raise HTTPException(
            status_code=500,
            detail="API-ключи не найдены в Environment Variables."
        )

    num_keys = len(api_keys)
    num_models = len(MODELS)
    total_attempts = num_keys * num_models * 2

    last_error_msg = ""

    for attempt in range(total_attempts):
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
            last_error_msg = str(e)
            
            if e.code in [503, 429] or "RESOURCE_EXHAUSTED" in str(e) or "UNAVAILABLE" in str(e) or "high demand" in str(e).lower():
                current_model_idx += 1
                if current_model_idx >= num_models:
                    current_model_idx = 0
                    current_key_idx = (current_key_idx + 1) % num_keys
                
                time.sleep(0.5)
                continue
                
            elif e.code == 404 or "not found" in str(e).lower() or "no longer available" in str(e).lower():
                current_model_idx = (current_model_idx + 1) % num_models
                continue
            else:
                break
        except Exception as e:
            last_error_msg = str(e)
            break

    raise HTTPException(
        status_code=500,
        detail="Сервис ИИ перегружен в данный момент. Пожалуйста, повторите попытку через несколько секунд."
    )

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

@app.get("/", response_class=HTMLResponse)
async def get_chat_ui():
    return """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
        <title>Rubinov AI</title>
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
        <!-- Подключение библиотеки для обработки Markdown (выделения, отступы, списки) -->
        <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
        <style>
            :root {
                --bg-main: #090a0f;
                --bg-sidebar: #0f1117;
                --card-bg: #161822;
                --border-color: rgba(255, 255, 255, 0.08);
                --border-hover: rgba(255, 255, 255, 0.18);
                --accent: #6366f1;
                --accent-hover: #4f46e5;
                --text-main: #f8fafc;
                --text-muted: #94a3b8;
                --user-msg-bg: #1e2235;
                --bot-msg-bg: #11131c;
            }

            * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', -apple-system, sans-serif; -webkit-tap-highlight-color: transparent; }
            html, body { height: 100%; height: 100dvh; overflow: hidden; background: var(--bg-main); color: var(--text-main); }
            body { display: flex; position: relative; }

            /* Overlay for Mobile Sidebar */
            #sidebar-overlay {
                display: none;
                position: fixed;
                top: 0;
                left: 0;
                width: 100vw;
                height: 100dvh;
                background: rgba(0, 0, 0, 0.6);
                backdrop-filter: blur(4px);
                z-index: 40;
                opacity: 0;
                transition: opacity 0.3s ease;
            }
            #sidebar-overlay.active {
                display: block;
                opacity: 1;
            }

            /* Sidebar */
            #sidebar { 
                width: 280px; 
                background: var(--bg-sidebar); 
                border-right: 1px solid var(--border-color); 
                display: flex; 
                flex-direction: column; 
                padding: 20px 16px; 
                z-index: 50;
                transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                height: 100dvh;
            }
            .brand { 
                display: flex; 
                align-items: center; 
                gap: 12px; 
                margin-bottom: 24px; 
                padding: 0 4px;
            }
            .brand-logo { 
                width: 32px; 
                height: 32px; 
                background: linear-gradient(135deg, #6366f1, #a855f7); 
                border-radius: 10px; 
                display: flex; 
                align-items: center; 
                justify-content: center; 
                font-weight: 700; 
                font-size: 16px; 
                color: #fff;
                box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
            }
            .brand h2 { font-size: 15px; font-weight: 700; color: #ffffff; letter-spacing: -0.3px; }
            .brand span { font-size: 11px; color: var(--text-muted); font-weight: 500; display: block; }

            .btn-new-chat { 
                background: rgba(255, 255, 255, 0.04); 
                color: #ffffff; 
                border: 1px solid var(--border-color); 
                padding: 12px 16px; 
                border-radius: 12px; 
                font-size: 13px; 
                font-weight: 600; 
                cursor: pointer; 
                display: flex; 
                align-items: center; 
                gap: 8px; 
                margin-bottom: 24px; 
                transition: all 0.2s ease; 
            }
            .btn-new-chat:hover { 
                background: rgba(255, 255, 255, 0.08); 
                border-color: var(--border-hover); 
            }

            .chats-header { display: flex; justify-content: space-between; font-size: 11px; color: var(--text-muted); font-weight: 700; margin-bottom: 12px; padding: 0 4px; text-transform: uppercase; letter-spacing: 0.8px; }
            
            #chats-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
            .chat-item { 
                background: rgba(255, 255, 255, 0.02); 
                border: 1px solid var(--border-color); 
                border-radius: 10px; 
                padding: 10px 12px; 
                font-size: 13px; 
                color: #cbd5e1; 
                display: flex; 
                justify-content: space-between; 
                align-items: center; 
                cursor: pointer; 
                transition: all 0.2s;
            }
            .chat-item:hover { background: rgba(255, 255, 255, 0.06); color: #ffffff; border-color: var(--border-hover); }
            .chat-item .close-btn { color: var(--text-muted); font-size: 16px; cursor: pointer; border-radius: 4px; width: 20px; height: 20px; display: flex; align-items: center; justify-content: center; }
            .chat-item .close-btn:hover { color: #f87171; background: rgba(248, 113, 113, 0.1); }

            .sidebar-footer { font-size: 12px; color: var(--text-muted); display: flex; align-items: center; gap: 8px; margin-top: auto; padding-top: 16px; border-top: 1px solid var(--border-color); }
            .status-dot { width: 8px; height: 8px; background: #10b981; border-radius: 50%; box-shadow: 0 0 8px rgba(16, 185, 129, 0.5); }

            /* Main Area */
            #main { 
                flex: 1; 
                display: flex; 
                flex-direction: column; 
                background: var(--bg-main); 
                position: relative; 
                height: 100dvh; 
                overflow: hidden;
            }
            
            #chat-header { 
                height: 60px; 
                min-height: 60px;
                border-bottom: 1px solid var(--border-color); 
                display: flex; 
                align-items: center; 
                justify-content: space-between; 
                padding: 0 20px; 
                background: rgba(15, 17, 23, 0.85); 
                backdrop-filter: blur(12px);
                z-index: 10;
            }
            .header-left { display: flex; align-items: center; gap: 12px; }
            .menu-toggle {
                display: none;
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid var(--border-color);
                color: #ffffff;
                border-radius: 8px;
                padding: 8px;
                cursor: pointer;
                align-items: center;
                justify-content: center;
            }
            #chat-header h3 { font-size: 15px; font-weight: 600; color: #ffffff; }
            
            .btn-clear { 
                background: rgba(255, 255, 255, 0.05); 
                color: var(--text-muted); 
                border: 1px solid var(--border-color); 
                padding: 8px 14px; 
                border-radius: 8px; 
                font-size: 12px; 
                font-weight: 500;
                cursor: pointer; 
                transition: all 0.2s;
            }
            .btn-clear:hover { background: rgba(255, 255, 255, 0.1); color: #ffffff; }

            /* Chat Messages Container */
            #chat-container { 
                flex: 1; 
                overflow-y: auto; 
                padding: 20px 20px 120px 20px; 
                display: flex; 
                flex-direction: column; 
                gap: 20px; 
                max-width: 900px;
                width: 100%;
                margin: 0 auto;
            }
            
            /* Message Blocks */
            .msg-row { display: flex; width: 100%; animation: fadeIn 0.25s ease-out; }
            .msg-row.user-row { justify-content: flex-end; }
            .msg-row.bot-row { justify-content: flex-start; }

            @keyframes fadeIn {
                from { opacity: 0; transform: translateY(6px); }
                to { opacity: 1; transform: translateY(0); }
            }

            .msg-user { 
                background: var(--user-msg-bg); 
                color: #ffffff; 
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 16px 16px 4px 16px; 
                padding: 12px 16px; 
                font-size: 14px; 
                line-height: 1.5;
                max-width: 85%; 
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
            }
            
            .msg-bot { 
                background: var(--bot-msg-bg); 
                border: 1px solid var(--border-color); 
                color: #e2e8f0; 
                border-radius: 16px 16px 16px 4px; 
                padding: 14px 18px; 
                font-size: 14px; 
                line-height: 1.6; 
                max-width: 90%; 
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
            }

            /* Красивое оформление Markdown для сообщений ИИ */
            .msg-bot p { margin-bottom: 12px; }
            .msg-bot p:last-child { margin-bottom: 0; }
            .msg-bot strong { color: #ffffff; font-weight: 700; }
            .msg-bot em { color: #cbd5e1; font-style: italic; }
            .msg-bot ul, .msg-bot ol { margin: 8px 0 12px 20px; padding-left: 8px; }
            .msg-bot li { margin-bottom: 4px; }
            .msg-bot h1, .msg-bot h2, .msg-bot h3, .msg-bot h4 { color: #ffffff; margin: 16px 0 8px 0; font-weight: 700; }
            .msg-bot h1 { font-size: 18px; }
            .msg-bot h2 { font-size: 16px; }
            .msg-bot h3 { font-size: 15px; }
            .msg-bot blockquote { border-left: 3px solid var(--accent); padding-left: 12px; margin: 8px 0; color: var(--text-muted); }
            .msg-bot code { background: rgba(255, 255, 255, 0.08); padding: 2px 6px; border-radius: 4px; font-family: monospace; font-size: 13px; color: #f472b6; }
            .msg-bot pre { background: #090a0f; padding: 12px; border-radius: 8px; overflow-x: auto; margin: 10px 0; border: 1px solid var(--border-color); }
            .msg-bot pre code { background: transparent; padding: 0; color: #e2e8f0; }
            
            .msg-error { background: rgba(239, 68, 68, 0.1); border-color: rgba(239, 68, 68, 0.3); color: #fca5a5; }

            .msg-bot.msg-thinking {
                padding: 8px 12px;
                border-radius: 10px;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                width: auto;
                background: var(--bot-msg-bg);
            }

            .thinking-indicator { display: flex; align-items: center; gap: 4px; }
            .thinking-dot { width: 5px; height: 5px; background-color: var(--accent); border-radius: 50%; animation: pulse 1.4s infinite ease-in-out both; }
            .thinking-dot:nth-child(1) { animation-delay: -0.32s; }
            .thinking-dot:nth-child(2) { animation-delay: -0.16s; }

            @keyframes pulse {
                0%, 80%, 100% { transform: scale(0.4); opacity: 0.3; }
                40% { transform: scale(1); opacity: 1; }
            }

            /* Fixed Bottom Input Area */
            #input-wrapper {
                position: absolute;
                bottom: 0;
                left: 0;
                right: 0;
                padding: 12px 16px;
                padding-bottom: calc(12px + env(safe-area-inset-bottom));
                background: linear-gradient(180deg, rgba(9, 10, 15, 0) 0%, rgba(9, 10, 15, 0.95) 40%, var(--bg-main) 100%);
                z-index: 20;
            }

            #input-container { 
                max-width: 900px;
                margin: 0 auto;
                background: var(--bg-sidebar); 
                border: 1px solid var(--border-color); 
                border-radius: 16px; 
                padding: 6px 6px 6px 14px; 
                display: flex; 
                gap: 8px; 
                align-items: center; 
                box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
            }
            #input-container:focus-within { 
                border-color: var(--accent); 
            }

            #prompt-input { 
                flex: 1; 
                background: transparent; 
                border: none; 
                color: #ffffff; 
                font-size: 15px; 
                outline: none; 
                min-width: 0;
            }
            #prompt-input::placeholder { color: var(--text-muted); }
            
            .btn-send { 
                background: var(--accent); 
                color: #ffffff; 
                border: none; 
                border-radius: 10px; 
                padding: 10px 16px; 
                font-size: 13px; 
                font-weight: 600; 
                cursor: pointer; 
                white-space: nowrap;
                transition: all 0.2s ease; 
                flex-shrink: 0;
            }

            /* Mobile Adaptations */
            @media (max-width: 768px) {
                #sidebar {
                    position: fixed;
                    top: 0;
                    left: 0;
                    transform: translateX(-100%);
                }
                #sidebar.open {
                    transform: translateX(0);
                }
                .menu-toggle {
                    display: flex;
                }
                #chat-header {
                    padding: 0 16px;
                }
                #chat-container {
                    padding: 16px 16px 100px 16px;
                }
            }
        </style>
    </head>
    <body>
        <div id="sidebar-overlay" onclick="toggleSidebar(false)"></div>

        <div id="sidebar">
            <div class="brand">
                <div class="brand-logo">R</div>
                <div>
                    <h2>Rubinov AI</h2>
                    <span>Next-Gen Assistant</span>
                </div>
            </div>

            <button class="btn-new-chat" onclick="createNewChat()">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 5v14M5 12h14"/></svg>
                Новый диалог
            </button>

            <div class="chats-header">
                <span>История</span>
            </div>

            <div id="chats-list">
                <div class="chat-item" onclick="toggleSidebar(false)">
                    <span>Текущая сессия</span>
                    <span class="close-btn" onclick="event.stopPropagation(); deleteChat(this)">×</span>
                </div>
            </div>

            <div class="sidebar-footer">
                <span class="status-dot"></span>
                <span>Онлайн • Gemini API</span>
            </div>
        </div>

        <div id="main">
            <div id="chat-header">
                <div class="header-left">
                    <button class="menu-toggle" onclick="toggleSidebar(true)">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 6h16M4 12h16M4 18h16"/></svg>
                    </button>
                    <h3>Диалог</h3>
                </div>
                <button class="btn-clear" onclick="clearMessages()">Очистить</button>
            </div>

            <div id="chat-container"></div>

            <div id="input-wrapper">
                <div id="input-container">
                    <input type="text" id="prompt-input" placeholder="Спросите что-нибудь..." onkeydown="handleKeyPress(event)" />
                    <button class="btn-send" onclick="sendMessage()">Отправить</button>
                </div>
            </div>
        </div>

        <script>
            function toggleSidebar(open) {
                const sidebar = document.getElementById('sidebar');
                const overlay = document.getElementById('sidebar-overlay');
                
                if (open) {
                    sidebar.classList.add('open');
                    overlay.classList.add('active');
                } else {
                    sidebar.classList.remove('open');
                    overlay.classList.remove('active');
                }
            }

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
                toggleSidebar(false);
            }

            function deleteChat(element) {
                element.parentElement.remove();
            }

            async function sendMessage() {
                const input = document.getElementById('prompt-input');
                const text = input.value.trim();
                if (!text) return;

                const chat = document.getElementById('chat-container');

                const userRow = document.createElement('div');
                userRow.className = 'msg-row user-row';
                userRow.innerHTML = `<div class="msg-user">${escapeHtml(text)}</div>`;
                chat.appendChild(userRow);
                
                input.value = '';
                chat.scrollTop = chat.scrollHeight;

                const botRow = document.createElement('div');
                botRow.className = 'msg-row bot-row';
                const botMsg = document.createElement('div');
                botMsg.className = 'msg-bot msg-thinking';
                
                botMsg.innerHTML = `
                    <div class="thinking-indicator">
                        <div class="thinking-dot"></div>
                        <div class="thinking-dot"></div>
                        <div class="thinking-dot"></div>
                    </div>
                `;
                
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

                    botMsg.className = 'msg-bot';

                    if (res.ok) {
                        // Рендерим Markdown в чистый HTML через библиотеку marked
                        botMsg.innerHTML = marked.parse(data.response);
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

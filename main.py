import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from google import genai

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

client = genai.Client()

class ChatRequest(BaseModel):
    message: str
    model: str = "gemini-3.1-flash-lite"
    history: list = []

@app.get("/", response_class=HTMLResponse)
async def get_chat_ui():
    return """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>RubinovAi v8.4 Pro</title>
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
            body { background: #0b0f19; color: #f8fafc; display: flex; height: 100vh; overflow: hidden; }
            
            /* Sidebar */
            .sidebar { width: 280px; background: #111827; display: flex; flex-direction: column; border-right: 1px solid #1f2937; padding: 16px; }
            .logo-area { margin-bottom: 24px; }
            .logo-title { font-size: 1.1rem; font-weight: bold; letter-spacing: 0.5px; color: #fff; }
            .logo-subtitle { font-size: 0.75rem; color: #38bdf8; font-weight: 600; margin-top: 4px; }
            
            .new-chat-btn { background: #0284c7; color: white; border: none; padding: 10px 14px; border-radius: 8px; font-weight: 600; cursor: pointer; text-align: left; margin-bottom: 16px; transition: background 0.2s; display: flex; align-items: center; gap: 8px; }
            .new-chat-btn:hover { background: #0369a1; }
            
            .chats-section-title { font-size: 0.75rem; text-transform: uppercase; color: #94a3b8; margin-bottom: 8px; font-weight: bold; display: flex; justify-content: space-between; align-items: center; }
            .chats-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; margin-bottom: 16px; }
            .chat-item { padding: 10px 12px; border-radius: 6px; cursor: pointer; background: #1f2937; color: #cbd5e1; font-size: 0.9rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; transition: background 0.2s; }
            .chat-item:hover { background: #374151; color: #fff; }
            .chat-item.active { background: #0284c7; color: #fff; font-weight: 500; }
            
            .sidebar-footer { padding-top: 12px; border-top: 1px solid #1f2937; display: flex; align-items: center; gap: 8px; font-size: 0.85rem; color: #38bdf8; font-weight: 500; }
            .status-dot { width: 8px; height: 8px; background: #22c55e; border-radius: 50%; }

            /* Main Content */
            .main-content { flex: 1; display: flex; flex-direction: column; background: #0b0f19; }
            .top-nav { padding: 16px 24px; border-bottom: 1px solid #1f2937; display: flex; justify-content: space-between; align-items: center; background: #111827; }
            .top-title { font-weight: 600; font-size: 1rem; color: #e2e8f0; }
            .clear-btn { background: #1f2937; color: #cbd5e1; border: 1px solid #374151; padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 0.85rem; transition: background 0.2s; }
            .clear-btn:hover { background: #374151; color: #fff; }

            .chat-messages { flex: 1; padding: 24px; overflow-y: auto; display: flex; flex-direction: column; gap: 16px; }
            
            .welcome-card { background: #111827; border: 1px solid #1f2937; border-radius: 12px; padding: 20px; max-width: 600px; }
            .welcome-title { font-weight: bold; font-size: 1.1rem; margin-bottom: 8px; color: #fff; }
            .welcome-desc { color: #94a3b8; font-size: 0.9rem; line-height: 1.4; }

            .message { padding: 12px 16px; border-radius: 10px; max-width: 75%; line-height: 1.5; word-break: break-word; font-size: 0.95rem; }
            .message.user { background: #0284c7; color: white; align-self: flex-end; }
            .message.ai { background: #1e293b; color: #f1f5f9; align-self: flex-start; border: 1px solid #334155; }

            /* Input Area */
            .input-container { padding: 20px 24px; background: #0b0f19; }
            .input-box { background: #111827; border: 1px solid #1f2937; border-radius: 12px; display: flex; align-items: center; padding: 8px 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.2); }
            textarea { flex: 1; background: transparent; border: none; color: white; font-size: 0.95rem; resize: none; outline: none; max-height: 120px; padding: 6px; }
            .send-btn { background: #0284c7; color: white; border: none; padding: 8px 18px; border-radius: 8px; font-weight: bold; cursor: pointer; transition: background 0.2s; }
            .send-btn:hover { background: #0369a1; }
        </style>
    </head>
    <body>
        <div class="sidebar">
            <div class="logo-area">
                <div class="logo-title">RUBINOVAI</div>
                <div class="logo-subtitle">PRO WORKSPACE</div>
            </div>
            <button class="new-chat-btn" onclick="createNewChat()">+ Новый чат</button>
            <div class="chats-section-title">
                <span>Чаты</span>
                <span style="font-size: 0.7rem; color: #38bdf8;">Max 5</span>
            </div>
            <div id="chatsList" class="chats-list"></div>
            <div class="sidebar-footer">
                <div class="status-dot"></div>
                <span>Gemini-3.1 Active</span>
            </div>
        </div>

        <div class="main-content">
            <div class="top-nav">
                <div class="top-title">Диалоговое окно</div>
                <button class="clear-btn" onclick="clearCurrentChat()">🗑️ Очистить чат</button>
            </div>
            
            <div id="messages" class="chat-messages">
                <div class="welcome-card" id="welcomeCard">
                    <div class="welcome-title">Добро пожаловать в RubinovAi v8.4 🚀</div>
                    <div class="welcome-desc">Веб-версия успешно запущенна. Задавайте вопросы нейросети. С памятью и историей чатов.</div>
                </div>
            </div>

            <div class="input-container">
                <div class="input-box">
                    <textarea id="messageInput" placeholder="Введите сообщение... (Enter для отправки)" rows="1" onkeydown="handleKeyDown(event)"></textarea>
                    <button class="send-btn" onclick="sendMessage()">Отправить</button>
                </div>
            </div>
        </div>

        <script>
            let chats = JSON.parse(localStorage.getItem('rubinovai_chats')) || [{ id: 1, title: 'Новый чат', history: [] }];
            let activeChatId = Number(localStorage.getItem('rubinovai_active_id')) || chats[0].id;

            function saveState() {
                localStorage.setItem('rubinovai_chats', JSON.stringify(chats));
                localStorage.setItem('rubinovai_active_id', activeChatId);
            }

            function renderChats() {
                const list = document.getElementById('chatsList');
                list.innerHTML = '';
                chats.forEach(chat => {
                    const div = document.createElement('div');
                    div.className = `chat-item ${chat.id === activeChatId ? 'active' : ''}`;
                    div.innerText = chat.title;
                    div.onclick = () => switchChat(chat.id);
                    list.appendChild(div);
                });
                renderMessages();
            }

            function renderMessages() {
                const msgDiv = document.getElementById('messages');
                const chat = chats.find(c => c.id === activeChatId);
                
                if (!chat || chat.history.length === 0) {
                    msgDiv.innerHTML = `
                        <div class="welcome-card">
                            <div class="welcome-title">Добро пожаловать в RubinovAi v8.4 🚀</div>
                            <div class="welcome-desc">Веб-версия успешно запущенна. Задавайте вопросы нейросети. С памятью и историей чатов.</div>
                        </div>`;
                    return;
                }

                msgDiv.innerHTML = '';
                chat.history.forEach(m => {
                    const el = document.createElement('div');
                    el.className = `message ${m.role}`;
                    el.innerText = m.text;
                    msgDiv.appendChild(el);
                });
                msgDiv.scrollTop = msgDiv.scrollHeight;
            }

            function createNewChat() {
                if (chats.length >= 5) {
                    alert('Достигнут лимит: максимум 5 чатов.');
                    return;
                }
                const newId = Date.now();
                chats.unshift({ id: newId, title: 'Новый чат', history: [] });
                activeChatId = newId;
                saveState();
                renderChats();
            }

            function switchChat(id) {
                activeChatId = id;
                saveState();
                renderChats();
            }

            function clearCurrentChat() {
                const chat = chats.find(c => c.id === activeChatId);
                if (chat) {
                    chat.history = [];
                    chat.title = 'Новый чат';
                    saveState();
                    renderChats();
                }
            }

            function handleKeyDown(e) {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendMessage();
                }
            }

            async function sendMessage() {
                const input = document.getElementById('messageInput');
                const text = input.value.trim();
                if (!text) return;

                let chat = chats.find(c => c.id === activeChatId);
                if (!chat) return;

                if (chat.history.length === 0) {
                    chat.title = text.length > 22 ? text.substring(0, 22) + '...' : text;
                }

                chat.history.push({ role: 'user', text: text });
                input.value = '';
                renderChats();

                try {
                    const response = await fetch('/api/chat', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ message: text, model: "gemini-3.1-flash-lite", history: chat.history })
                    });
                    const data = await response.json();
                    const replyText = data.reply || data.detail || 'Ошибка ответа';
                    chat.history.push({ role: 'ai', text: replyText });
                    saveState();
                    renderChats();
                } catch (err) {
                    chat.history.push({ role: 'ai', text: 'Ошибка соединения с сервером.' });
                    renderChats();
                }
            }

            renderChats();
        </script>
    </body>
    </html>
    """

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    try:
        # Передаем всю историю диалога для сохранения контекста (памяти)
        formatted_history = []
        for h in req.history[:-1]: # исключаем текущее сообщение, чтобы не дублировать
            role = "user" if h["role"] == "user" else "model"
            formatted_history.append({"role": role, "parts": [h["text"]]})

        chat_session = client.chats.create(model=req.model, history=formatted_history)
        response = chat_session.send_message(req.message)
        return {"reply": response.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

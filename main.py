import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from google import genai
from google.genai import types

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

client = genai.Client()

class ChatRequest(BaseModel):
    message: str
    model: str = "gemini-2.5-flash"
    history: list = []

@app.get("/", response_class=HTMLResponse)
async def get_chat_ui():
    return """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>RubinovAi Pro</title>
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
            
            .chat-item { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; border-radius: 6px; cursor: pointer; background: #1f2937; color: #cbd5e1; font-size: 0.9rem; transition: background 0.2s; }
            .chat-item:hover { background: #374151; color: #fff; }
            .chat-item.active { background: #0284c7; color: #fff; font-weight: 500; }
            
            .chat-title-text { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1; }
            .delete-chat-btn { background: transparent; border: none; color: #94a3b8; font-size: 1rem; cursor: pointer; padding: 0 4px; border-radius: 4px; transition: color 0.2s, background 0.2s; }
            .delete-chat-btn:hover { color: #f87171; background: rgba(255,255,255,0.05); }

            .sidebar-footer { padding-top: 12px; border-top: 1px solid #1f2937; display: flex; align-items: center; gap: 8px; font-size: 0.85rem; color: #38bdf8; font-weight: 500; }
            .status-dot { width: 8px; height: 8px; background: #22c55e; border-radius: 50%; }

            /* Main Content */
            .main-content { flex: 1; display: flex; flex-direction: column; background: #0b0f19; }
            .top-nav { padding: 16px 24px; border-bottom: 1px solid #1f2937; display: flex; justify-content: space-between; align-items: center; background: #111827; }
            .top-title { font-weight: 600; font-size: 1rem; color: #e2e8f0; display: flex; align-items: center; gap: 12px; }
            
            /* Status badge animation */
            .ai-status-badge { font-size: 0.75rem; background: rgba(56, 189, 248, 0.1); color: #38bdf8; padding: 5px 12px; border-radius: 20px; border: 1px solid rgba(56, 189, 248, 0.3); display: none; align-items: center; gap: 8px; font-weight: 600; letter-spacing: 0.5px; }
            .ai-status-badge.active { display: inline-flex; animation: pulseBadge 1.5s infinite; }
            
            @keyframes pulseBadge {
                0% { opacity: 0.6; box-shadow: 0 0 0 0 rgba(56, 189, 248, 0.4); }
                50% { opacity: 1; border-color: #38bdf8; box-shadow: 0 0 10px rgba(56, 189, 248, 0.2); }
                100% { opacity: 0.6; box-shadow: 0 0 0 0 rgba(56, 189, 248, 0.4); }
            }

            .clear-btn { background: #1f2937; color: #cbd5e1; border: 1px solid #374151; padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 0.85rem; transition: background 0.2s; }
            .clear-btn:hover { background: #374151; color: #fff; }

            .chat-messages { flex: 1; padding: 24px; overflow-y: auto; display: flex; flex-direction: column; gap: 16px; }
            
            /* Широкая приветственная карточка на всю ширину контейнера */
            .welcome-card { background: #111827; border: 1px solid #1f2937; border-radius: 12px; padding: 24px; width: 100%; }
            .welcome-title { font-weight: bold; font-size: 1.25rem; color: #fff; }

            .message { padding: 12px 16px; border-radius: 10px; max-width: 75%; line-height: 1.5; word-break: break-word; font-size: 0.95rem; animation: fadeIn 0.3s ease; }
            @keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }

            .message.user { background: #0284c7; color: white; align-self: flex-end; }
            .message.ai { background: #1e293b; color: #f1f5f9; align-self: flex-start; border: 1px solid #334155; }

            /* Typing Indicator Animation Box */
            .typing-indicator { display: none; align-self: flex-start; background: #1e293b; border: 1px solid #334155; padding: 12px 18px; border-radius: 10px; align-items: center; gap: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
            .typing-indicator.active { display: flex; animation: fadeIn 0.3s ease; }
            .typing-dot { width: 7px; height: 7px; background: #38bdf8; border-radius: 50%; animation: bounce 1.4s infinite ease-in-out both; }
            .typing-dot:nth-child(1) { animation-delay: -0.32s; }
            .typing-dot:nth-child(2) { animation-delay: -0.16s; }
            .typing-text { font-size: 0.8rem; color: #38bdf8; margin-left: 6px; font-weight: 700; letter-spacing: 0.5px; }

            @keyframes bounce {
                0%, 80%, 100% { transform: scale(0); }
                40% { transform: scale(1.15); }
            }

            /* Input Area */
            .input-container { padding: 20px 24px; background: #0b0f19; }
            .input-box { background: #111827; border: 1px solid #1f2937; border-radius: 12px; display: flex; align-items: center; padding: 8px 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.2); }
            textarea { flex: 1; background: transparent; border: none; color: white; font-size: 0.95rem; resize: none; outline: none; max-height: 120px; padding: 6px; }
            .send-btn { background: #0284c7; color: white; border: none; padding: 8px 18px; border-radius: 8px; font-weight: bold; cursor: pointer; transition: background 0.2s; }
            .send-btn:hover { background: #0369a1; }
            .send-btn:disabled { background: #334155; cursor: not-allowed; opacity: 0.7; }
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
                <span>Gemini Active</span>
            </div>
        </div>

        <div class="main-content">
            <div class="top-nav">
                <div class="top-title">
                    <span>Диалоговое окно</span>
                    <div id="aiStatusBadge" class="ai-status-badge">
                        <div class="typing-dot" style="width: 5px; height: 5px;"></div>
                        <span>РУБИНОВ АИ ДУМАЕТ...</span>
                    </div>
                </div>
                <button class="clear-btn" onclick="clearCurrentChat()">🗑️ Очистить чат</button>
            </div>
            
            <div id="messages" class="chat-messages">
                <div class="welcome-card" id="welcomeCard">
                    <div class="welcome-title">Добро пожаловать в RubinovAi 🚀</div>
                </div>
            </div>

            <!-- Typing indicator element -->
            <div style="padding: 0 24px 12px 24px;">
                <div id="typingIndicator" class="typing-indicator">
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <span class="typing-text">РУБИНОВ АИ ПЕЧАТАЕТ...</span>
                </div>
            </div>

            <div class="input-container">
                <div class="input-box">
                    <textarea id="messageInput" placeholder="Введите сообщение... (Enter для отправки)" rows="1" onkeydown="handleKeyDown(event)"></textarea>
                    <button id="sendBtn" class="send-btn" onclick="sendMessage()">Отправить</button>
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
                    
                    const titleSpan = document.createElement('span');
                    titleSpan.className = 'chat-title-text';
                    titleSpan.innerText = chat.title;
                    titleSpan.onclick = () => switchChat(chat.id);
                    
                    const deleteBtn = document.createElement('button');
                    deleteBtn.className = 'delete-chat-btn';
                    deleteBtn.innerHTML = '&times;';
                    deleteBtn.title = 'Удалить чат';
                    deleteBtn.onclick = (e) => {
                        e.stopPropagation();
                        deleteChat(chat.id);
                    };

                    div.appendChild(titleSpan);
                    div.appendChild(deleteBtn);
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
                            <div class="welcome-title">Добро пожаловать в RubinovAi 🚀</div>
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

            function setAiWorkingState(isWorking) {
                const badge = document.getElementById('aiStatusBadge');
                const indicator = document.getElementById('typingIndicator');
                const sendBtn = document.getElementById('sendBtn');
                const textarea = document.getElementById('messageInput');

                if (isWorking) {
                    badge.classList.add('active');
                    indicator.classList.add('active');
                    sendBtn.disabled = true;
                    textarea.disabled = true;
                } else {
                    badge.classList.remove('active');
                    indicator.classList.remove('active');
                    sendBtn.disabled = false;
                    textarea.disabled = false;
                    textarea.focus();
                }
                const msgDiv = document.getElementById('messages');
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

            function deleteChat(id) {
                if (chats.length <= 1) {
                    alert('Нужно оставить хотя бы один чат.');
                    return;
                }
                chats = chats.filter(c => c.id !== id);
                if (activeChatId === id) {
                    activeChatId = chats[0].id;
                }
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

                setAiWorkingState(true);

                try {
                    const response = await fetch('/api/chat', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ message: text, model: "gemini-2.5-flash", history: chat.history })
                    });
                    const data = await response.json();
                    const replyText = data.reply || data.detail || 'Ошибка ответа';
                    chat.history.push({ role: 'ai', text: replyText });
                    saveState();
                    renderChats();
                } catch (err) {
                    chat.history.push({ role: 'ai', text: 'Ошибка соединения с сервером.' });
                    renderChats();
                } finally {
                    setAiWorkingState(false);
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
        formatted_history = []
        for h in req.history[:-1]:
            role = "user" if h["role"] == "user" else "model"
            formatted_history.append(
                types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=h["text"])]
                )
            )

        chat_session = client.chats.create(model=req.model, history=formatted_history)
        response = chat_session.send_message(req.message)
        return {"reply": response.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

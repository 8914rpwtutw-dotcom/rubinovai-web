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
        <title>Rubinov-AI AI-Assistant</title>
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
            body { background: #000000; color: #b5b5b5; display: flex; height: 100dvh; overflow: hidden; position: relative; }
            
            /* Sidebar */
            .sidebar { width: 280px; background: #080808; display: flex; flex-direction: column; border-right: 1px solid #1a1a1a; padding: 16px; transition: transform 0.3s ease; z-index: 100; }
            .logo-area { margin-bottom: 24px; display: flex; justify-content: space-between; align-items: center; }
            .logo-title { font-size: 1.1rem; font-weight: bold; letter-spacing: 0.5px; color: #cccccc; }
            .logo-subtitle { font-size: 0.75rem; color: #666666; font-weight: 600; margin-top: 4px; }
            
            .close-sidebar-btn { display: none; background: transparent; border: none; color: #888; font-size: 1.2rem; cursor: pointer; }

            .new-chat-btn { background: #262626; color: #d0d0d0; border: 1px solid #333; padding: 10px 14px; border-radius: 8px; font-weight: 600; cursor: pointer; text-align: left; margin-bottom: 16px; transition: background 0.2s; display: flex; align-items: center; gap: 8px; }
            .new-chat-btn:hover { background: #333333; color: #ffffff; }
            
            .chats-section-title { font-size: 0.75rem; text-transform: uppercase; color: #595959; margin-bottom: 8px; font-weight: bold; display: flex; justify-content: space-between; align-items: center; }
            .chats-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; margin-bottom: 16px; }
            
            .chat-item { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; border-radius: 6px; cursor: pointer; background: #121212; color: #8c8c8c; font-size: 0.9rem; transition: background 0.2s, color 0.2s; }
            .chat-item:hover { background: #1a1a1a; color: #b5b5b5; }
            .chat-item.active { background: #262626; color: #e0e0e0; font-weight: 500; border: 1px solid #383838; }
            
            .chat-title-text { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1; }
            .delete-chat-btn { background: transparent; border: none; color: #595959; font-size: 1rem; cursor: pointer; padding: 0 4px; border-radius: 4px; transition: color 0.2s, background 0.2s; }
            .delete-chat-btn:hover { color: #cccccc; background: rgba(255,255,255,0.08); }

            .sidebar-footer { padding-top: 12px; border-top: 1px solid #1a1a1a; display: flex; align-items: center; gap: 8px; font-size: 0.85rem; color: #595959; font-weight: 500; }
            .status-dot { width: 8px; height: 8px; background: #737373; border-radius: 50%; }

            /* Main Content */
            .main-content { flex: 1; display: flex; flex-direction: column; background: #000000; width: 100%; overflow: hidden; }
            .top-nav { padding: 16px 20px; border-bottom: 1px solid #1a1a1a; display: flex; justify-content: space-between; align-items: center; background: #080808; gap: 10px; }
            
            .top-left-group { display: flex; align-items: center; gap: 12px; overflow: hidden; }
            .menu-btn { display: none; background: #121212; border: 1px solid #222; color: #b5b5b5; font-size: 1.1rem; padding: 6px 10px; border-radius: 6px; cursor: pointer; }

            .top-title { font-weight: 600; font-size: 0.95rem; color: #b5b5b5; display: flex; align-items: center; gap: 10px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
            
            .ai-status-badge { font-size: 0.7rem; background: rgba(255, 255, 255, 0.03); color: #a6a6a6; padding: 4px 10px; border-radius: 20px; border: 1px solid rgba(255, 255, 255, 0.1); display: none; align-items: center; gap: 6px; font-weight: 600; }
            .ai-status-badge.active { display: inline-flex; animation: pulseBadge 1.5s infinite; }
            
            @keyframes pulseBadge {
                0% { opacity: 0.5; box-shadow: 0 0 0 0 rgba(150, 150, 150, 0.1); }
                50% { opacity: 1; border-color: #888888; box-shadow: 0 0 8px rgba(150, 150, 150, 0.08); }
                100% { opacity: 0.5; box-shadow: 0 0 0 0 rgba(150, 150, 150, 0.1); }
            }

            .clear-btn { background: #121212; color: #8c8c8c; border: 1px solid #222222; padding: 6px 10px; border-radius: 6px; cursor: pointer; font-size: 0.8rem; white-space: nowrap; transition: background 0.2s, color 0.2s; }
            .clear-btn:hover { background: #1a1a1a; color: #b5b5b5; }

            .chat-messages { flex: 1; padding: 20px; overflow-y: auto; display: flex; flex-direction: column; gap: 16px; justify-content: center; align-items: center; }
            
            /* Welcome Area & Starter Chips */
            .welcome-container { display: flex; flex-direction: column; align-items: center; gap: 16px; max-width: 480px; width: 100%; text-align: center; }
            .welcome-card { background: #080808; border: 1px solid #1a1a1a; border-radius: 12px; padding: 18px 20px; width: 100%; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }
            .welcome-title { font-weight: 600; font-size: 0.95rem; color: #cccccc; letter-spacing: 0.3px; margin-bottom: 4px; }
            .welcome-subtitle { font-size: 0.8rem; color: #595959; }

            .chips-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; width: 100%; }
            .chip { background: #0a0a0a; border: 1px solid #1c1c1c; border-radius: 10px; padding: 10px 14px; color: #8c8c8c; font-size: 0.82rem; cursor: pointer; text-align: left; transition: all 0.2s ease; display: flex; align-items: center; gap: 8px; user-select: none; }
            .chip:hover { background: #141414; border-color: #333333; color: #cccccc; transform: translateY(-1px); }

            .message { 
                padding: 12px 16px; 
                border-radius: 10px; 
                max-width: 85%; 
                line-height: 1.5; 
                overflow-wrap: break-word; 
                word-break: normal; 
                white-space: pre-wrap; 
                font-size: 0.95rem; 
                animation: fadeIn 0.3s ease; 
                align-self: flex-start; 
            }
            @keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }

            /* ТЕМНО-СЕРЫЕ сообщения пользователя */
            .message.user { 
                background: #242424 !important; 
                color: #e0e0e0 !important; 
                align-self: flex-end; 
                font-weight: 400; 
                border: 1px solid #333333; 
            }
            
            .message.ai { 
                background: #0e0e0e; 
                color: #b5b5b5; 
                border: 1px solid #222222; 
            }

            .typing-indicator { display: none; align-self: flex-start; background: #0e0e0e; border: 1px solid #222222; padding: 12px 16px; border-radius: 10px; align-items: center; gap: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.3); }
            .typing-indicator.active { display: flex; animation: fadeIn 0.3s ease; }
            .typing-dot { width: 7px; height: 7px; background: #888888; border-radius: 50%; animation: bounce 1.4s infinite ease-in-out both; }
            .typing-dot:nth-child(1) { animation-delay: -0.32s; }
            .typing-dot:nth-child(2) { animation-delay: -0.16s; }
            .typing-text { font-size: 0.75rem; color: #666666; margin-left: 4px; font-weight: 700; letter-spacing: 0.5px; }

            @keyframes bounce {
                0%, 80%, 100% { transform: scale(0); }
                40% { transform: scale(1.15); }
            }

            .input-container { padding: 16px 20px; background: #000000; }
            .input-box { background: #080808; border: 1px solid #1a1a1a; border-radius: 12px; display: flex; align-items: center; padding: 6px 10px; box-shadow: 0 4px 12px rgba(0,0,0,0.3); }
            textarea { flex: 1; background: transparent; border: none; color: #b5b5b5; font-size: 0.95rem; resize: none; outline: none; max-height: 120px; padding: 6px; }
            textarea::placeholder { color: #4a4a4a; }
            
            .send-btn { background: #262626; color: #d0d0d0; border: 1px solid #333; padding: 8px 16px; border-radius: 8px; font-weight: bold; cursor: pointer; transition: background 0.2s; font-size: 0.9rem; }
            .send-btn:hover { background: #333333; color: #ffffff; }
            .send-btn:disabled { background: #161616; color: #444444; border-color: #222; cursor: not-allowed; }

            @media (max-width: 768px) {
                .sidebar { position: absolute; height: 100%; left: 0; top: 0; transform: translateX(-100%); box-shadow: 10px 0 30px rgba(0,0,0,0.8); }
                .sidebar.open { transform: translateX(0); }
                .close-sidebar-btn { display: block; }
                .menu-btn { display: inline-flex; align-items: center; justify-content: center; }
                .ai-status-badge { display: none !important; }
                .chips-grid { grid-template-columns: 1fr; }
            }
        </style>
    </head>
    <body>
        <div id="sidebar" class="sidebar">
            <div class="logo-area">
                <div>
                    <div class="logo-title">RUBINOV-AI</div>
                    <div class="logo-subtitle">AI-ASSISTANT</div>
                </div>
                <button class="close-sidebar-btn" onclick="toggleSidebar()">&times;</button>
            </div>
            <button class="new-chat-btn" onclick="createNewChat()">+ Новый чат</button>
            <div class="chats-section-title">
                <span>Чаты</span>
                <span style="font-size: 0.7rem; color: #595959;">Max 5</span>
            </div>
            <div id="chatsList" class="chats-list"></div>
            <div class="sidebar-footer">
                <div class="status-dot"></div>
                <span>Flash-Lite Active</span>
            </div>
        </div>

        <div class="main-content">
            <div class="top-nav">
                <div class="top-left-group">
                    <button class="menu-btn" onclick="toggleSidebar()">☰</button>
                    <div class="top-title">
                        <span>Диалог</span>
                        <div id="aiStatusBadge" class="ai-status-badge">
                            <div class="typing-dot" style="width: 5px; height: 5px; background: #888888;"></div>
                            <span>ДУМАЕТ...</span>
                        </div>
                    </div>
                </div>
                <button class="clear-btn" onclick="clearCurrentChat()">🗑️ Очистить</button>
            </div>
            
            <div id="messages" class="chat-messages">
                <!-- Заполняется динамически через renderMessages -->
            </div>

            <div style="padding: 0 20px 8px 20px;">
                <div id="typingIndicator" class="typing-indicator">
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <span class="typing-text">РУБИНОВ АИ ПЕЧАТАЕТ...</span>
                </div>
            </div>

            <div class="input-container">
                <div class="input-box">
                    <textarea id="messageInput" placeholder="Введите сообщение..." rows="1" onkeydown="handleKeyDown(event)"></textarea>
                    <button id="sendBtn" class="send-btn" onclick="sendMessage()">Отправить</button>
                </div>
            </div>
        </div>

        <script>
            let chats = JSON.parse(localStorage.getItem('rubinovai_chats_mono_v14')) || [{ id: 1, title: 'Новый чат', history: [] }];
            let activeChatId = Number(localStorage.getItem('rubinovai_active_id_mono_v14')) || chats[0].id;

            function saveState() {
                localStorage.setItem('rubinovai_chats_mono_v14', JSON.stringify(chats));
                localStorage.setItem('rubinovai_active_id_mono_v14', activeChatId);
            }

            function toggleSidebar() {
                const sidebar = document.getElementById('sidebar');
                sidebar.classList.toggle('open');
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
                    titleSpan.onclick = () => {
                        switchChat(chat.id);
                        if (window.innerWidth <= 768) toggleSidebar();
                    };
                    
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
                        <div class="welcome-container">
                            <div class="welcome-card">
                                <div class="welcome-title">Добро пожаловать в Rubinov-AI 🚀</div>
                                <div class="welcome-subtitle">Выберите быстрый запрос или напишите свой ниже</div>
                            </div>
                            <div class="chips-grid">
                                <div class="chip" onclick="sendChip('Придумай идею для проекта')">💡 Идея для проекта</div>
                                <div class="chip" onclick="sendChip('Напиши код на Python / FastAPI')">💻 Код на FastAPI</div>
                                <div class="chip" onclick="sendChip('Напиши текст или статью')">✍️ Написать текст</div>
                                <div class="chip" onclick="sendChip('Объясни сложную концепцию простыми словами')">📊 Объяснить концепцию</div>
                            </div>
                        </div>`;
                    msgDiv.style.justifyContent = 'center';
                    return;
                }

                msgDiv.style.justifyContent = 'flex-start';
                msgDiv.innerHTML = '';
                chat.history.forEach(m => {
                    const el = document.createElement('div');
                    el.className = `message ${m.role}`;
                    el.innerText = m.text;
                    msgDiv.appendChild(el);
                });
                msgDiv.scrollTop = msgDiv.scrollHeight;
            }

            function sendChip(text) {
                const input = document.getElementById('messageInput');
                input.value = text.trim();
                setTimeout(() => {
                    sendMessage();
                }, 50);
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

            function typeWriterEffect(element, text, speed = 8, callback) {
                let i = 0;
                element.innerText = '';
                function type() {
                    if (i < text.length) {
                        element.innerText += text.charAt(i);
                        i++;
                        const msgDiv = document.getElementById('messages');
                        msgDiv.scrollTop = msgDiv.scrollHeight;
                        setTimeout(type, speed);
                    } else {
                        if (callback) callback();
                    }
                }
                type();
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
                if (window.innerWidth <= 768) toggleSidebar();
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

                if (chat.history.length === 0 && chat.title === 'Новый чат') {
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
                        body: JSON.stringify({ message: text, model: "gemini-3.1-flash-lite", history: chat.history })
                    });
                    const data = await response.json();
                    const replyText = data.reply || data.detail || 'Ошибка ответа';
                    
                    setAiWorkingState(false);
                    
                    const msgDiv = document.getElementById('messages');
                    const aiElement = document.createElement('div');
                    aiElement.className = 'message ai';
                    msgDiv.appendChild(aiElement);

                    typeWriterEffect(aiElement, replyText, 8, () => {
                        chat.history.push({ role: 'ai', text: replyText });
                        saveState();
                    });

                } catch (err) {
                    setAiWorkingState(false);
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
        formatted_history = []
        # Передаем все предыдущие сообщения для полноценного контекста (кроме текущего сообщения, которое отправляется через send_message)
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

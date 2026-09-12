import os
import json
import base64
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from google import genai
from google.genai import types

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

client = genai.Client()

DEFAULT_MODEL = "gemini-2.5-flash"
IMAGE_MODEL = "imagen-3.0-generate-002"

class TitleRequest(BaseModel):
    message: str

@app.get("/", response_class=HTMLResponse)
async def get_chat_ui():
    return """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Rubinov-AI Multimodal Assistant</title>
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
            body { background: #000000; color: #b5b5b5; display: flex; height: 100dvh; overflow: hidden; position: relative; }
            
            /* Экран обновления (оверлей) */
            .update-overlay {
                position: fixed;
                top: 0; left: 0; width: 100%; height: 100%;
                background: rgba(0, 0, 0, 0.85);
                backdrop-filter: blur(8px);
                z-index: 9999;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                gap: 16px;
                opacity: 0;
                pointer-events: none;
                transition: opacity 0.3s ease;
            }
            .update-overlay.active {
                opacity: 1;
                pointer-events: auto;
            }
            .update-spinner {
                width: 48px;
                height: 48px;
                border: 3px solid rgba(255, 255, 255, 0.1);
                border-top-color: #ffffff;
                border-radius: 50%;
                animation: spin 0.8s linear infinite;
            }
            .update-text {
                font-size: 1.1rem;
                font-weight: 600;
                color: #ffffff;
                letter-spacing: 0.5px;
            }
            .update-subtext {
                font-size: 0.85rem;
                color: #777777;
            }
            @keyframes spin {
                to { transform: rotate(360deg); }
            }

            /* Sidebar */
            .sidebar { width: 280px; background: #080808; display: flex; flex-direction: column; border-right: 1px solid #1a1a1a; padding: 16px; transition: transform 0.3s ease; z-index: 100; }
            .logo-area { margin-bottom: 24px; display: flex; justify-content: space-between; align-items: center; padding: 0 8px; }
            .logo-title { font-size: 1.1rem; font-weight: bold; letter-spacing: 0.5px; color: #cccccc; }
            .logo-subtitle { font-size: 0.75rem; color: #666666; font-weight: 600; margin-top: 4px; }
            
            .close-sidebar-btn { display: none; background: transparent; border: none; color: #888; font-size: 1.2rem; cursor: pointer; }

            .new-chat-btn { 
                background: transparent; color: #d0d0d0; border: 1px solid #222; padding: 10px 14px; 
                border-radius: 20px; font-weight: 600; cursor: pointer; text-align: left; margin-bottom: 16px; 
                transition: background 0.2s ease, border-color 0.2s ease; display: flex; align-items: center; gap: 8px; 
            }
            .new-chat-btn:hover { background: #181818; border-color: #333333; color: #ffffff; }
            
            .chats-section-title { font-size: 0.75rem; text-transform: uppercase; color: #595959; margin-bottom: 8px; font-weight: bold; padding: 0 8px; }
            .chats-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 4px; margin-bottom: 16px; }
            
            .chat-item { 
                display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; 
                border-radius: 20px; cursor: pointer; background: transparent; color: #8c8c8c; font-size: 0.9rem; 
                transition: background 0.2s ease, color 0.2s ease; border: 1px solid transparent;
            }
            .chat-item:hover { background: #141414; color: #b5b5b5; }
            .chat-item.active { background: #1c1c1c; color: #e0e0e0; font-weight: 500; border: 1px solid #282828; }
            
            .chat-title-text { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1; }
            .delete-chat-btn { background: transparent; border: none; color: #595959; font-size: 1rem; cursor: pointer; padding: 2px 6px; border-radius: 50%; }
            .delete-chat-btn:hover { color: #cccccc; background: rgba(255,255,255,0.08); }

            .sidebar-footer { padding: 8px 8px 0 8px; border-top: 1px solid #1a1a1a; display: flex; align-items: center; gap: 8px; font-size: 0.85rem; color: #595959; }
            .status-dot { width: 8px; height: 8px; background: #22c55e; border-radius: 50%; }

            /* Main Content */
            .main-content { flex: 1; display: flex; flex-direction: column; background: #000000; width: 100%; overflow: hidden; }
            .top-nav { padding: 16px 20px; border-bottom: 1px solid #1a1a1a; display: flex; justify-content: space-between; align-items: center; background: #080808; }
            
            .top-left-group { display: flex; align-items: center; gap: 12px; overflow: hidden; }
            .menu-btn { display: none; background: #121212; border: 1px solid #222; color: #b5b5b5; padding: 6px 10px; border-radius: 6px; cursor: pointer; }

            .top-title { font-weight: 600; font-size: 0.95rem; color: #b5b5b5; display: flex; align-items: center; gap: 10px; }
            
            .ai-status-badge { font-size: 0.7rem; background: rgba(255, 255, 255, 0.03); color: #a6a6a6; padding: 4px 10px; border-radius: 20px; border: 1px solid rgba(255, 255, 255, 0.1); display: none; align-items: center; gap: 6px; font-weight: 600; }
            .ai-status-badge.active { display: inline-flex; animation: pulseBadge 1.5s infinite; }
            
            @keyframes pulseBadge {
                0% { opacity: 0.5; } 50% { opacity: 1; border-color: #888; } 100% { opacity: 0.5; }
            }

            .clear-btn { background: #121212; color: #8c8c8c; border: 1px solid #222; padding: 6px 12px; border-radius: 16px; cursor: pointer; font-size: 0.8rem; }
            .clear-btn:hover { background: #1c1c1c; color: #b5b5b5; }

            .chat-messages { flex: 1; padding: 20px; overflow-y: auto; display: flex; flex-direction: column; gap: 16px; justify-content: center; align-items: center; }
            
            .welcome-container { display: flex; flex-direction: column; align-items: center; gap: 16px; max-width: 480px; width: 100%; text-align: center; }
            .welcome-card { background: #080808; border: 1px solid #1a1a1a; border-radius: 16px; padding: 18px 20px; width: 100%; }
            .welcome-title { font-weight: 600; font-size: 0.95rem; color: #cccccc; margin-bottom: 4px; }
            .welcome-subtitle { font-size: 0.8rem; color: #595959; }

            .chips-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; width: 100%; }
            .chip { background: #0a0a0a; border: 1px solid #1c1c1c; border-radius: 16px; padding: 10px 14px; color: #8c8c8c; font-size: 0.82rem; cursor: pointer; text-align: left; transition: all 0.2s; display: flex; align-items: center; gap: 8px; }
            .chip:hover { background: #161616; border-color: #333; color: #ccc; }

            .message { padding: 12px 16px; border-radius: 14px; max-width: 85%; line-height: 1.5; overflow-wrap: break-word; white-space: pre-wrap; font-size: 0.95rem; align-self: flex-start; }
            .message.user { background: #242424 !important; color: #e0e0e0 !important; align-self: flex-end; border: 1px solid #333; }
            .message.ai { background: #0e0e0e; color: #b5b5b5; border: 1px solid #222; }
            .message img { max-width: 100%; border-radius: 8px; margin-top: 8px; display: block; }
            
            .file-preview-pill { display: inline-flex; align-items: center; gap: 6px; background: #181818; border: 1px solid #333; padding: 4px 10px; border-radius: 12px; font-size: 0.75rem; color: #ccc; margin-bottom: 8px; width: fit-content; }
            .file-preview-pill button { background: none; border: none; color: #888; cursor: pointer; font-weight: bold; font-size: 1rem; }

            .typing-indicator { display: none; align-self: flex-start; background: #0e0e0e; border: 1px solid #222; padding: 12px 16px; border-radius: 14px; align-items: center; gap: 8px; }
            .typing-indicator.active { display: flex; }
            .typing-dot { width: 7px; height: 7px; background: #888; border-radius: 50%; animation: bounce 1.4s infinite ease-in-out both; }
            .typing-dot:nth-child(1) { animation-delay: -0.32s; }
            .typing-dot:nth-child(2) { animation-delay: -0.16s; }

            @keyframes bounce { 0%, 80%, 100% { transform: scale(0); } 40% { transform: scale(1.15); } }

            .input-container { padding: 16px 20px; background: #000; }
            .input-box { background: #080808; border: 1px solid #1a1a1a; border-radius: 20px; display: flex; flex-direction: column; padding: 10px 14px; box-shadow: 0 4px 12px rgba(0,0,0,0.3); }
            .input-row { display: flex; align-items: center; gap: 10px; width: 100%; }
            
            textarea { flex: 1; background: transparent; border: none; color: #b5b5b5; font-size: 0.95rem; resize: none; outline: none; max-height: 120px; padding: 4px 0; }
            textarea::placeholder { color: #4a4a4a; }
            
            .attach-btn { display: flex !important; visibility: visible !important; opacity: 1 !important; background: #141414; border: 1px solid #222; color: #aaa; min-width: 36px; height: 36px; border-radius: 50%; align-items: center; justify-content: center; font-size: 1.1rem; cursor: pointer; transition: all 0.2s; flex-shrink: 0; }
            .attach-btn:hover { background: #222; color: #fff; border-color: #444; }
            
            .send-btn { background: #262626; color: #d0d0d0; border: 1px solid #333; padding: 8px 16px; border-radius: 16px; font-weight: bold; cursor: pointer; font-size: 0.9rem; flex-shrink: 0; }
            .send-btn:hover { background: #333333; color: #fff; }
            .send-btn:disabled { background: #161616; color: #444; cursor: not-allowed; }

            @media (max-width: 768px) {
                .sidebar { position: absolute; height: 100%; left: 0; top: 0; transform: translateX(-100%); }
                .sidebar.open { transform: translateX(0); }
                .close-sidebar-btn { display: block; }
                .menu-btn { display: inline-flex; }
                .chips-grid { grid-template-columns: 1fr; }
            }
        </style>
    </head>
    <body>
        <!-- Оверлей обновления -->
        <div id="updateOverlay" class="update-overlay">
            <div class="update-spinner"></div>
            <div class="update-text">Сайт на обновлении...</div>
            <div class="update-subtext">Нейросеть генерирует контент и обновляет данные</div>
        </div>

        <div id="sidebar" class="sidebar">
            <div class="logo-area">
                <div>
                    <div class="logo-title">RUBINOV-AI</div>
                    <div class="logo-subtitle">MULTIMODAL</div>
                </div>
                <button class="close-sidebar-btn" onclick="toggleSidebar()">&times;</button>
            </div>
            <button class="new-chat-btn" onclick="createNewChat()">+ Новый чат</button>
            <div class="chats-section-title">Чаты</div>
            <div id="chatsList" class="chats-list"></div>
            <div class="sidebar-footer">
                <div class="status-dot"></div>
                <span>Imagen 3 + Flash Active</span>
            </div>
        </div>

        <div class="main-content">
            <div class="top-nav">
                <div class="top-left-group">
                    <button class="menu-btn" onclick="toggleSidebar()">☰</button>
                    <div class="top-title">
                        <span>Мультимодальный чат</span>
                        <div id="aiStatusBadge" class="ai-status-badge">
                            <div class="typing-dot" style="width: 5px; height: 5px; background: #888;"></div>
                            <span>ОБРАБОТКА...</span>
                        </div>
                    </div>
                </div>
                <button class="clear-btn" onclick="clearCurrentChat()">🗑️ Очистить</button>
            </div>
            
            <div id="messages" class="chat-messages"></div>

            <div style="padding: 0 20px 8px 20px;">
                <div id="typingIndicator" class="typing-indicator">
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <span style="font-size: 0.75rem; color: #666; font-weight: 700;">НЕЙРОСЕТЬ ДУМАЕТ / РИСУЕТ...</span>
                </div>
            </div>

            <div class="input-container">
                <div class="input-box">
                    <div id="filePreviewContainer"></div>
                    <div class="input-row">
                        <input type="file" id="fileInput" style="display: none;" onchange="handleFileSelect(event)">
                        <button class="attach-btn" onclick="document.getElementById('fileInput').click()" title="Прикрепить файл или картинку">📎</button>
                        <textarea id="messageInput" placeholder="Введите сообщение или напишите «нарисуй...»..." rows="1" onkeydown="handleKeyDown(event)"></textarea>
                        <button id="sendBtn" class="send-btn" onclick="sendMessage()">Отправить</button>
                    </div>
                </div>
            </div>
        </div>

        <script>
            let chats = JSON.parse(localStorage.getItem('rubinovai_chats_mm_v5')) || [{ id: 1, title: 'Новый чат', history: [] }];
            let activeChatId = Number(localStorage.getItem('rubinovai_active_id_mm_v5')) || chats[0].id;
            let attachedFile = null;

            function saveState() {
                localStorage.setItem('rubinovai_chats_mm_v5', JSON.stringify(chats));
                localStorage.setItem('rubinovai_active_id_mm_v5', activeChatId);
            }

            function toggleSidebar() {
                document.getElementById('sidebar').classList.toggle('open');
            }

            function handleFileSelect(event) {
                const file = event.target.files[0];
                if (!file) return;
                const reader = new FileReader();
                reader.onload = function(e) {
                    const base64String = e.target.result.split(',')[1];
                    attachedFile = {
                        name: file.name,
                        type: file.type,
                        base64: base64String
                    };
                    renderFilePreview();
                };
                reader.readAsDataURL(file);
            }

            function removeAttachedFile() {
                attachedFile = null;
                document.getElementById('fileInput').value = '';
                renderFilePreview();
            }

            function renderFilePreview() {
                const container = document.getElementById('filePreviewContainer');
                if (!attachedFile) {
                    container.innerHTML = '';
                    return;
                }
                container.innerHTML = `
                    <div class="file-preview-pill">
                        <span>📎 ${escapeHtml(attachedFile.name)}</span>
                        <button onclick="removeAttachedFile()">&times;</button>
                    </div>
                `;
            }

            function renderChats() {
                const list = document.getElementById('chatsList');
                list.innerHTML = '';
                chats.forEach(chat => {
                    const div = document.createElement('div');
                    div.className = `chat-item ${chat.id === activeChatId ? 'active' : ''}`;
                    div.innerHTML = `<span class="chat-title-text">${escapeHtml(chat.title)}</span>`;
                    div.onclick = () => { switchChat(chat.id); if (window.innerWidth <= 768) toggleSidebar(); };
                    
                    const deleteBtn = document.createElement('button');
                    deleteBtn.className = 'delete-chat-btn';
                    deleteBtn.innerHTML = '&times;';
                    deleteBtn.onclick = (e) => { e.stopPropagation(); deleteChat(chat.id); };
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
                                <div class="welcome-title">Rubinov-AI Мультимодальный 🚀</div>
                                <div class="welcome-subtitle">Нажмите скрепку 📎 или напишите «нарисуй...»</div>
                            </div>
                            <div class="chips-grid">
                                <div class="chip" onclick="sendChip('Нарисуй футуристический спорткар на закате')">🎨 Спорткар на закате</div>
                                <div class="chip" onclick="sendChip('Объясни код из прикрепленного файла')">📂 Анализ файла</div>
                                <div class="chip" onclick="sendChip('Напиши план для маркетинговой кампании')">📊 План маркетинга</div>
                                <div class="chip" onclick="sendChip('Сделай красивую иконку приложения')">✨ Иконка приложения</div>
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
                    let htmlContent = "";
                    if (m.fileThumb) {
                        htmlContent += `<div style="font-size: 0.8rem; color: #888; margin-bottom: 6px; border-bottom: 1px solid #222; padding-bottom: 4px;">📎 Файл: ${escapeHtml(m.fileName)}</div>`;
                    }
                    htmlContent += escapeHtml(m.text);
                    if (m.imageUrl) {
                        htmlContent += `<img src="${m.imageUrl}" alt="Сгенерированное изображение">`;
                    }
                    el.innerHTML = htmlContent;
                    msgDiv.appendChild(el);
                });
                msgDiv.scrollTop = msgDiv.scrollHeight;
            }

            function escapeHtml(text) {
                if (!text) return '';
                return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
            }

            function sendChip(text) {
                document.getElementById('messageInput').value = text;
                sendMessage();
            }

            function setWorkingState(isWorking) {
                document.getElementById('aiStatusBadge').classList.toggle('active', isWorking);
                document.getElementById('typingIndicator').classList.toggle('active', isWorking);
                document.getElementById('updateOverlay').classList.toggle('active', isWorking);
                document.getElementById('sendBtn').disabled = isWorking;
                document.getElementById('messageInput').disabled = isWorking;
            }

            function createNewChat() {
                if (chats.length >= 5) { alert('Максимум 5 чатов.'); return; }
                const newId = Date.now();
                chats.unshift({ id: newId, title: 'Новый чат', history: [] });
                activeChatId = newId;
                saveState();
                renderChats();
                if (window.innerWidth <= 768) toggleSidebar();
            }

            function deleteChat(id) {
                if (chats.length <= 1) { alert('Нужно оставить хотя бы один чат.'); return; }
                chats = chats.filter(c => c.id !== id);
                if (activeChatId === id) activeChatId = chats[0].id;
                saveState();
                renderChats();
            }

            function switchChat(id) { activeChatId = id; saveState(); renderChats(); }
            function clearCurrentChat() {
                const chat = chats.find(c => c.id === activeChatId);
                if (chat) { chat.history = []; chat.title = 'Новый чат'; saveState(); renderChats(); }
            }
            function handleKeyDown(e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } }

            async function sendMessage() {
                const input = document.getElementById('messageInput');
                const text = input.value.trim();
                if (!text && !attachedFile) return;

                let chat = chats.find(c => c.id === activeChatId);
                if (!chat) return;

                const isFirstMsg = (chat.history.length === 0);
                const currentFile = attachedFile;
                
                chat.history.push({
                    role: 'user',
                    text: text || "Проанализируй прикрепленный файл",
                    fileThumb: currentFile ? true : false,
                    fileName: currentFile ? currentFile.name : null
                });

                input.value = '';
                attachedFile = null;
                document.getElementById('fileInput').value = '';
                renderFilePreview();
                renderChats();
                setWorkingState(true);

                const formData = new FormData();
                formData.append("message", text || "Проанализируй прикрепленный файл");
                formData.append("history", JSON.stringify(chat.history.slice(0, -1)));
                if (currentFile) {
                    formData.append("file_base64", currentFile.base64);
                    formData.append("file_name", currentFile.name);
                    formData.append("file_type", currentFile.type);
                }

                try {
                    const response = await fetch('/api/chat', { method: 'POST', body: formData });
                    const data = await response.json();

                    chat.history.push({
                        role: 'ai',
                        text: data.reply,
                        imageUrl: data.image_url || null
                    });

                    saveState();
                    setWorkingState(false);
                    renderChats();

                    if (isFirstMsg && text) {
                        fetch('/api/title', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({message: text})
                        }).then(r => r.json()).then(d => {
                            if (d.title) { chat.title = d.title; saveState(); renderChats(); }
                        });
                    }
                } catch (err) {
                    setWorkingState(false);
                    chat.history.push({ role: 'ai', text: 'Ошибка связи с сервером.' });
                    saveState();
                    renderChats();
                }
            }
            renderChats();
        </script>
    </body>
    </html>
    """

@app.post("/api/title")
async def generate_title(req: TitleRequest):
    try:
        response = client.models.generate_content(
            model=DEFAULT_MODEL,
            contents=f"Придумай краткое название (3-4 слова, без кавычек) для чата по теме: «{req.message}»"
        )
        title = response.text.strip().replace('"', '').replace("'", "")
        return {"title": title[:30]}
    except:
        return {"title": "Диалог"}

@app.post("/api/chat")
async def chat_endpoint(
    message: str = Form(...),
    history: str = Form("[]"),
    file_base64: str = Form(None),
    file_name: str = Form(None),
    file_type: str = Form(None)
):
    try:
        hist_list = json.loads(history)
        low_msg = message.lower()
        is_image_request = any(kw in low_msg for kw in ["нарисуй", "сгенерируй картинку", "создай изображение", "картинка с", "нарисовать"])

        if is_image_request:
            result = client.models.generate_images(
                model=IMAGE_MODEL,
                prompt=message,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    output_mime_type="image/jpeg",
                    aspect_ratio="1:1",
                )
            )
            
            img_url = None
            if result.generated_images:
                img_bytes = result.generated_images[0].image.image_bytes
                b64_img = base64.b64encode(img_bytes).decode('utf-8')
                img_url = f"data:image/jpeg;base64,{b64_img}"

            reply_text = "Вот что у меня получилось по вашему запросу:" if img_url else "Не удалось сгенерировать изображение."
            return {"reply": reply_text, "image_url": img_url}

        formatted_history = []
        for h in hist_list:
            role = "user" if h["role"] == "user" else "model"
            formatted_history.append(types.Content(role=role, parts=[types.Part.from_text(text=h["text"])]))

        chat_session = client.chats.create(model=DEFAULT_MODEL, history=formatted_history)
        
        content_parts = []
        if file_base64 and file_type:
            file_bytes = base64.b64decode(file_base64)
            content_parts.append(types.Part.from_bytes(data=file_bytes, mime_type=file_type))
        
        if message:
            content_parts.append(types.Part.from_text(text=message))

        response = chat_session.send_message(content_parts)
        return {"reply": response.text, "image_url": None}

    except Exception as e:
        return {"reply": f"Ошибка обработки запроса: {str(e)}", "image_url": None}

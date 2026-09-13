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
from google import genai
from google.genai import types

app = FastAPI()

SERVER_BUILD_ID = str(uuid.uuid4())[:8]
IMAGE_GEN_ENABLED = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

client = genai.Client()
CHAT_MODEL = "gemini-3.1-flash-lite"
IMAGEN_MODEL = "imagen-3.0-generate-002"

class TitleRequest(BaseModel):
    message: str

class ImageGenRequest(BaseModel):
    prompt: str

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "build_id": SERVER_BUILD_ID, "image_gen_enabled": IMAGE_GEN_ENABLED}

@app.post("/api/title")
async def generate_title(req: TitleRequest):
    words = req.message.strip().split()
    short_title = " ".join(words[:4])
    if len(short_title) > 28:
        short_title = short_title[:25] + "..."
    return {"title": short_title if short_title else "Диалог"}

@app.post("/api/generate-image")
async def generate_image_endpoint(req: ImageGenRequest):
    if not IMAGE_GEN_ENABLED:
        raise HTTPException(status_code=403, detail="Генерация изображений временно отключена администратором.")
    try:
        response = client.models.generate_images(
            model=IMAGEN_MODEL,
            prompt=req.prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                output_mime_type="image/jpeg",
                aspect_ratio="1:1"
            )
        )
        if not response.generated_images:
            raise HTTPException(status_code=500, detail="Не удалось получить изображение от модели.")
        
        img_obj = response.generated_images[0].image
        buf = io.BytesIO()
        if hasattr(img_obj, "save"):
            img_obj.save(buf, format="JPEG")
        elif hasattr(img_obj, "_pil_image"):
            img_obj._pil_image.save(buf, format="JPEG")
        else:
            raise HTTPException(status_code=500, detail="Формат ответа изображения не поддерживается.")
            
        img_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return {"image_url": f"data:image/jpeg;base64,{img_base64}"}
    except Exception as e:
        error_msg = str(e)
        if "not found" in error_msg.lower() or "permission" in error_msg.lower():
            raise HTTPException(status_code=400, detail="Генерация картинок недоступна на вашем текущем ключе или тарифном плане API.")
        raise HTTPException(status_code=500, detail=f"Ошибка генерации: {error_msg}")

@app.post("/api/chat")
async def chat_endpoint(
    message: str = Form(...),
    mode: str = Form("chat"),
    history: str = Form("[]"),
    file: UploadFile = File(None)
):
    try:
        history_list = json.loads(history)
        formatted_history = []
        for h in history_list:
            sdk_role = "user" if h["role"] == "user" else "model"
            formatted_history.append(
                types.Content(
                    role=sdk_role,
                    parts=[types.Part.from_text(text=h["content"])]
                )
            )

        chat = client.chats.create(
            model=CHAT_MODEL,
            history=formatted_history
        )

        current_contents = []
        if file:
            file_bytes = await file.read()
            current_contents.append(
                types.Part.from_bytes(
                    data=file_bytes,
                    mime_type=file.content_type
                )
            )
        
        current_contents.append(message)
        response = chat.send_message(current_contents)

        return {"response": response.text}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/", response_class=HTMLResponse)
async def get_chat_ui():
    html_content = """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>Rubinov-AI Assistant</title>
        <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; -webkit-tap-highlight-color: transparent; }
            body { background: #050505; color: #c0c0c0; display: flex; height: 100dvh; overflow: hidden; position: relative; }
            
            .sidebar { width: 260px; background: #0a0a0a; display: flex; flex-direction: column; border-right: 1px solid #1f1f1f; padding: 12px; transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1); z-index: 100; }
            .logo-area { margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; padding: 2px 4px; }
            .logo-title { font-size: 1rem; font-weight: 700; color: #e0e0e0; letter-spacing: 0.5px; }
            .logo-subtitle { font-size: 0.65rem; color: #707070; font-weight: 600; margin-top: 1px; letter-spacing: 1px; }
            .close-sidebar-btn { display: none; background: transparent; border: none; color: #aaa; font-size: 1.2rem; cursor: pointer; padding: 2px; }

            .new-chat-btn { 
                background: #141414; color: #ddd; border: 1px solid #2a2a2a; padding: 6px 10px; 
                border-radius: 6px; font-weight: 500; cursor: pointer; text-align: left; margin-bottom: 10px; 
                display: flex; align-items: center; gap: 6px; transition: all 0.2s; font-size: 0.78rem;
            }
            .new-chat-btn:hover { background: #1c1c1c; border-color: #404040; color: #fff; }
            
            .chats-section-title { font-size: 0.65rem; text-transform: uppercase; color: #666; margin-bottom: 4px; font-weight: 700; padding: 0 4px; letter-spacing: 0.8px; }
            .chats-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 3px; margin-bottom: 8px; padding-right: 2px; }
            .chats-list::-webkit-scrollbar { width: 3px; }
            .chats-list::-webkit-scrollbar-thumb { background: #222; border-radius: 3px; }
            
            .chat-item { 
                display: flex; align-items: center; justify-content: space-between; padding: 5px 8px; 
                border-radius: 6px; cursor: pointer; background: transparent; color: #999; font-size: 0.78rem; 
                border: 1px solid transparent; transition: all 0.2s;
            }
            .chat-item:hover { background: #121212; color: #ccc; }
            .chat-item.active { background: #1a1a1a; color: #f0f0f0; font-weight: 500; border-color: #2e2e2e; }
            .chat-title-text { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1; }
            .delete-chat-btn { background: transparent; border: none; color: #666; font-size: 0.9rem; cursor: pointer; padding: 1px 4px; border-radius: 4px; opacity: 0; transition: opacity 0.2s; }
            .chat-item:hover .delete-chat-btn { opacity: 1; }
            .delete-chat-btn:hover { color: #fff; background: rgba(255,255,255,0.1); }

            .sidebar-footer { padding: 8px 4px; border-top: 1px solid #1f1f1f; display: flex; align-items: center; gap: 8px; font-size: 0.75rem; color: #666; }
            .status-dot { width: 6px; height: 6px; background: #22c55e; border-radius: 50%; box-shadow: 0 0 6px rgba(34, 197, 94, 0.4); }

            .main-content { flex: 1; display: flex; flex-direction: column; background: #050505; width: 100%; overflow: hidden; position: relative; }
            .top-nav { padding: 12px 16px; border-bottom: 1px solid #1f1f1f; display: flex; justify-content: space-between; align-items: center; background: #080808; min-height: 55px; }
            .top-left-group { display: flex; align-items: center; gap: 10px; }
            .menu-btn { display: none; background: #141414; border: 1px solid #2a2a2a; color: #ccc; width: 34px; height: 34px; border-radius: 8px; cursor: pointer; align-items: center; justify-content: center; font-size: 1rem; }
            .top-title-wrapper { display: flex; flex-direction: column; gap: 2px; }
            .top-title { font-weight: 600; font-size: 0.9rem; color: #ddd; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 180px; }
            .model-badge { font-size: 0.65rem; color: #888; background: #121212; border: 1px solid #222; padding: 1px 6px; border-radius: 6px; width: fit-content; font-weight: 500; }
            
            .nav-right-group { display: flex; align-items: center; gap: 8px; }
            .mode-switch { display: flex; background: #121212; border: 1px solid #222; border-radius: 10px; padding: 2px; }
            .mode-btn { background: transparent; border: none; color: #888; padding: 5px 10px; border-radius: 8px; font-size: 0.75rem; font-weight: 600; cursor: pointer; transition: all 0.2s; }
            .mode-btn.active { background: #262626; color: #fff; box-shadow: 0 2px 4px rgba(0,0,0,0.3); }

            .ai-status-badge { font-size: 0.65rem; background: rgba(255,255,255,0.04); color: #bbb; padding: 4px 8px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.1); display: none; align-items: center; gap: 5px; font-weight: 600; }
            .ai-status-badge.active { display: inline-flex; animation: pulseBadge 1.5s infinite; }
            @keyframes pulseBadge { 0% { opacity: 0.6; } 50% { opacity: 1; border-color: #666; } 100% { opacity: 0.6; } }

            .clear-btn { background: #141414; color: #999; border: 1px solid #2a2a2a; padding: 5px 10px; border-radius: 10px; cursor: pointer; font-size: 0.75rem; font-weight: 500; transition: all 0.2s; }
            .clear-btn:hover { background: #1f1f1f; color: #fff; border-color: #404040; }

            .chat-messages { flex: 1; padding: 20px; overflow-y: auto; display: flex; flex-direction: column; gap: 14px; scroll-behavior: smooth; }
            .chat-messages::-webkit-scrollbar { width: 5px; }
            .chat-messages::-webkit-scrollbar-thumb { background: #222; border-radius: 4px; }
            
            .welcome-container { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 16px; max-width: 480px; width: 100%; margin: auto; text-align: center; padding: 16px; }
            .welcome-card { background: #0c0c0c; border: 1px solid #1a1a1a; border-radius: 16px; padding: 20px; width: 100%; box-shadow: 0 6px 20px rgba(0,0,0,0.4); }
            .welcome-title { font-weight: 600; font-size: 1.05rem; color: #e0e0e0; margin-bottom: 4px; }
            .welcome-subtitle { font-size: 0.8rem; color: #777; line-height: 1.4; }

            .chips-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; width: 100%; }
            .chip { background: #0a0a0a; border: 1px solid #1f1f1f; border-radius: 12px; padding: 10px 12px; color: #999; font-size: 0.78rem; cursor: pointer; text-align: left; transition: all 0.2s; display: flex; align-items: center; gap: 6px; }
            .chip:hover { background: #161616; border-color: #333; color: #ddd; transform: translateY(-1px); }

            .message { padding: 12px 16px; border-radius: 14px; max-width: 80%; line-height: 1.5; overflow-wrap: break-word; font-size: 0.9rem; box-shadow: 0 2px 6px rgba(0,0,0,0.2); }
            .message.user { background: #222222 !important; color: #f0f0f0 !important; align-self: flex-end; border: 1px solid #333; border-bottom-right-radius: 4px; white-space: pre-wrap; }
            .message.ai { background: #0c0c0c; color: #c5c5c5; border: 1px solid #1f1f1f; align-self: flex-start; border-bottom-left-radius: 4px; }
            
            .message.ai p { margin-bottom: 8px; }
            .message.ai p:last-child { margin-bottom: 0; }
            .message.ai ul, .message.ai ol { margin-left: 20px; margin-bottom: 8px; }
            .message.ai code { background: #1a1a1a; padding: 2px 5px; border-radius: 4px; font-family: monospace; font-size: 0.85rem; }
            .message.ai pre { background: #141414; padding: 10px; border-radius: 8px; overflow-x: auto; margin: 8px 0; border: 1px solid #222; }
            .message.ai pre code { background: transparent; padding: 0; }
            .message.ai strong { color: #fff; }
            .message.ai hr { border: none; border-top: 1px solid #222; margin: 10px 0; }
            .message img { max-width: 100%; border-radius: 10px; margin-top: 8px; display: block; box-shadow: 0 3px 10px rgba(0,0,0,0.5); }
            
            .input-container { padding: 12px 20px 20px; background: #050505; }
            .input-box { background: #0c0c0c; border: 1px solid #222; border-radius: 16px; display: flex; flex-direction: column; padding: 8px 12px; box-shadow: 0 6px 24px rgba(0,0,0,0.5); transition: border-color 0.2s; }
            .input-box:focus-within { border-color: #444; }
            .input-row { display: flex; align-items: flex-end; gap: 8px; width: 100%; }
            
            textarea { flex: 1; background: transparent; border: none; color: #e0e0e0; font-size: 0.9rem; resize: none; outline: none; max-height: 120px; padding: 4px 0; line-height: 1.4; }
            textarea::placeholder { color: #555; }

            .attach-btn { background: #141414; border: 1px solid #2a2a2a; color: #bbb; min-width: 34px; height: 34px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 1rem; cursor: pointer; transition: all 0.2s; flex-shrink: 0; margin-bottom: 2px; }
            .attach-btn:hover { background: #222; color: #fff; border-color: #444; }
            
            .send-btn { background: #e0e0e0; color: #000; border: none; padding: 8px 16px; border-radius: 12px; font-weight: 700; cursor: pointer; font-size: 0.85rem; flex-shrink: 0; transition: all 0.2s; margin-bottom: 2px; }
            .send-btn:hover { background: #fff; box-shadow: 0 0 10px rgba(255,255,255,0.2); }
            .send-btn:disabled { background: #1a1a1a; color: #555; cursor: not-allowed; box-shadow: none; }

            .file-preview-pill { display: inline-flex; align-items: center; gap: 6px; background: #161616; border: 1px solid #333; padding: 4px 10px; border-radius: 8px; font-size: 0.75rem; color: #ddd; margin-bottom: 6px; width: fit-content; }
            .file-preview-pill button { background: none; border: none; color: #888; cursor: pointer; font-weight: bold; font-size: 1rem; line-height: 1; }
            .file-preview-pill button:hover { color: #fff; }

            .sidebar-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.6); backdrop-filter: blur(3px); z-index: 90; }
            .sidebar-overlay.active { display: block; }

            @media (max-width: 768px) {
                .sidebar { position: absolute; height: 100%; left: 0; top: 0; transform: translateX(-100%); width: 260px; box-shadow: 20px 0 40px rgba(0,0,0,0.8); }
                .sidebar.open { transform: translateX(0); }
                .close-sidebar-btn { display: block; }
                .menu-btn { display: inline-flex; }
                .chips-grid { grid-template-columns: 1fr; }
                .chat-messages { padding: 14px; }
                .input-container { padding: 10px 14px 14px; }
                .message { max-width: 90%; }
                .top-title { max-width: 130px; }
            }
        </style>
    </head>
    <body>
        <div id="sidebarOverlay" class="sidebar-overlay" onclick="toggleSidebar()"></div>

        <div id="sidebar" class="sidebar">
            <div class="logo-area">
                <div>
                    <div class="logo-title">RUBINOV-AI</div>
                    <div class="logo-subtitle">MULTIMODAL CHAT</div>
                </div>
                <button class="close-sidebar-btn" onclick="toggleSidebar()">✕</button>
            </div>
            
            <button class="new-chat-btn" onclick="startNewChat()">
                <span style="font-size: 0.9rem; line-height: 1;">+</span> Новый чат
            </button>
            
            <div class="chats-section-title">История диалогов</div>
            <div id="chatsList" class="chats-list"></div>
            
            <div class="sidebar-footer">
                <div class="status-dot"></div>
                <span>Система активна</span>
            </div>
        </div>

        <div class="main-content">
            <div class="top-nav">
                <div class="top-left-group">
                    <button class="menu-btn" onclick="toggleSidebar()">☰</button>
                    <div class="top-title-wrapper">
                        <div class="top-title" id="currentChatTitle">Новый диалог</div>
                        <div class="model-badge">⚡ gemini-3.1-flash-lite</div>
                    </div>
                </div>
                <div class="nav-right-group">
                    <div class="mode-switch">
                        <button id="modeChat" class="mode-btn active" onclick="setMode('chat')">💬 Чат</button>
                        <button id="modeImage" class="mode-btn" onclick="setMode('image')">🎨 Картинка</button>
                    </div>
                    <div id="aiStatusBadge" class="ai-status-badge">
                        <span style="width: 4px; height: 4px; background: #fff; border-radius: 50%;"></span>
                        ДУМАЕТ...
                    </div>
                    <button class="clear-btn" onclick="clearCurrentChat()">Очистить</button>
                </div>
            </div>

            <div id="chatMessages" class="chat-messages">
                <div class="welcome-container" id="welcomeContainer">
                    <div class="welcome-card">
                        <div class="welcome-title">Чем я могу помочь сегодня?</div>
                        <div class="welcome-subtitle">Задайте вопрос, прикрепите файл или переключитесь в режим генерации изображений.</div>
                    </div>
                    <div class="chips-grid">
                        <div class="chip" onclick="sendPreset('Напиши простой код на Python для сервера FastAPI')">⚡ Код FastAPI</div>
                        <div class="chip" onclick="sendPreset('Объясни квантовые вычисления простыми словами')">🌌 Квантовая физика</div>
                        <div class="chip" onclick="sendPreset('Составь план продуктивного дня')">📋 План дня</div>
                        <div class="chip" onclick="sendPreset('Киберпанк город под дождем, неоновые вывески')">🎨 Нарисовать киберпанк</div>
                    </div>
                </div>
            </div>

            <div class="input-container">
                <div class="input-box">
                    <div id="filePreviewArea"></div>
                    <div class="input-row">
                        <button class="attach-btn" title="Прикрепить файл" onclick="document.getElementById('fileInput').click()">📎</button>
                        <input type="file" id="fileInput" style="display:none" onchange="handleFileSelect(event)">
                        
                        <textarea id="userInput" rows="1" placeholder="Введите сообщение..." oninput="autoResize(this)" onkeydown="handleKeyDown(event)"></textarea>
                        
                        <button id="sendBtn" class="send-btn" onclick="sendMessage()">Отправить</button>
                    </div>
                </div>
            </div>
        </div>

        <script>
            let chats = JSON.parse(localStorage.getItem('rubinov_chats') || '[]');
            let currentChatId = null;
            let selectedFile = null;
            let currentMode = 'chat';

            function setMode(mode) {
                currentMode = mode;
                document.getElementById('modeChat').classList.toggle('active', mode === 'chat');
                document.getElementById('modeImage').classList.toggle('active', mode === 'image');
                const textarea = document.getElementById('userInput');
                textarea.placeholder = mode === 'image' ? 'Опишите изображение для генерации...' : 'Введите сообщение...';
            }

            window.addEventListener('DOMContentLoaded', () => {
                renderChatsList();
                const savedId = localStorage.getItem('rubinov_current_id');
                if (savedId && chats.some(c => c.id === savedId)) {
                    loadChat(savedId);
                } else {
                    startNewChat();
                }
            });

            function toggleSidebar() {
                document.getElementById('sidebar').classList.toggle('open');
                document.getElementById('sidebarOverlay').classList.toggle('active');
            }

            function autoResize(textarea) {
                textarea.style.height = 'auto';
                textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
            }

            function handleKeyDown(e) {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendMessage();
                }
            }

            function handleFileSelect(e) {
                const file = e.target.files[0];
                if (!file) return;
                selectedFile = file;
                const previewArea = document.getElementById('filePreviewArea');
                previewArea.innerHTML = `
                    <div class="file-preview-pill">
                        <span>📎 ${file.name}</span>
                        <button onclick="removeFile()">×</button>
                    </div>
                `;
            }

            function removeFile() {
                selectedFile = null;
                document.getElementById('fileInput').value = '';
                document.getElementById('filePreviewArea').innerHTML = '';
            }

            function sendPreset(text) {
                document.getElementById('userInput').value = text;
                if (text.includes('Нарисовать')) {
                    setMode('image');
                }
                sendMessage();
            }

            function startNewChat() {
                currentChatId = null;
                localStorage.removeItem('rubinov_current_id');
                document.getElementById('currentChatTitle').innerText = 'Новый диалог';
                document.getElementById('chatMessages').innerHTML = `
                    <div class="welcome-container" id="welcomeContainer">
                        <div class="welcome-card">
                            <div class="welcome-title">Чем я могу помочь сегодня?</div>
                            <div class="welcome-subtitle">Задайте вопрос, прикрепите файл или переключитесь в режим генерации изображений.</div>
                        </div>
                        <div class="chips-grid">
                            <div class="chip" onclick="sendPreset('Напиши простой код на Python для сервера FastAPI')">⚡ Код FastAPI</div>
                            <div class="chip" onclick="sendPreset('Объясни квантовые вычисления простыми словами')">🌌 Квантовая физика</div>
                            <div class="chip" onclick="sendPreset('Составь план продуктивного дня')">📋 План дня</div>
                            <div class="chip" onclick="sendPreset('Киберпанк город под дождем, неоновые вывески')">🎨 Нарисовать киберпанк</div>
                        </div>
                    </div>
                `;
                renderChatsList();
                if (window.innerWidth <= 768) toggleSidebar();
            }

            function clearCurrentChat() {
                startNewChat();
            }

            function renderChatsList() {
                const list = document.getElementById('chatsList');
                list.innerHTML = '';
                if (chats.length === 0) {
                    list.innerHTML = '<div style="font-size: 0.75rem; color: #555; padding: 4px 6px;">Нет сохраненных чатов</div>';
                    return;
                }
                chats.forEach(chat => {
                    const div = document.createElement('div');
                    div.className = `chat-item ${chat.id === currentChatId ? 'active' : ''}`;
                    div.innerHTML = `
                        <span class="chat-title-text" onclick="loadChat('${chat.id}')">${chat.title}</span>
                        <button class="delete-chat-btn" onclick="deleteChat(event, '${chat.id}')">×</button>
                    `;
                    list.appendChild(div);
                });
            }

            function deleteChat(e, id) {
                e.stopPropagation();
                chats = chats.filter(c => c.id !== id);
                localStorage.setItem('rubinov_chats', JSON.stringify(chats));
                if (currentChatId === id) {
                    startNewChat();
                } else {
                    renderChatsList();
                }
            }

            function loadChat(id) {
                const chat = chats.find(c => c.id === id);
                if (!chat) return;
                currentChatId = id;
                localStorage.setItem('rubinov_current_id', id);
                document.getElementById('currentChatTitle').innerText = chat.title;
                
                const container = document.getElementById('chatMessages');
                container.innerHTML = '';
                chat.messages.forEach(m => {
                    const msgDiv = document.createElement('div');
                    msgDiv.className = `message ${m.role}`;
                    if (m.role === 'ai') {
                        msgDiv.innerHTML = marked.parse(m.content);
                    } else {
                        msgDiv.innerText = m.content;
                    }
                    container.appendChild(msgDiv);
                });
                container.scrollTop = container.scrollHeight;
                renderChatsList();
                if (window.innerWidth <= 768) toggleSidebar();
            }

            async function sendMessage() {
                const input = document.getElementById('userInput');
                const text = input.value.trim();
                if (!text && !selectedFile) return;

                const welcome = document.getElementById('welcomeContainer');
                if (welcome) welcome.remove();

                const container = document.getElementById('chatMessages');
                
                const userMsgDiv = document.createElement('div');
                userMsgDiv.className = 'message user';
                let displayContent = text;
                if (selectedFile) {
                    displayContent = `[Файл: ${selectedFile.name}]\n` + displayContent;
                }
                userMsgDiv.innerText = displayContent;
                container.appendChild(userMsgDiv);

                input.value = '';
                input.style.height = 'auto';
                const fileToSend = selectedFile;
                removeFile();

                document.getElementById('aiStatusBadge').classList.add('active');
                document.getElementById('sendBtn').disabled = true;
                container.scrollTop = container.scrollHeight;

                try {
                    let responseHtml = '';

                    if (currentMode === 'image') {
                        const imgRes = await fetch('/api/generate-image', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({ prompt: text })
                        });
                        const imgData = await imgRes.json();
                        if (!imgRes.ok) throw new Error(imgData.detail || 'Ошибка генерации картинки');
                        responseHtml = `Сгенерированное изображение по запросу: "${text}"<br><img src="${imgData.image_url}" alt="Generated Image">`;
                    } else {
                        let currentHistory = [];
                        if (currentChatId) {
                            const activeChat = chats.find(c => c.id === currentChatId);
                            if (activeChat) {
                                currentHistory = activeChat.messages.map(m => ({
                                    role: m.role,
                                    content: m.content
                                }));
                            }
                        }

                        const formData = new FormData();
                        formData.append('message', text);
                        formData.append('history', JSON.stringify(currentHistory));
                        if (fileToSend) {
                            formData.append('file', fileToSend);
                        }

                        const res = await fetch('/api/chat', {
                            method: 'POST',
                            body: formData
                        });
                        const data = await res.json();
                        if (!res.ok) throw new Error(data.detail || 'Ошибка сервера');
                        responseHtml = data.response;
                    }

                    const aiMsgDiv = document.createElement('div');
                    aiMsgDiv.className = 'message ai';
                    aiMsgDiv.innerHTML = marked.parse(responseHtml);
                    container.appendChild(aiMsgDiv);

                    if (!currentChatId) {
                        currentChatId = 'chat_' + Date.now();
                        localStorage.setItem('rubinov_current_id', currentChatId);
                        
                        let chatTitle = text.slice(0, 25) + '...';
                        if (currentMode === 'chat') {
                            try {
                                const titleRes = await fetch('/api/title', {
                                    method: 'POST',
                                    headers: {'Content-Type': 'application/json'},
                                    body: JSON.stringify({ message: text })
                                });
                                const titleData = await titleRes.json();
                                if (titleData.title) chatTitle = titleData.title;
                            } catch(err) {}
                        } else {
                            chatTitle = '🎨 ' + text.slice(0, 20) + '...';
                        }

                        document.getElementById('currentChatTitle').innerText = chatTitle;
                        
                        chats.unshift({
                            id: currentChatId,
                            title: chatTitle,
                            messages: [
                                { role: 'user', content: displayContent },
                                { role: 'ai', content: responseHtml }
                            ]
                        });
                    } else {
                        const chat = chats.find(c => c.id === currentChatId);
                        if (chat) {
                            chat.messages.push({ role: 'user', content: displayContent });
                            chat.messages.push({ role: 'ai', content: responseHtml });
                        } else {
                            chats.unshift({
                                id: currentChatId,
                                title: document.getElementById('currentChatTitle').innerText,
                                messages: [
                                    { role: 'user', content: displayContent },
                                    { role: 'ai', content: responseHtml }
                                ]
                            });
                        }
                    }
                    localStorage.setItem('rubinov_chats', JSON.stringify(chats));
                    renderChatsList();

                } catch (err) {
                    const errDiv = document.createElement('div');
                    errDiv.className = 'message ai';
                    errDiv.style.color = '#ef4444';
                    errDiv.innerText = 'Ошибка: ' + err.message;
                    container.appendChild(errDiv);
                } finally {
                    document.getElementById('aiStatusBadge').classList.remove('active');
                    document.getElementById('sendBtn').disabled = false;
                    container.scrollTop = container.scrollHeight;
                }
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)

import os
import time
import json
import uuid
import io
import base64
import urllib.request
import urllib.parse
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from google import genai
from google.genai import types

app = FastAPI()

SERVER_BUILD_ID = str(uuid.uuid4())[:8]
IMAGE_GEN_ENABLED = True

CURRENT_COMMIT = os.environ.get("RENDER_GIT_COMMIT", "")
CURRENT_BRANCH = os.environ.get("RENDER_GIT_BRANCH", "")
CURRENT_REPO_SLUG = os.environ.get("RENDER_GIT_REPO_SLUG", "")

DEPLOY_STATUS_CACHE = {
    "checked_at": 0.0,
    "latest_commit": None,
    "error": None,
}
DEPLOY_STATUS_CACHE_TTL = 4.0

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

client = genai.Client()
CHAT_MODEL = "gemini-3.1-flash-lite"  # Переключено на актуальную модель Flash-Lite
IMAGEN_MODEL = "imagen-3.0-generate-002"

class TitleRequest(BaseModel):
    message: str

class ImageGenRequest(BaseModel):
    prompt: str

def get_latest_github_commit():
    now = time.time()

    if (
        DEPLOY_STATUS_CACHE["latest_commit"] is not None
        and now - DEPLOY_STATUS_CACHE["checked_at"] < DEPLOY_STATUS_CACHE_TTL
    ):
        return DEPLOY_STATUS_CACHE["latest_commit"], DEPLOY_STATUS_CACHE["error"]

    if not CURRENT_REPO_SLUG or not CURRENT_BRANCH:
        DEPLOY_STATUS_CACHE["checked_at"] = now
        DEPLOY_STATUS_CACHE["latest_commit"] = None
        DEPLOY_STATUS_CACHE["error"] = "Render Git metadata is unavailable"
        return None, DEPLOY_STATUS_CACHE["error"]

    branch = urllib.parse.quote(CURRENT_BRANCH, safe="")
    url = f"https://api.github.com/repos/{CURRENT_REPO_SLUG}/commits/{branch}"

    try:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "Rubinov-AI-Deploy-Monitor",
            },
        )

        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))

        latest_commit = payload.get("sha")

        DEPLOY_STATUS_CACHE["checked_at"] = now
        DEPLOY_STATUS_CACHE["latest_commit"] = latest_commit
        DEPLOY_STATUS_CACHE["error"] = None
        return latest_commit, None

    except Exception as exc:
        DEPLOY_STATUS_CACHE["checked_at"] = now
        DEPLOY_STATUS_CACHE["error"] = str(exc)
        return DEPLOY_STATUS_CACHE["latest_commit"], str(exc)


@app.get("/api/deploy-status")
async def deploy_status():
    latest_commit, error = get_latest_github_commit()

    is_building = bool(
        CURRENT_COMMIT
        and latest_commit
        and latest_commit != CURRENT_COMMIT
    )

    return {
        "updating": is_building,
        "current_commit": CURRENT_COMMIT,
        "latest_commit": latest_commit,
        "current_branch": CURRENT_BRANCH,
        "repository": CURRENT_REPO_SLUG,
        "build_id": SERVER_BUILD_ID,
        "github_check_ok": latest_commit is not None,
        "error": error,
    }


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "build_id": SERVER_BUILD_ID, "image_gen_enabled": IMAGE_GEN_ENABLED}

@app.post("/api/title")
async def generate_title(req: TitleRequest):
    try:
        response = client.models.generate_content(
            model=CHAT_MODEL,
            contents=f"Придумай короткое название (не более 3-4 слов, без кавычек) для чата, который начинается с этого сообщения: {req.message}"
        )
        return {"title": response.text.strip().replace('"', '')}
    except Exception as e:
        return {"title": req.message[:20] + "..."}

@app.post("/api/generate-image")
async def generate_image_endpoint(req: ImageGenRequest):
    if not IMAGE_GEN_ENABLED:
        raise HTTPException(status_code=403, detail="Генерация изображений временно отключена администратором.")
    try:
        response = client.models.generate_image(
            model=IMAGEN_MODEL,
            prompt=req.prompt,
            config=types.GenerateImageConfig(
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
    html_content = f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
        <meta http-equiv="Pragma" content="no-cache">
        <meta http-equiv="Expires" content="0">
        <title>Rubinov-AI Assistant</title>
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
            body {{ background: #000000; color: #b5b5b5; display: flex; height: 100dvh; overflow: hidden; position: relative; }}
            
            .deploy-overlay {{
                position: fixed;
                inset: 0;
                background: rgba(0,0,0,0.78);
                backdrop-filter: blur(6px);
                -webkit-backdrop-filter: blur(6px);
                display: none;
                align-items: center;
                justify-content: center;
                z-index: 9999;
                padding: 20px;
            }}

            .deploy-overlay.active {{ display: flex; }}

            .deploy-card {{
                width: min(420px, 100%);
                background: #0b0b0b;
                border: 1px solid #2a2a2a;
                border-radius: 20px;
                padding: 28px;
                text-align: center;
                box-shadow: 0 20px 60px rgba(0,0,0,0.55);
            }}

            .deploy-spinner {{
                width: 34px;
                height: 34px;
                margin: 0 auto 16px;
                border: 3px solid #2b2b2b;
                border-top-color: #ffffff;
                border-radius: 50%;
                animation: deploySpin 0.9s linear infinite;
            }}

            @keyframes deploySpin {{
                to {{ transform: rotate(360deg); }}
            }}

            .deploy-title {{
                color: #f1f1f1;
                font-size: 1rem;
                font-weight: 700;
                margin-bottom: 8px;
            }}

            .deploy-text {{
                color: #777;
                font-size: 0.83rem;
                line-height: 1.5;
            }}

            .deploy-hint {{
                color: #4f4f4f;
                font-size: 0.72rem;
                margin-top: 12px;
            }}

            .sidebar {{ width: 280px; background: #080808; display: flex; flex-direction: column; border-right: 1px solid #1a1a1a; padding: 16px; transition: transform 0.3s ease; z-index: 100; }}
            .logo-area {{ margin-bottom: 24px; display: flex; justify-content: space-between; align-items: center; padding: 0 8px; }}
            .logo-title {{ font-size: 1.1rem; font-weight: bold; color: #cccccc; }}
            .logo-subtitle {{ font-size: 0.75rem; color: #666666; font-weight: 600; margin-top: 4px; }}
            .close-sidebar-btn {{ display: none; background: transparent; border: none; color: #888; font-size: 1.2rem; cursor: pointer; }}

            .new-chat-btn {{ 
                background: transparent; color: #d0d0d0; border: 1px solid #222; padding: 10px 14px; 
                border-radius: 20px; font-weight: 600; cursor: pointer; text-align: left; margin-bottom: 16px; 
                display: flex; align-items: center; gap: 8px; transition: background 0.2s; 
            }}
            .new-chat-btn:hover {{ background: #181818; color: #fff; border-color: #333; }}
            
            .chats-section-title {{ font-size: 0.75rem; text-transform: uppercase; color: #595959; margin-bottom: 8px; font-weight: bold; padding: 0 8px; }}
            .chats-list {{ flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 4px; margin-bottom: 16px; }}
            
            .chat-item {{ 
                display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; 
                border-radius: 20px; cursor: pointer; background: transparent; color: #8c8c8c; font-size: 0.9rem; 
                border: 1px solid transparent; transition: all 0.2s;
            }}
            .chat-item:hover {{ background: #141414; color: #b5b5b5; }}
            .chat-item.active {{ background: #1c1c1c; color: #e0e0e0; font-weight: 500; border: 1px solid #282828; }}
            .chat-title-text {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1; }}
            .delete-chat-btn {{ background: transparent; border: none; color: #595959; font-size: 1rem; cursor: pointer; padding: 2px 6px; border-radius: 50%; }}
            .delete-chat-btn:hover {{ color: #fff; background: rgba(255,255,255,0.08); }}

            .sidebar-footer {{ padding: 8px; border-top: 1px solid #1a1a1a; display: flex; align-items: center; gap: 8px; font-size: 0.85rem; color: #595959; }}
            .status-dot {{ width: 8px; height: 8px; background: #22c55e; border-radius: 50%; }}

            .main-content {{ flex: 1; display: flex; flex-direction: column; background: #000; width: 100%; overflow: hidden; }}
            .top-nav {{ padding: 16px 20px; border-bottom: 1px solid #1a1a1a; display: flex; justify-content: space-between; align-items: center; background: #080808; }}
            .top-left-group {{ display: flex; align-items: center; gap: 12px; }}
            .menu-btn {{ display: none; background: #121212; border: 1px solid #222; color: #b5b5b5; padding: 6px 10px; border-radius: 6px; cursor: pointer; }}
            .top-title-wrapper {{ display: flex; flex-direction: column; gap: 2px; }}
            .top-title {{ font-weight: 600; font-size: 0.95rem; color: #b5b5b5; }}
            .model-badge {{ font-size: 0.7rem; color: #777; background: #121212; border: 1px solid #222; padding: 2px 8px; border-radius: 10px; width: fit-content; font-weight: 500; }}
            
            .mode-switch {{ display: flex; background: #121212; border: 1px solid #222; border-radius: 16px; padding: 2px; }}
            .mode-btn {{ background: transparent; border: none; color: #777; padding: 6px 12px; border-radius: 14px; font-size: 0.8rem; font-weight: 600; cursor: pointer; transition: all 0.2s; }}
            .mode-btn.active {{ background: #262626; color: #fff; }}

            .ai-status-badge {{ font-size: 0.7rem; background: rgba(255,255,255,0.03); color: #a6a6a6; padding: 4px 10px; border-radius: 20px; border: 1px solid rgba(255,255,255,0.1); display: none; align-items: center; gap: 6px; font-weight: 600; }}
            .ai-status-badge.active {{ display: inline-flex; animation: pulseBadge 1.5s infinite; }}
            @keyframes pulseBadge {{ 0% {{ opacity: 0.5; }} 50% {{ opacity: 1; border-color: #888; }} 100% {{ opacity: 0.5; }} }}

            .clear-btn {{ background: #121212; color: #8c8c8c; border: 1px solid #222; padding: 6px 12px; border-radius: 16px; cursor: pointer; font-size: 0.8rem; }}
            .clear-btn:hover {{ background: #1c1c1c; color: #fff; }}

            .chat-messages {{ flex: 1; padding: 20px; overflow-y: auto; display: flex; flex-direction: column; gap: 16px; justify-content: center; align-items: center; }}
            
            .welcome-container {{ display: flex; flex-direction: column; align-items: center; gap: 16px; max-width: 480px; width: 100%; text-align: center; }}
            .welcome-card {{ background: #080808; border: 1px solid #1a1a1a; border-radius: 16px; padding: 18px 20px; width: 100%; }}
            .welcome-title {{ font-weight: 600; font-size: 0.95rem; color: #cccccc; margin-bottom: 4px; }}
            .welcome-subtitle {{ font-size: 0.8rem; color: #595959; }}

            .chips-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; width: 100%; }}
            .chip {{ background: #0a0a0a; border: 1px solid #1c1c1c; border-radius: 16px; padding: 10px 14px; color: #8c8c8c; font-size: 0.82rem; cursor: pointer; text-align: left; transition: all 0.2s; display: flex; align-items: center; gap: 8px; }}
            .chip:hover {{ background: #161616; border-color: #333; color: #ccc; }}

            .message {{ padding: 12px 16px; border-radius: 14px; max-width: 85%; line-height: 1.5; overflow-wrap: break-word; white-space: pre-wrap; font-size: 0.95rem; align-self: flex-start; }}
            .message.user {{ background: #242424 !important; color: #e0e0e0 !important; align-self: flex-end; border: 1px solid #333; }}
            .message.ai {{ background: #0e0e0e; color: #b5b5b5; border: 1px solid #222; }}
            .message img {{ max-width: 100%; border-radius: 10px; margin-top: 8px; display: block; }}
            
            .file-preview-pill {{ display: inline-flex; align-items: center; gap: 6px; background: #181818; border: 1px solid #333; padding: 4px 10px; border-radius: 12px; font-size: 0.75rem; color: #ccc; margin-bottom: 8px; width: fit-content; }}
            .file-preview-pill button {{ background: none; border: none; color: #888; cursor: pointer; font-weight: bold; font-size: 1rem; }}

            .input-container {{ padding: 16px 20px; background: #000; }}
            .input-box {{ background: #080808; border: 1px solid #1a1a1a; border-radius: 20px; display: flex; flex-direction: column; padding: 10px 14px; box-shadow: 0 4px 12px rgba(0,0,0,0.3); }}
            .input-row {{ display: flex; align-items: center; gap: 10px; width: 100%; }}
            
            textarea {{ flex: 1; background: transparent; border: none; color: #b5b5b5; font-size: 0.95rem; resize: none; outline: none; max-height: 120px; padding: 4px 0; }}
            textarea::placeholder {{ color: #4a4a4a; }}

            .attach-btn {{ background: #141414; border: 1px solid #222; color: #aaa; min-width: 36px; height: 36px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 1.1rem; cursor: pointer; transition: all 0.2s; flex-shrink: 0; }}
            .attach-btn:hover {{ background: #222; color: #fff; border-color: #444; }}
            
            .send-btn {{ background: #262626; color: #d0d0d0; border: 1px solid #333; padding: 8px 16px; border-radius: 16px; font-weight: bold; cursor: pointer; font-size: 0.9rem; flex-shrink: 0; }}
            .send-btn:hover {{ background: #333; color: #fff; }}
            .send-btn:disabled {{ background: #161616; color: #444; cursor: not-allowed; }}

            @media (max-width: 768px) {{
                .sidebar {{ position: absolute; height: 100%; left: 0; top: 0; transform: translateX(-100%); }}
                .sidebar.open {{ transform: translateX(0); }}
                .close-sidebar-btn {{ display: block; }}
                .menu-btn {{ display: inline-flex; }}
                .chips-grid {{ grid-template-columns: 1fr; }}
            }}
        </style>
    </head>
    <body>
        <div id="deployOverlay" class="deploy-overlay" aria-live="polite">
            <div class="deploy-card">
                <div class="deploy-spinner"></div>
                <div class="deploy-title">Сайт обновляется</div>
                <div class="deploy-text" id="deployOverlayText">
                    Новая версия уже собирается на Render. Пожалуйста, не закрывайте страницу.
                </div>
                <div class="deploy-hint">
                    После завершения сайт обновится автоматически.
                </div>
            </div>
        </div>

        <div id="sidebar" class="sidebar">
            <div class="logo-area">
                <div>
                    <div class="logo-title">RUBINOV-AI</div>
                    <div class="logo-subtitle">MULTIMODAL CHAT</div>
                </div>
                <button class="close-sidebar-btn" onclick="toggleSidebar()">✕</button>
            </div>
            
            <button class="new-chat-btn" onclick="startNewChat()">
                <span>+</span> Новый чат
            </button>
            
            <div class="chats-section-title">История чатов</div>
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
                <div style="display: flex; align-items: center; gap: 10px;">
                    <div class="mode-switch">
                        <button id="modeChat" class="mode-btn active" onclick="setMode('chat')">💬 Чат</button>
                        <button id="modeImage" class="mode-btn" onclick="setMode('image')">🎨 Картинка</button>
                    </div>
                    <div id="aiStatusBadge" class="ai-status-badge">
                        <span style="width: 6px; height: 6px; background: #fff; border-radius: 50%;"></span>
                        ОБРАБОТКА...
                    </div>
                    <button class="clear-btn" onclick="clearCurrentChat()">Очистить</button>
                </div>
            </div>

            <div id="chatMessages" class="chat-messages">
                <div class="welcome-container" id="welcomeContainer">
                    <div class="welcome-card">
                        <div class="welcome-title">Чем я могу помочь сегодня?</div>
                        <div class="welcome-subtitle">Задайте вопрос, загрузите файл или переключитесь в режим создания картинок.</div>
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
            const CURRENT_BUILD_ID = "{SERVER_BUILD_ID}";
            const CURRENT_DEPLOY_COMMIT = "{CURRENT_COMMIT}";

            let deployUpdatingShown = false;
            let deployReloadScheduled = false;

            function setDeployOverlay(active, text = null) {{
                const overlay = document.getElementById('deployOverlay');
                if (!overlay) return;

                overlay.classList.toggle('active', active);

                if (text) {{
                    document.getElementById('deployOverlayText').innerText = text;
                }}
            }}

            function hardReloadAfterDeploy() {{
                if (deployReloadScheduled) return;
                deployReloadScheduled = true;

                const url = new URL(window.location.href);
                url.searchParams.set('_updated', Date.now().toString());

                window.location.replace(url.toString());
            }}

            async function checkDeployStatus() {{
                try {{
                    const res = await fetch('/api/deploy-status?t=' + Date.now(), {{
                        cache: 'no-store',
                        headers: {{ 'Cache-Control': 'no-cache' }}
                    }});

                    if (!res.ok) return;

                    const data = await res.json();

                    if (data.updating) {{
                        if (!deployUpdatingShown) {{
                            deployUpdatingShown = true;
                            setDeployOverlay(
                                true,
                                'Новая версия уже отправлена в GitHub и сейчас собирается на Render.'
                            );
                        }}
                        return;
                    }}

                    const newVersionStarted =
                        CURRENT_DEPLOY_COMMIT &&
                        data.current_commit &&
                        data.current_commit !== CURRENT_DEPLOY_COMMIT;

                    const backendRestarted =
                        data.build_id &&
                        data.build_id !== CURRENT_BUILD_ID;

                    if (newVersionStarted || backendRestarted) {{
                        setDeployOverlay(
                            true,
                            'Сборка завершена. Перезапускаю сайт и загружаю новую версию...'
                        );

                        setTimeout(hardReloadAfterDeploy, 350);
                    }}
                }} catch (e) {{}}
            }}

            checkDeployStatus();
            setInterval(checkDeployStatus, 4000);

            let chats = JSON.parse(localStorage.getItem('rubinov_chats') || '[]');
            let currentChatId = localStorage.getItem('rubinov_current_id') || null;
            let selectedFile = null;
            let currentMode = 'chat';

            function setMode(mode) {{
                currentMode = mode;
                document.getElementById('modeChat').classList.toggle('active', mode === 'chat');
                document.getElementById('modeImage').classList.toggle('active', mode === 'image');
                const textarea = document.getElementById('userInput');
                textarea.placeholder = mode === 'image' ? 'Опишите картинку для генерации...' : 'Введите сообщение...';
            }}

            window.addEventListener('DOMContentLoaded', () => {{
                renderChatsList();
                if (currentChatId) {{
                    loadChat(currentChatId);
                }}
            }});

            function toggleSidebar() {{
                document.getElementById('sidebar').classList.toggle('open');
            }}

            function autoResize(textarea) {{
                textarea.style.height = 'auto';
                textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
            }}

            function handleKeyDown(e) {{
                if (e.key === 'Enter' && !e.shiftKey) {{
                    e.preventDefault();
                    sendMessage();
                }}
            }}

            function handleFileSelect(e) {{
                const file = e.target.files[0];
                if (!file) return;
                selectedFile = file;
                const previewArea = document.getElementById('filePreviewArea');
                previewArea.innerHTML = `
                    <div class="file-preview-pill">
                        <span>📎 ${{file.name}}</span>
                        <button onclick="removeFile()">×</button>
                    </div>
                `;
            }}

            function removeFile() {{
                selectedFile = null;
                document.getElementById('fileInput').value = '';
                document.getElementById('filePreviewArea').innerHTML = '';
            }}

            function sendPreset(text) {{
                document.getElementById('userInput').value = text;
                if (text.includes('Нарисовать')) {{
                    setMode('image');
                }}
                sendMessage();
            }}

            function startNewChat() {{
                currentChatId = null;
                localStorage.removeItem('rubinov_current_id');
                document.getElementById('currentChatTitle').innerText = 'Новый диалог';
                document.getElementById('chatMessages').innerHTML = `
                    <div class="welcome-container" id="welcomeContainer">
                        <div class="welcome-card">
                            <div class="welcome-title">Чем я могу помочь сегодня?</div>
                            <div class="welcome-subtitle">Задайте вопрос, загрузите файл или переключитесь в режим создания картинок.</div>
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
            }}

            function clearCurrentChat() {{
                startNewChat();
            }}

            function renderChatsList() {{
                const list = document.getElementById('chatsList');
                list.innerHTML = '';
                chats.forEach(chat => {{
                    const div = document.createElement('div');
                    div.className = `chat-item ${{chat.id === currentChatId ? 'active' : ''}}`;
                    div.innerHTML = `
                        <span class="chat-title-text" onclick="loadChat('${{chat.id}}')">${{chat.title}}</span>
                        <button class="delete-chat-btn" onclick="deleteChat(event, '${{chat.id}}')">×</button>
                    `;
                    list.appendChild(div);
                });
            }}

            function deleteChat(e, id) {{
                e.stopPropagation();
                chats = chats.filter(c => c.id !== id);
                localStorage.setItem('rubinov_chats', JSON.stringify(chats));
                if (currentChatId === id) {{
                    startNewChat();
                }} else {{
                    renderChatsList();
                }}
            }}

            function loadChat(id) {{
                const chat = chats.find(c => c.id === id);
                if (!chat) return;
                currentChatId = id;
                localStorage.setItem('rubinov_current_id', id);
                document.getElementById('currentChatTitle').innerText = chat.title;
                
                const container = document.getElementById('chatMessages');
                container.innerHTML = '';
                chat.messages.forEach(m => {{
                    const msgDiv = document.createElement('div');
                    msgDiv.className = `message ${{m.role}}`;
                    msgDiv.innerHTML = m.content;
                    container.appendChild(msgDiv);
                }});
                container.scrollTop = container.scrollHeight;
                renderChatsList();
                if (window.innerWidth <= 768) toggleSidebar();
            }}

            async function sendMessage() {{
                const input = document.getElementById('userInput');
                const text = input.value.trim();
                if (!text && !selectedFile) return;

                const welcome = document.getElementById('welcomeContainer');
                if (welcome) welcome.remove();

                const container = document.getElementById('chatMessages');
                
                const userMsgDiv = document.createElement('div');
                userMsgDiv.className = 'message user';
                let displayContent = text;
                if (selectedFile) {{
                    displayContent = `[Файл: ${{selectedFile.name}}]<br>` + displayContent;
                }}
                userMsgDiv.innerHTML = displayContent;
                container.appendChild(userMsgDiv);

                input.value = '';
                input.style.height = 'auto';
                const fileToSend = selectedFile;
                removeFile();

                document.getElementById('aiStatusBadge').classList.add('active');
                document.getElementById('sendBtn').disabled = true;
                container.scrollTop = container.scrollHeight;

                try {{
                    let responseHtml = '';

                    if (currentMode === 'image') {{
                        const imgRes = await fetch('/api/generate-image', {{
                            method: 'POST',
                            headers: {{'Content-Type': 'application/json'}},
                            body: JSON.stringify({{ prompt: text }})
                        }});
                        const imgData = await imgRes.json();
                        if (!imgRes.ok) throw new Error(imgData.detail || 'Ошибка генерации картинки');
                        responseHtml = `Сгенерированное изображение по запросу: "${{text}}"<br><img src="${{imgData.image_url}}" alt="Generated Image">`;
                    }} else {{
                        let currentHistory = [];
                        if (currentChatId) {{
                            const activeChat = chats.find(c => c.id === currentChatId);
                            if (activeChat) {{
                                currentHistory = activeChat.messages.map(m => ({{
                                    role: m.role,
                                    content: m.content
                                }}));
                            }}
                        }}

                        const formData = new FormData();
                        formData.append('message', text);
                        formData.append('history', JSON.stringify(currentHistory));
                        if (fileToSend) {{
                            formData.append('file', fileToSend);
                        }}

                        const res = await fetch('/api/chat', {{
                            method: 'POST',
                            body: formData
                        }});
                        const data = await res.json();
                        if (!res.ok) throw new Error(data.detail || 'Ошибка сервера');
                        responseHtml = data.response;
                    }}

                    const aiMsgDiv = document.createElement('div');
                    aiMsgDiv.className = 'message ai';
                    aiMsgDiv.innerHTML = responseHtml;
                    container.appendChild(aiMsgDiv);

                    if (!currentChatId) {{
                        currentChatId = 'chat_' + Date.now();
                        localStorage.setItem('rubinov_current_id', currentChatId);
                        
                        let chatTitle = text.slice(0, 25) + '...';
                        if (currentMode === 'chat') {{
                            try {{
                                const titleRes = await fetch('/api/title', {{
                                    method: 'POST',
                                    headers: {{'Content-Type': 'application/json'}},
                                    body: JSON.stringify({{ message: text }})
                                }});
                                const titleData = await titleRes.json();
                                if (titleData.title) chatTitle = titleData.title;
                            }} catch(err) {{}}
                        }} else {{
                            chatTitle = '🎨 ' + text.slice(0, 20) + '...';
                        }}

                        document.getElementById('currentChatTitle').innerText = chatTitle;
                        
                        chats.unshift({{
                            id: currentChatId,
                            title: chatTitle,
                            messages: [
                                {{ role: 'user', content: displayContent }},
                                {{ role: 'ai', content: responseHtml }}
                            ]
                        }});
                    }} else {{
                        const chat = chats.find(c => c.id === currentChatId);
                        if (chat) {{
                            chat.messages.push({{ role: 'user', content: displayContent }});
                            chat.messages.push({{ role: 'ai', content: responseHtml }});
                        }}
                    }}
                    localStorage.setItem('rubinov_chats', JSON.stringify(chats));
                    renderChatsList();

                }} catch (err) {{
                    const errDiv = document.createElement('div');
                    errDiv.className = 'message ai';
                    errDiv.style.color = '#ef4444';
                    errDiv.innerText = 'Ошибка: ' + err.message;
                    container.appendChild(errDiv);
                }} finally {{
                    document.getElementById('aiStatusBadge').classList.remove('active');
                    document.getElementById('sendBtn').disabled = false;
                    container.scrollTop = container.scrollHeight;
                }}
            }}
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content, headers={
        "Cache-Control": "no-cache, no-store, max-age=0, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0"
    })

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)

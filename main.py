import os
import time
import json
import uuid
import io
import base64
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from google import genai
from google.genai import types

app = FastAPI()

# Уникальный ID текущей сборки сервера
SERVER_BUILD_ID = str(uuid.uuid4())[:8]
IMAGE_GEN_ENABLED = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

client = genai.Client()
CHAT_MODEL = "gemini-2.5-flash"
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
            
            /* Изначально класс .hidden убран, но мы добавим логику через JS */
            .site-update-overlay {{
                position: fixed; top: 0; left: 0; width: 100%; height: 100%;
                background: #000000; z-index: 99999; display: flex;
                flex-direction: column; align-items: center; justify-content: center;
                gap: 20px; opacity: 0; pointer-events: none; transition: opacity 0.4s ease;
            }}
            .site-update-overlay.visible {{ opacity: 1; pointer-events: auto; }}
            
            .update-spinner {{
                width: 56px; height: 56px; border: 3px solid rgba(255, 255, 255, 0.1);
                border-top-color: #ffffff; border-radius: 50%; animation: spin 0.8s linear infinite;
            }}
            .site-update-title {{ font-size: 1.6rem; font-weight: 800; color: #ffffff; text-transform: uppercase; letter-spacing: 1px; }}
            .site-update-subtitle {{ font-size: 0.95rem; color: #666666; font-weight: 500; text-align: center; padding: 0 20px; }}
            @keyframes spin {{ to {{ transform: rotate(360deg); }} }}

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
        <div id="siteUpdateOverlay" class="site-update-overlay">
            <div class="update-spinner"></div>
            <div class="site-update-title">Сайт на обновлении</div>
            <div class="site-update-subtitle">Выполняется сборка сервера (Билд: <span id="buildIdText">{SERVER_BUILD_ID}</span>)...</div>
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
                        <div class="model-badge">⚡ gemini-2.5-flash</div>
                    </div>
                </div>
                <div style="display: flex; align-items: center; gap: 10px;">
                    <div class="mode-switch">
                        <button id="modeChat" class="mode-btn active" onclick="setMode('chat')">💬 Чат</button>
                        <button id="modeImage" class="mode-btn" onclick

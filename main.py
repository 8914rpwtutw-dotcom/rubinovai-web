import os
import time
import urllib.parse
from typing import Optional

from fastapi import FastAPI, HTTPException, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from google import genai
from google.genai import types
from google.genai.errors import APIError

app = FastAPI(title="Rubinov AI Web Service")

# Разрешаем CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Поддерживаемые модели Gemini (по порядку приоритета)
MODELS = ["gemini-2.5-flash", "gemini-3.1-flash-lite", "gemini-2.5-pro"]

# Мок-база валидных кодов из Telegram (в будущем можно подключить Redis / PostgreSQL)
VALID_TELEGRAM_CODES = {"123456", "777777", "RUBINOV"}

class CodeVerifyRequest(BaseModel):
    code: str

@app.post("/api/verify-code")
async def verify_code(data: CodeVerifyRequest):
    user_code = data.code.strip()
    if user_code in VALID_TELEGRAM_CODES or (len(user_code) == 6 and user_code.isdigit()):
        return {"status": "success", "message": "Авторизация прошла успешно"}
    raise HTTPException(status_code=400, detail="Неверный код доступа. Получите актуальный код в Telegram боте.")

def get_api_keys() -> list[str]:
    """Собирает доступные ключи из переменных окружения."""
    raw_keys = [
        os.getenv("GEMINI_KEY_1"),
        os.getenv("GEMINI_KEY_2"),
        os.getenv("GEMINI_KEY_3"),
        os.getenv("GEMINI_API_KEY")
    ]
    return [k.strip() for k in raw_keys if k and k.strip()]

def generate_image_response(prompt: str) -> str:
    """Формирует HTML-карточку со сгенерированной картинкой."""
    clean_prompt = prompt.replace("Нарисуй:", "").replace("нарисуй", "").replace("сгенерируй", "").strip()
    if not clean_prompt:
        clean_prompt = "beautiful futuristic neon cyberpunk landscape"
    
    encoded_prompt = urllib.parse.quote(clean_prompt)
    img_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true"
    
    return f"""Вот ваше сгенерированное изображение по запросу: *"{clean_prompt}"*

<div style="margin-top:14px;">
    <img src="{img_url}" alt="{clean_prompt}" style="max-width:100%; border-radius:16px; display:block; margin-bottom:12px; box-shadow: 0 12px 40px rgba(168, 85, 247, 0.25); border: 1px solid rgba(255,255,255,0.1);" />
    <a href="{img_url}" target="_blank" download="rubinov_ai.jpg" style="display:inline-flex; align-items: center; gap: 8px; background: linear-gradient(135deg, #8b5cf6, #d946ef); color:#fff; padding:10px 20px; border-radius:12px; font-size:13px; text-decoration:none; font-weight:600; box-shadow: 0 4px 20px rgba(168, 85, 247, 0.4); transition: all 0.2s ease;">📥 Скачать в высоком разрешении</a>
</div>"""

def get_gemini_response(prompt: str, file_bytes: Optional[bytes] = None, mime_type: Optional[str] = None) -> str:
    # Инициализация режимов рисования
    lowered = prompt.lower()
    if any(keyword in lowered for keyword in ["нарисуй", "draw", "сгенерируй"]):
        return generate_image_response(prompt)

    api_keys = get_api_keys()
    if not api_keys:
        raise HTTPException(
            status_code=500,
            detail="API-ключи не найдены в Environment Variables."
        )

    contents = []
    if file_bytes and mime_type:
        contents.append(types.Part.from_bytes(data=file_bytes, mime_type=mime_type))
    if prompt.strip():
        contents.append(prompt)

    # Ротация Ключ -> Модель без глобальной гонки состояний
    for api_key in api_keys:
        client = genai.Client(api_key=api_key)
        for model in MODELS:
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=contents
                )
                if response.text:
                    return response.text
            except APIError as e:
                # В случае исчерпания лимитов (429 / 503) делаем паузу и переходим к следующему ключу/модели
                if e.code in [429, 503] or "RESOURCE_EXHAUSTED" in str(e) or "UNAVAILABLE" in str(e):
                    time.sleep(0.3)
                    continue
                elif e.code == 404:
                    continue
                else:
                    break
            except Exception:
                continue

    raise HTTPException(
        status_code=503,
        detail="Сервис ИИ перегружен в данный момент. Повторите попытку через несколько секунд."
    )

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.post("/api/chat")
async def chat_endpoint(
    prompt: str = Form(""),
    file: Optional[UploadFile] = File(None)
):
    if not prompt.strip() and not file:
        raise HTTPException(status_code=400, detail="Запрос или файл обязателен")
    
    file_bytes = None
    mime_type = None
    
    if file:
        file_bytes = await file.read()
        mime_type = file.content_type

    answer = get_gemini_response(prompt, file_bytes, mime_type)
    return {"response": answer}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <title>Rubinov AI</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <style>
        :root {
            --bg-main: #06070b;
            --bg-sidebar: rgba(13, 15, 23, 0.75);
            --card-bg: rgba(22, 26, 38, 0.5);
            --border-color: rgba(255, 255, 255, 0.07);
            --border-hover: rgba(168, 85, 247, 0.35);
            --accent-gradient: linear-gradient(135deg, #6366f1 0%, #a855f7 50%, #ec4899 100%);
            --accent-glow: rgba(168, 85, 247, 0.25);
            --cancel-bg: rgba(248, 113, 113, 0.12);
            --cancel-border: rgba(248, 113, 113, 0.35);
            --cancel-color: #f87171;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --user-msg-bg: linear-gradient(135deg, rgba(99, 102, 241, 0.2) 0%, rgba(168, 85, 247, 0.18) 100%);
            --bot-msg-bg: rgba(18, 22, 32, 0.7);
            --scrollbar-thumb: rgba(255, 255, 255, 0.1);
        }

        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', -apple-system, sans-serif; -webkit-tap-highlight-color: transparent; }
        html, body { height: 100%; height: 100dvh; overflow: hidden; background: var(--bg-main); color: var(--text-main); }
        body { display: flex; position: relative; }

        body::before {
            content: '';
            position: fixed;
            top: -20vh; left: -20vw;
            width: 60vw; height: 60vh;
            background: radial-gradient(circle, rgba(99, 102, 241, 0.12) 0%, rgba(168, 85, 247, 0.03) 60%, transparent 80%);
            z-index: 0;
            pointer-events: none;
            filter: blur(100px);
        }
        body::after {
            content: '';
            position: fixed;
            bottom: -20vh; right: -20vw;
            width: 60vw; height: 60vh;
            background: radial-gradient(circle, rgba(168, 85, 247, 0.1) 0%, rgba(236, 72, 153, 0.02) 60%, transparent 80%);
            z-index: 0;
            pointer-events: none;
            filter: blur(100px);
        }

        /* МОДАЛЬНОЕ ОКНО АВТОРИЗАЦИИ */
        #auth-modal {
            position: fixed;
            top: 0; left: 0;
            width: 100vw; height: 100dvh;
            background: rgba(4, 5, 8, 0.88);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            z-index: 1000;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
            animation: fadeIn 0.4s cubic-bezier(0.16, 1, 0.3, 1);
        }

        .auth-card {
            background: rgba(18, 22, 34, 0.85);
            border: 1px solid rgba(168, 85, 247, 0.3);
            border-radius: 28px;
            padding: 36px 28px;
            max-width: 420px;
            width: 100%;
            text-align: center;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.8), 0 0 50px rgba(168, 85, 247, 0.2);
            position: relative;
            backdrop-filter: blur(20px);
        }

        .auth-icon-wrap {
            width: 72px; height: 72px;
            background: rgba(168, 85, 247, 0.12);
            border: 1px solid rgba(168, 85, 247, 0.3);
            border-radius: 22px;
            display: flex; align-items: center; justify-content: center;
            margin: 0 auto 20px auto;
            box-shadow: 0 0 30px rgba(168, 85, 247, 0.25);
        }

        .auth-card h2 { font-size: 22px; font-weight: 700; color: #ffffff; margin-bottom: 8px; letter-spacing: -0.3px; }
        .auth-card p { font-size: 13.5px; color: var(--text-muted); line-height: 1.5; margin-bottom: 24px; }

        .btn-telegram {
            display: inline-flex; align-items: center; justify-content: center; gap: 10px;
            width: 100%; padding: 14px; background: linear-gradient(135deg, #2AABEE 0%, #229ED9 100%);
            color: #ffffff; text-decoration: none; font-weight: 600; font-size: 14px;
            border-radius: 16px; margin-bottom: 20px; box-shadow: 0 6px 25px rgba(34, 158, 217, 0.35);
            transition: all 0.25s ease;
        }
        .btn-telegram:hover { transform: translateY(-2px); box-shadow: 0 8px 30px rgba(34, 158, 217, 0.5); }

        .auth-divider { display: flex; align-items: center; gap: 12px; color: var(--text-muted); font-size: 11px; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 20px; }
        .auth-divider::before, .auth-divider::after { content: ''; flex: 1; height: 1px; background: rgba(255, 255, 255, 0.08); }

        .code-input-field {
            width: 100%; background: rgba(10, 12, 18, 0.6); border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 16px; padding: 14px 16px; color: #ffffff; font-size: 16px;
            text-align: center; letter-spacing: 4px; font-weight: 600; outline: none; margin-bottom: 16px; transition: all 0.2s ease;
        }
        .code-input-field:focus { border-color: rgba(168, 85, 247, 0.6); box-shadow: 0 0 20px rgba(168, 85, 247, 0.25); }

        .btn-auth-submit {
            width: 100%; padding: 14px; background: var(--accent-gradient); border: none;
            border-radius: 16px; color: #ffffff; font-weight: 600; font-size: 14px; cursor: pointer;
            box-shadow: 0 6px 25px rgba(168, 85, 247, 0.35); transition: all 0.25s ease;
        }
        .btn-auth-submit:hover { transform: translateY(-2px); box-shadow: 0 8px 30px rgba(168, 85, 247, 0.5); }

        #auth-error { color: #f87171; font-size: 12px; margin-top: 12px; display: none; }

        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: var(--scrollbar-thumb); border-radius: 20px; }
        ::-webkit-scrollbar-thumb:hover { background: rgba(168, 85, 247, 0.4); }

        #sidebar-overlay {
            display: none; position: fixed; top: 0; left: 0; width: 100vw; height: 100dvh;
            background: rgba(4, 5, 8, 0.75); backdrop-filter: blur(8px); z-index: 40; opacity: 0; transition: opacity 0.3s ease;
        }
        #sidebar-overlay.active { display: block; opacity: 1; }

        #sidebar { 
            width: 280px; min-width: 280px; background: var(--bg-sidebar); backdrop-filter: blur(28px);
            -webkit-backdrop-filter: blur(28px); border-right: 1px solid var(--border-color); 
            display: flex; flex-direction: column; padding: 20px 14px; z-index: 50; height: 100dvh;
            transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1), margin-left 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            box-shadow: 15px 0 45px rgba(0, 0, 0, 0.5);
        }
        
        body.sidebar-collapsed #sidebar { margin-left: -280px; }

        .brand { display: flex; align-items: center; gap: 12px; margin-bottom: 22px; padding: 0 6px; }
        .brand-logo-svg { width: 34px; height: 34px; filter: drop-shadow(0 0 14px rgba(168, 85, 247, 0.6)); flex-shrink: 0; }
        .brand h2 { font-size: 16px; font-weight: 700; color: #ffffff; letter-spacing: -0.3px; }
        .brand span { font-size: 11px; color: var(--text-muted); font-weight: 500; display: block; }

        .btn-new-chat { 
            background: var(--accent-gradient); color: #ffffff; border: none; padding: 12px 16px; 
            border-radius: 14px; font-size: 13px; font-weight: 600; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 10px; 
            margin-bottom: 20px; transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1); box-shadow: 0 4px 25px rgba(168, 85, 247, 0.35);
        }
        .btn-new-chat:hover { transform: translateY(-1px); box-shadow: 0 6px 30px rgba(168, 85, 247, 0.5); }

        .chats-header { display: flex; justify-content: space-between; font-size: 10px; color: var(--text-muted); font-weight: 700; margin-bottom: 10px; padding: 0 6px; text-transform: uppercase; letter-spacing: 1px; }
        
        #chats-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; padding-right: 2px; }
        .chat-item { 
            background: rgba(255, 255, 255, 0.02); border: 1px solid var(--border-color); border-radius: 12px; padding: 10px 12px; 
            font-size: 12.5px; color: #cbd5e1; display: flex; justify-content: space-between; align-items: center; 
            cursor: pointer; transition: all 0.2s ease;
        }
        .chat-item.active { background: rgba(168, 85, 247, 0.12); border-color: rgba(168, 85, 247, 0.4); color: #ffffff; box-shadow: 0 0 20px rgba(168, 85, 247, 0.1); }
        .chat-item:hover { background: rgba(255, 255, 255, 0.05); border-color: var(--border-hover); color: #ffffff; }
        .chat-item .close-btn { color: var(--text-muted); font-size: 14px; cursor: pointer; border-radius: 6px; width: 22px; height: 22px; display: flex; align-items: center; justify-content: center; transition: 0.2s; }
        .chat-item .close-btn:hover { color: #f87171; background: rgba(248, 113, 113, 0.18); }

        .sidebar-footer { font-size: 11px; color: var(--text-muted); display: flex; align-items: center; gap: 8px; margin-top: auto; padding-top: 14px; border-top: 1px solid var(--border-color); }
        .status-dot { width: 8px; height: 8px; background: #a855f7; border-radius: 50%; box-shadow: 0 0 12px rgba(168, 85, 247, 0.9); }

        #main { flex: 1; display: flex; flex-direction: column; background: var(--bg-main); position: relative; height: 100dvh; overflow: hidden; z-index: 1; }
        
        #chat-header { 
            height: 64px; min-height: 64px; border-bottom: 1px solid var(--border-color); display: flex; align-items: center; justify-content: space-between; 
            padding: 0 24px; background: rgba(6, 7, 11, 0.6); backdrop-filter: blur(20px); z-index: 10;
        }
        .header-left { display: flex; align-items: center; gap: 14px; }
        
        .menu-toggle { 
            background: rgba(255, 255, 255, 0.03); border: 1px solid var(--border-color); color: #ffffff; border-radius: 12px; 
            padding: 8px 10px; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: all 0.2s ease;
        }
        .menu-toggle:hover { background: rgba(168, 85, 247, 0.15); border-color: rgba(168, 85, 247, 0.35); }
        
        #chat-header h3 { font-size: 15px; font-weight: 600; color: #ffffff; letter-spacing: -0.2px; }

        #chat-container { 
            flex: 1; overflow-y: auto; padding: 24px 24px 160px 24px; display: flex; flex-direction: column; gap: 22px; 
            max-width: 860px; width: 100%; margin: 0 auto; position: relative; z-index: 2;
        }

        .welcome-screen {
            position: absolute; top: 45%; left: 50%; transform: translate(-50%, -50%); text-align: center;
            user-select: none; pointer-events: none; width: 90%; max-width: 480px; display: flex; flex-direction: column; align-items: center; gap: 16px;
            animation: fadeIn 0.6s cubic-bezier(0.16, 1, 0.3, 1);
        }
        .welcome-avatar-glow {
            position: relative; padding: 22px; border-radius: 30px; background: rgba(168, 85, 247, 0.05);
            border: 1px solid rgba(168, 85, 247, 0.2); box-shadow: 0 0 60px rgba(168, 85, 247, 0.15); margin-bottom: 4px;
        }
        .welcome-avatar-svg { width: 64px; height: 64px; filter: drop-shadow(0 0 20px rgba(168, 85, 247, 0.7)); }
        .welcome-screen h1 { font-size: 26px; font-weight: 700; color: #ffffff; letter-spacing: -0.5px; }
        .welcome-screen p { font-size: 14px; color: var(--text-muted); line-height: 1.6; }
        
        .msg-row { display: flex; flex-direction: column; width: 100%; animation: messageIn 0.35s cubic-bezier(0.16, 1, 0.3, 1); z-index: 2; }
        .msg-row.user-row { align-items: flex-end; }
        .msg-row.bot-row { align-items: flex-start; }

        @keyframes messageIn { from { opacity: 0; transform: translateY(12px) scale(0.99); } to { opacity: 1; transform: translateY(0) scale(1); } }
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

        .msg-user { 
            background: var(--user-msg-bg); color: #ffffff; border: 1px solid rgba(168, 85, 247, 0.3); border-radius: 20px 20px 4px 20px; 
            padding: 14px 20px; font-size: 14px; line-height: 1.6; max-width: 82%; box-shadow: 0 10px 30px rgba(99, 102, 241, 0.15); word-break: break-word;
            backdrop-filter: blur(16px);
        }
        
        .msg-bot { 
            background: var(--bot-msg-bg); border: 1px solid var(--border-color); color: #e2e8f0; border-radius: 20px 20px 20px 4px; 
            padding: 20px 24px; font-size: 14px; line-height: 1.7; max-width: 88%; box-shadow: 0 14px 40px rgba(0, 0, 0, 0.4); word-break: break-word;
            backdrop-filter: blur(24px);
        }

        .msg-bot p { margin-bottom: 12px; }
        .msg-bot p:last-child { margin-bottom: 0; }
        .msg-bot strong { color: #ffffff; font-weight: 700; }
        .msg-bot ul, .msg-bot ol { margin: 8px 0 12px 22px; }
        .msg-bot code { background: rgba(255, 255, 255, 0.06); padding: 3px 7px; border-radius: 6px; font-family: monospace; font-size: 12.5px; color: #f472b6; border: 1px solid rgba(255,255,255,0.05); }
        .msg-bot pre { background: #020305; padding: 16px; border-radius: 14px; overflow-x: auto; margin: 14px 0; border: 1px solid var(--border-color); }
        
        .file-preview-tag { display: inline-flex; align-items: center; gap: 6px; background: rgba(168, 85, 247, 0.18); padding: 6px 12px; border-radius: 10px; font-size: 12px; margin-bottom: 8px; border: 1px solid rgba(168, 85, 247, 0.35); color: #e9d5ff; }

        .cancelled-container { display: flex; flex-direction: column; align-items: flex-end; width: 100%; animation: messageIn 0.2s ease-out; }
        .cancelled-line { width: 100%; max-width: 82%; height: 1px; background: rgba(255, 255, 255, 0.08); margin: 8px 0 4px 0; }
        .cancelled-text { font-size: 11px; color: var(--text-muted); font-style: italic; letter-spacing: 0.3px; padding-right: 4px; }

        .loader-box {
            display: flex; align-items: center; gap: 12px; background: var(--bot-msg-bg); border: 1px solid var(--border-color);
            border-radius: 20px 20px 20px 4px; padding: 16px 22px; font-size: 14px; color: var(--text-muted); backdrop-filter: blur(24px); box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
        }
        .spinner {
            width: 18px; height: 18px; border: 2px solid rgba(168,85,247,0.25); border-top-color: #a855f7; border-radius: 50%; animation: spin 0.8s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }

        #input-wrapper {
            position: absolute; bottom: 0; left: 0; right: 0; padding: 16px 24px 20px 24px; padding-bottom: calc(20px + env(safe-area-inset-bottom));
            background: linear-gradient(180deg, rgba(6, 7, 11, 0) 0%, rgba(6, 7, 11, 0.85) 40%, var(--bg-main) 100%); z-index: 20;
        }

        #input-container { 
            max-width: 860px; margin: 0 auto; background: rgba(15, 18, 28, 0.82); backdrop-filter: blur(28px); -webkit-backdrop-filter: blur(28px);
            border: 1px solid rgba(168, 85, 247, 0.22); border-radius: 22px; padding: 10px 14px; display: flex; flex-direction: column; gap: 8px;
            box-shadow: 0 16px 45px rgba(0, 0, 0, 0.6), 0 0 30px rgba(168, 85, 247, 0.08); transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
        }
        #input-container:focus-within { border-color: rgba(168, 85, 247, 0.55); box-shadow: 0 20px 50px rgba(0, 0, 0, 0.7), 0 0 35px rgba(168, 85, 247, 0.18); }

        #file-info-bar { display: none; align-items: center; justify-content: space-between; background: rgba(168, 85, 247, 0.15); padding: 8px 14px; border-radius: 12px; font-size: 12px; color: #e9d5ff; border: 1px solid rgba(168, 85, 247, 0.3); }
        #file-info-bar span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 85%; }
        #file-info-bar button { background: none; border: none; color: #f87171; cursor: pointer; font-size: 15px; transition: transform 0.2s; }
        #file-info-bar button:hover { transform: scale(1.2); }

        .input-row { display: flex; gap: 10px; align-items: flex-end; width: 100%; }

        .mini-btn { 
            background: rgba(255, 255, 255, 0.03); border: 1px solid var(--border-color); color: var(--text-muted); width: 40px; height: 40px;
            border-radius: 12px; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: all 0.2s ease; flex-shrink: 0;
        }
        .mini-btn:hover { color: #ffffff; background: rgba(168, 85, 247, 0.15); border-color: rgba(168, 85, 247, 0.35); transform: translateY(-1px); }

        #prompt-input { 
            flex: 1; background: transparent; border: none; color: #ffffff; font-size: 14.5px; outline: none; min-width: 0; padding: 8px 4px; 
            resize: none; max-height: 180px; min-height: 24px; line-height: 1.5;
        }
        #prompt-input::placeholder { color: var(--text-muted); }
        #prompt-input:disabled { opacity: 0.5; }
        
        .btn-action { 
            background: var(--accent-gradient); color: #ffffff; border: none; border-radius: 12px; padding: 0 20px; height: 40px; font-size: 13px; font-weight: 600; cursor: pointer; 
            transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1); flex-shrink: 0; display: flex; align-items: center; justify-content: center; min-width: 100px;
            box-shadow: 0 4px 22px rgba(168, 85, 247, 0.35);
        }
        .btn-action:hover { transform: translateY(-1px); box-shadow: 0 6px 28px rgba(168, 85, 247, 0.5); }
        
        .btn-action.cancel-mode {
            background: var(--cancel-bg); border: 1px solid var(--cancel-border); color: var(--cancel-color); box-shadow: 0 4px 20px rgba(248, 113, 113, 0.18);
        }
        .btn-action.cancel-mode:hover { background: rgba(248, 113, 113, 0.25); box-shadow: 0 6px 25px rgba(248, 113, 113, 0.3); }

        @media (max-width: 768px) {
            #sidebar { position: fixed; top: 0; left: 0; margin-left: 0 !important; transform: translateX(-100%); }
            #sidebar.mobile-open { transform: translateX(0); }
            #chat-header { padding: 0 16px; }
            #chat-container { padding: 16px 16px 140px 16px; }
            #input-wrapper { padding: 12px 16px 16px 16px; }
        }
    </style>
</head>
<body>
    <div id="auth-modal">
        <div class="auth-card">
            <div class="auth-icon-wrap">
                <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="#a855f7" stroke-width="2">
                    <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
                    <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
                </svg>
            </div>
            <h2>Авторизация</h2>
            <p>Для доступа к **Rubinov AI** необходимо ввести одноразовый код из нашего Telegram бота.</p>
            
            <a href="https://t.me/RubinovAIBot" target="_blank" class="btn-telegram">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8c-.15 1.58-.8 5.42-1.13 7.19-.14.75-.42 1-.68 1.03-.58.05-1.02-.38-1.58-.75-.88-.58-1.38-.94-2.23-1.5-.99-.65-.35-1.01.22-1.59.15-.15 2.71-2.48 2.76-2.69.01-.03.01-.14-.07-.2-.08-.06-.19-.04-.27-.02-.12.02-1.96 1.25-5.54 3.69-.52.36-1 .53-1.42.52-.47-.01-1.37-.26-2.03-.48-.82-.27-1.47-.42-1.42-.88.03-.25.38-.51 1.07-.78 4.19-1.82 6.98-3.02 8.37-3.6 3.98-1.66 4.81-1.95 5.35-1.96.12 0 .38.03.55.17.14.12.18.28.2.4.02.11.02.24 0 .38z"/>
                </svg>
                Перейти в Telegram бота
            </a>

            <div class="auth-divider">затем введите код</div>

            <input type="text" id="auth-code-input" class="code-input-field" placeholder="000000" maxlength="10" autocomplete="off" />
            <button class="btn-auth-submit" onclick="submitAuthCode()">Войти в систему</button>
            <div id="auth-error">Неверный код доступа. Попробуйте еще раз.</div>
        </div>
    </div>

    <div id="sidebar-overlay" onclick="toggleSidebar()"></div>

    <div id="sidebar">
        <div class="brand">
            <svg class="brand-logo-svg" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
                <defs>
                    <linearGradient id="rubyGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                        <stop offset="0%" stop-color="#ff4b4b" />
                        <stop offset="100%" stop-color="#900c3f" />
                    </linearGradient>
                </defs>
                <path d="M50 10 L85 35 L50 90 L15 35 Z" stroke="url(#rubyGrad)" stroke-width="4" fill="none" />
                <path d="M15 35 L85 35 M50 10 L32 35 M50 10 L68 35 M50 90 L32 35 M50 90 L68 35" stroke="url(#rubyGrad)" stroke-width="2.5" opacity="0.7" />
                <circle cx="50" cy="48" r="14" fill="#ff4b4b" opacity="0.25" />
                <path d="M42 45 Q46 40 50 45 Q54 40 58 45 Q60 52 50 56 Q40 52 42 45 Z" stroke="#ffffff" stroke-width="2.5" fill="none" />
            </svg>
            <div>
                <h2>Rubinov AI</h2>
                <span>Assistant</span>
            </div>
        </div>

        <button class="btn-new-chat" onclick="createNewChat()">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 5v14M5 12h14"/></svg>
            Новый диалог
        </button>

        <div class="chats-header">
            <span>Чаты (<span id="chat-count">1</span>/5)</span>
        </div>

        <div id="chats-list"></div>

        <div class="sidebar-footer">
            <span class="status-dot"></span>
            <span>Online</span>
        </div>
    </div>

    <div id="main">
        <div id="chat-header">
            <div class="header-left">
                <button class="menu-toggle" onclick="toggleSidebar()" title="Меню">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12h18M3 6h18M3 18h18"/></svg>
                </button>
                <h3 id="current-chat-title">Чаты</h3>
            </div>
        </div>

        <div id="chat-container"></div>

        <div id="input-wrapper">
            <div id="input-container">
                <div id="file-info-bar">
                    <span id="file-name-text">Файл прикреплен</span>
                    <button onclick="removeSelectedFile()">✕</button>
                </div>
                <div class="input-row">
                    <input type="file" id="file-input" accept="image/*" capture="environment" style="display: none;" onchange="handleFileSelect(event)" />
                    
                    <button class="mini-btn" onclick="document.getElementById('file-input').click()" title="Прикрепить фото">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
                    </button>

                    <button class="mini-btn" onclick="triggerImageGenerationPrompt()" title="Сгенерировать картинку">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
                    </button>

                    <textarea id="prompt-input" rows="1" placeholder="Введите сообщение или опишите картинку..." onkeydown="handleKeyPress(event)" oninput="autoResizeInput(this)"></textarea>
                    
                    <button class="btn-action" id="action-btn" onclick="handleActionButton()">Отправить</button>
                </div>
            </div>
        </div>
    </div>

    <script>
        function checkAuth() {
            const isAuthenticated = localStorage.getItem('rubinov_auth_passed');
            if (isAuthenticated === 'true') {
                document.getElementById('auth-modal').style.display = 'none';
            }
        }

        async function submitAuthCode() {
            const input = document.getElementById('auth-code-input');
            const errorDiv = document.getElementById('auth-error');
            const code = input.value.trim();

            if (!code) {
                errorDiv.textContent = "Пожалуйста, введите код.";
                errorDiv.style.display = "block";
                return;
            }

            try {
                const response = await fetch('/api/verify-code', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ code: code })
                });

                const data = await response.json();

                if (response.ok) {
                    localStorage.setItem('rubinov_auth_passed', 'true');
                    document.getElementById('auth-modal').style.display = 'none';
                } else {
                    errorDiv.textContent = data.detail || "Неверный код доступа.";
                    errorDiv.style.display = "block";
                }
            } catch (err) {
                errorDiv.textContent = "Ошибка проверки кода. Попробуйте еще раз.";
                errorDiv.style.display = "block";
            }
        }

        document.getElementById('auth-code-input').addEventListener('keydown', function(e) {
            if (e.key === 'Enter') submitAuthCode();
        });

        let chats = JSON.parse(localStorage.getItem('rubinov_chats_v2') || '[]');
        let currentChatId = localStorage.getItem('rubinov_active_chat_v2') || null;
        let selectedFile = null;
        let activeController = null;
        let isGenerating = false;

        if (chats.length === 0) {
            const initialChat = { id: Date.now().toString(), name: 'Новый чат 1', messages: [] };
            chats.push(initialChat);
            currentChatId = initialChat.id;
            saveState();
        } else if (!currentChatId || !chats.find(c => c.id === currentChatId)) {
            currentChatId = chats[0].id;
        }

        function saveState() {
            localStorage.setItem('rubinov_chats_v2', JSON.stringify(chats));
            localStorage.setItem('rubinov_active_chat_v2', currentChatId);
            renderChats();
        }

        function toggleSidebar() {
            const width = window.innerWidth;
            if (width <= 768) {
                const sidebar = document.getElementById('sidebar');
                const overlay = document.getElementById('sidebar-overlay');
                sidebar.classList.toggle('mobile-open');
                overlay.classList.toggle('active');
            } else {
                document.body.classList.toggle('sidebar-collapsed');
            }
        }

        function renderChats() {
            const list = document.getElementById('chats-list');
            list.innerHTML = '';
            document.getElementById('chat-count').textContent = chats.length;

            chats.forEach(chat => {
                const item = document.createElement('div');
                item.className = `chat-item ${chat.id === currentChatId ? 'active' : ''}`;
                item.onclick = () => switchChat(chat.id);

                item.innerHTML = `
                    <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:160px;">${escapeHtml(chat.name)}</span>
                    ${chats.length > 1 ? `<span class="close-btn" onclick="event.stopPropagation(); deleteChat('${chat.id}')">×</span>` : ''}
                `;
                list.appendChild(item);
            });

            const active = chats.find(c => c.id === currentChatId);
            if (active) {
                document.getElementById('current-chat-title').textContent = active.name;
                renderMessages(active.messages);
            }
        }

        function switchChat(id) {
            if (activeController) activeController.abort();
            currentChatId = id;
            setGeneratingState(false);
            saveState();
            if (window.innerWidth <= 768) toggleSidebar();
        }

        function createNewChat() {
            if (chats.length >= 5) {
                if (window.innerWidth <= 768) toggleSidebar();
                return;
            }
            if (activeController) activeController.abort();
            
            const newChat = {
                id: Date.now().toString(),
                name: `Новый чат ${chats.length + 1}`,
                messages: []
            };
            chats.push(newChat);
            currentChatId = newChat.id;
            setGeneratingState(false);
            saveState();
            if (window.innerWidth <= 768) toggleSidebar();
        }

        function deleteChat(id) {
            chats = chats.filter(c => c.id !== id);
            if (currentChatId === id) {
                currentChatId = chats[0].id;
            }
            saveState();
        }

        function triggerImageGenerationPrompt() {
            const input = document.getElementById('prompt-input');
            input.value = "Нарисуй: ";
            autoResizeInput(input);
            input.focus();
        }

        function renderMessages(messages) {
            const chatContainer = document.getElementById('chat-container');
            chatContainer.innerHTML = '';

            if (messages.length === 0) {
                const welcome = document.createElement('div');
                welcome.className = 'welcome-screen';
                welcome.innerHTML = `
                    <div class="welcome-avatar-glow">
                        <svg class="welcome-avatar-svg" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <path d="M50 10 L85 35 L50 90 L15 35 Z" stroke="url(#rubyGrad)" stroke-width="4" fill="none" />
                            <path d="M15 35 L85 35 M50 10 L32 35 M50 10 L68 35 M50 90 L32 35 M50 90 L68 35" stroke="url(#rubyGrad)" stroke-width="2.5" opacity="0.7" />
                            <circle cx="50" cy="48" r="14" fill="#ff4b4b" opacity="0.25" />
                            <path d="M42 45 Q46 40 50 45 Q54 40 58 45 Q60 52 50 56 Q40 52 42 45 Z" stroke="#ffffff" stroke-width="2.5" fill="none" />
                        </svg>
                    </div>
                    <h1>Rubinov AI</h1>
                    <p>Чем я могу помочь вам сегодня?</p>
                `;
                chatContainer.appendChild(welcome);
                return;
            }

            messages.forEach(msg => {
                const row = document.createElement('div');
                row.className = `msg-row ${msg.role === 'user' ? 'user-row' : 'bot-row'}`;
                
                if (msg.role === 'user') {
                    const box = document.createElement('div');
                    box.className = 'msg-user';
                    let content = '';
                    if (msg.file) content += `<div class="file-preview-tag">📷 ${escapeHtml(msg.file)}</div><br>`;
                    content += escapeHtml(msg.text);
                    box.innerHTML = content;
                    row.appendChild(box);
                } else if (msg.role === 'cancelled') {
                    const container = document.createElement('div');
                    container.className = 'cancelled-container';
                    
                    const box = document.createElement('div');
                    box.className = 'msg-user';
                    let content = '';
                    if (msg.file) content += `<div class="file-preview-tag">📷 ${escapeHtml(msg.file)}</div><br>`;
                    content += escapeHtml(msg.text);
                    box.innerHTML = content;
                    
                    container.appendChild(box);
                    container.appendChild(Object.assign(document.createElement('div'), { className: 'cancelled-line' }));
                    container.appendChild(Object.assign(document.createElement('div'), { className: 'cancelled-text', textContent: 'сообщение отменено' }));

                    row.appendChild(container);
                } else {
                    const box = document.createElement('div');
                    box.className = 'msg-bot';
                    if (msg.text.includes('<img')) {
                        box.innerHTML = msg.text;
                    } else {
                        box.innerHTML = marked.parse(msg.text);
                    }
                    row.appendChild(box);
                }

                chatContainer.appendChild(row);
            });
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }

        function handleFileSelect(event) {
            const file = event.target.files[0];
            if (file) {
                selectedFile = file;
                document.getElementById('file-name-text').textContent = `📷 ${file.name}`;
                document.getElementById('file-info-bar').style.display = 'flex';
            }
        }

        function removeSelectedFile() {
            selectedFile = null;
            document.getElementById('file-input').value = '';
            document.getElementById('file-info-bar').style.display = 'none';
        }

        function handleKeyPress(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleActionButton();
            }
        }

        function autoResizeInput(el) {
            el.style.height = 'auto';
            el.style.height = Math.min(el.scrollHeight, 180) + 'px';
        }

        function setGeneratingState(generating) {
            isGenerating = generating;
            const actionBtn = document.getElementById('action-btn');
            const promptInput = document.getElementById('prompt-input');

            if (generating) {
                actionBtn.textContent = 'Отменить';
                actionBtn.className = 'btn-action cancel-mode';
                promptInput.disabled = true;
            } else {
                actionBtn.textContent = 'Отправить';
                actionBtn.className = 'btn-action';
                promptInput.disabled = false;
                promptInput.focus();
            }
        }

        function handleActionButton() {
            if (isGenerating) {
                cancelCurrentRequest();
            } else {
                sendMessage();
            }
        }

        function cancelCurrentRequest() {
            if (activeController) {
                activeController.abort();
                activeController = null;
            }

            const activeChat = chats.find(c => c.id === currentChatId);
            if (activeChat && activeChat.messages.length > 0) {
                const lastMsg = activeChat.messages[activeChat.messages.length - 1];
                if (lastMsg.role === 'user') {
                    lastMsg.role = 'cancelled';
                }
            }

            document.getElementById('temp-loader-row')?.remove();
            setGeneratingState(false);
            saveState();
        }

        async function sendMessage() {
            const input = document.getElementById('prompt-input');
            const text = input.value.trim();
            
            if (!text && !selectedFile) return;

            const activeChat = chats.find(c => c.id === currentChatId);
            if (!activeChat) return;

            const userMsg = {
                role: 'user',
                text: text,
                file: selectedFile ? selectedFile.name : null
            };

            activeChat.messages.push(userMsg);
            if (activeChat.messages.length === 1 && text) {
                activeChat.name = text.slice(0, 18) + (text.length > 18 ? '...' : '');
            }
            
            renderMessages(activeChat.messages);

            const formData = new FormData();
            formData.append('prompt', text);
            if (selectedFile) {
                formData.append('file', selectedFile);
            }

            input.value = '';
            input.style.height = 'auto';
            removeSelectedFile();
            setGeneratingState(true);

            const chatContainer = document.getElementById('chat-container');
            const botRow = document.createElement('div');
            botRow.className = 'msg-row bot-row';
            botRow.id = 'temp-loader-row';
            botRow.innerHTML = `
                <div class="loader-box">
                    <div class="spinner"></div>
                    <span>Думаю...</span>
                </div>
            `;
            chatContainer.appendChild(botRow);
            chatContainer.scrollTop = chatContainer.scrollHeight;

            activeController = new AbortController();

            try {
                const res = await fetch('/api/chat', {
                    method: 'POST',
                    body: formData,
                    signal: activeController.signal
                });
                const data = await res.json();

                document.getElementById('temp-loader-row')?.remove();
                setGeneratingState(false);
                activeController = null;

                if (res.ok) {
                    activeChat.messages.push({ role: 'bot', text: data.response });
                } else {
                    activeChat.messages.push({ role: 'bot', text: 'Ошибка: ' + (data.detail || 'Не удалось получить ответ.') });
                }
            } catch (e) {
                if (e.name === 'AbortError') return;
                document.getElementById('temp-loader-row')?.remove();
                setGeneratingState(false);
                activeController = null;
                activeChat.messages.push({ role: 'bot', text: 'Ошибка подключения к серверу.' });
            }

            saveState();
        }

        function escapeHtml(text) {
            return (text || '').replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        }

        checkAuth();
        renderChats();
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def get_chat_ui():
    return HTML_TEMPLATE

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)

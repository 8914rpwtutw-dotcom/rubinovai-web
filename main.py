import os
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from google import genai

app = FastAPI()

# --- ВАШИ СТАТИЧЕСКИЕ ФАЙЛЫ И ШАБЛОНЫ (КАК БЫЛО ИЗНАЧАЛЬНО) ---
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates") if os.path.exists("templates") else None

# Настройки Google OAuth из переменных окружения Render
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "https://rubinovai-web.onrender.com/auth/google/callback")

# Инициализация Gemini API
def get_gemini_client():
    keys = [
        os.getenv("GEMINI_KEY_1"),
        os.getenv("GEMINI_KEY_2"),
        os.getenv("GEMINI_KEY_3"),
        os.getenv("GEMINI_API_KEY")
    ]
    valid_keys = [k for k in keys if k]
    if not valid_keys:
        raise HTTPException(status_code=500, detail="Gemini API keys not found")
    return genai.Client(api_key=valid_keys[0])

# --- ВАШ ОСНОВНОЙ ИНТЕРФЕЙС И МАРШРУТЫ ---
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    # Если у вас используется шаблон index.html через Jinja2
    if templates and os.path.exists("templates/index.html"):
        return templates.TemplateResponse("index.html", {"request": request})
    # Или если файл лежит в корне проекта
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return {"status": "ok", "message": "Интерфейс ожидает подключения шаблона"}

# --- АВТОРИЗАЦИЯ ЧЕРЕЗ GOOGLE (ПРИВЯЗАНА К КНОПКЕ ВХОДА) ---
@app.get("/auth/google")
def login_google():
    """Перенаправляет пользователя на форму входа Google"""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=500, detail="GOOGLE_CLIENT_ID not configured")
    
    google_auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={GOOGLE_CLIENT_ID}&"
        f"redirect_uri={REDIRECT_URI}&"
        f"response_type=code&"
        f"scope=openid%20email%20profile"
    )
    return RedirectResponse(google_auth_url)

@app.get("/auth/google/callback")
async def auth_google_callback(code: str):
    """Обрабатывает ответ от Google и завершает вход"""
    token_url = "https://oauth2.googleapis.com/token"
    payload = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }
    
    async with httpx.AsyncClient() as client:
        token_res = await client.post(token_url, data=payload)
        if token_res.status_code != 200:
            raise HTTPException(status_code=400, detail="Google token exchange failed")
        
        token_data = token_res.json()
        access_token = token_data.get("access_token")
        
        user_res = await client.get(
            "https://www.googleapis.com/oauth2/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        if user_res.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch Google profile")
        
        user_info = user_res.json()
        # Данные пользователя получены (email: user_info.get('email'), имя: user_info.get('name'))

    # Возвращаем пользователя обратно на ваш сайт
    return RedirectResponse(url="/", status_code=303)

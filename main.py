import os
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from google import genai

app = FastAPI()

# Подключение статических файлов (если у вас есть папка static для фронтенда)
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Настройки Google OAuth
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "https://rubinovai-web.onrender.com/auth/google/callback")

# Инициализация Gemini API с ротацией ключей из окружения
def get_gemini_client():
    keys = [
        os.getenv("GEMINI_KEY_1"),
        os.getenv("GEMINI_KEY_2"),
        os.getenv("GEMINI_KEY_3"),
        os.getenv("GEMINI_API_KEY")
    ]
    valid_keys = [k for k in keys if k]
    if not valid_keys:
        raise HTTPException(status_code=500, detail="API keys for Gemini not found")
    return genai.Client(api_key=valid_keys[0])

# Главная страница с вашим неизменным интерфейсом
@app.get("/", response_class=HTMLResponse)
async def read_root():
    # Если у вас фронтенд отдается как index.html, можно вернуть его содержание или шаблон
    index_path = "index.html"
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    return """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <title>Рубинов ИИ</title>
        <style>
            body { font-family: sans-serif; background: #0f172a; color: #f8fafc; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; margin: 0; }
            .card { background: #1e293b; padding: 40px; border-radius: 16px; text-align: center; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }
            .btn { display: inline-block; background: #4285F4; color: white; padding: 12px 24px; border-radius: 8px; text-decoration: none; font-weight: bold; margin-top: 20px; transition: background 0.2s; }
            .btn:hover { background: #357ae8; }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>Рубинов ИИ</h1>
            <p>Добро пожаловать! Войдите через аккаунт Google, чтобы продолжить.</p>
            <a href="/auth/google" class="btn">Войти через Google</a>
        </div>
    </body>
    </html>
    """

# Эндпоинт инициализации входа через Google
@app.get("/auth/google")
def login_google():
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=500, detail="GOOGLE_CLIENT_ID is not configured")
    
    google_auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={GOOGLE_CLIENT_ID}&"
        f"redirect_uri={REDIRECT_URI}&"
        f"response_type=code&"
        f"scope=openid%20email%20profile"
    )
    return RedirectResponse(google_auth_url)

# Callback-эндпоинт для обработки успешного входа от Google
@app.get("/auth/google/callback")
async def auth_google_callback(code: str):
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
            raise HTTPException(status_code=400, detail="Failed to fetch Google user profile")
        
        user_info = user_res.json()
        # Получены данные: user_info.get('email'), user_info.get('name')

    # После успешной авторизации возвращаем пользователя на главную страницу
    return RedirectResponse(url="/", status_code=303)

# Пример API-эндпоинта для работы с Gemini
@app.post("/api/chat")
async def chat_with_gemini(request: Request):
    data = await request.json()
    prompt = data.get("prompt", "")
    
    client = get_gemini_client()
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        return {"response": response.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

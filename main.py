import os
import json
import time
import traceback
import psycopg2
from typing import Optional
from fastapi import FastAPI, HTTPException, File, Form, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from starlette.middleware.sessions import SessionMiddleware
from google import genai
from google.genai import types
import httpx

app = FastAPI()

# Поддержка HTTPS заголовков прокси
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])

# Защищенные сессии с криптографическим ключом
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET_KEY", "rubinov-ai-super-secure-secret-key-2026-xyz"),
    https_only=True,
    same_site="lax"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# --- Настройка базы данных PostgreSQL (Neon) ---
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    if not DATABASE_URL:
        raise HTTPException(status_code=500, detail="DATABASE_URL не настроена в Environment Variables.")
    return psycopg2.connect(DATABASE_URL)

# Единственный СУПЕР-АДМИНИСТРАТОР (главный владелец)
SUPER_ADMIN = "8914rpwtutw@gmail.com".lower()

# Начальный список обычных администраторов
INITIAL_ADMINS = [
    "egrandr123123@gmail.com",
    "gorvov2003@gmail.com"
]

def init_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY,
                status TEXT DEFAULT 'free',
                requests_count INTEGER DEFAULT 0,
                last_reset_date TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id SERIAL PRIMARY KEY,
                user_email TEXT NOT NULL,
                message TEXT DEFAULT '',
                status TEXT DEFAULT 'open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ticket_messages (
                id SERIAL PRIMARY KEY,
                ticket_id INTEGER REFERENCES tickets(id) ON DELETE CASCADE,
                sender TEXT NOT NULL,
                sender_role TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            INSERT INTO users (email, status) 
            VALUES (%s, 'admin') 
            ON CONFLICT (email) DO UPDATE SET status = 'admin'
        """, (SUPER_ADMIN,))
        
        for adm in INITIAL_ADMINS:
            cursor.execute("""
                INSERT INTO users (email, status) 
                VALUES (%s, 'admin') 
                ON CONFLICT (email) DO NOTHING
            """, (adm.lower(),))
        
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Ошибка инициализации БД: {e}")

init_db()

def get_user_status(email: str) -> str:
    if not email:
        return "guest"
    
    clean_email = email.lower()
    if clean_email == SUPER_ADMIN:
        return "admin"
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM users WHERE email = %s", (clean_email,))
    row = cursor.fetchone()
    
    if row:
        cursor.close()
        conn.close()
        return row[0]
    
    cursor.execute("INSERT INTO users (email, status) VALUES (%s, 'free') ON CONFLICT (email) DO NOTHING", (clean_email,))
    conn.commit()
    cursor.close()
    conn.close()
    return "free"

MODELS = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-3.5-flash-lite"]
current_key_idx = 0
current_model_idx = 0

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")

PERSONA_INSTRUCTIONS = {
    "default": "Ты Rubinov AI — передовой, точный и дружелюбный ИИ-ассистент. Отвечай структурированно, ясно и по делу.",
    "coder": "Ты Senior Fullstack & Python архитектор. Пиши чистый, безопасный и оптимизированный код с комментариями и пояснениями.",
    "copywriter": "Ты топовый креативный копирайтер и маркетолог. Создавай цепляющие тексты, посты и сценарии с высокой конверсией.",
    "translator": "Ты профессиональный переводчик-синхронист. Делай точный, естественный перевод с сохранением стиля и нюансов оригинала."
}

def get_redirect_uri(request: Request) -> str:
    env_uri = os.getenv("REDIRECT_URI") or os.getenv("GOOGLE_REDIRECT_URI")
    if env_uri:
        return env_uri
    return str(request.url_for("auth_google_callback"))

def get_api_keys():
    keys = [
        os.getenv("GEMINI_KEY_1"),
        os.getenv("GEMINI_KEY_2"),
        os.getenv("GEMINI_KEY_3"),
        os.getenv("GEMINI_API_KEY")
    ]
    return [k.strip() for k in keys if k and k.strip()]

def get_gemini_client(api_key: str):
    return genai.Client(api_key=api_key)

def get_gemini_response(prompt: str, persona: str = "default", file_bytes: Optional[bytes] = None, mime_type: Optional[str] = None) -> str:
    global current_key_idx, current_model_idx
    
    lowered = prompt.lower()
    if lowered.startswith("нарисуй") or lowered.startswith("draw") or lowered.startswith("сгенерируй"):
        clean_prompt = prompt
        for prefix in ["Нарисуй:", "нарисуй:", "Нарисуй", "нарисуй", "Сгенерируй:", "сгенерируй:", "Сгенерируй", "сгенерируй", "Draw:", "draw:"]:
            if clean_prompt.startswith(prefix):
                clean_prompt = clean_prompt[len(prefix):].strip()
                break
        if not clean_prompt:
            clean_prompt = "beautiful futuristic neon ruby cyberpunk landscape"
        
        import urllib.parse
        encoded_prompt = urllib.parse.quote(clean_prompt)
        img_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true"
        
        return f"""Вот ваше сгенерированное изображение по запросу: *"{clean_prompt}"*

<div style="margin-top:14px;">
    <img src="{img_url}" alt="{clean_prompt}" style="max-width:100%; border-radius:16px; display:block; margin-bottom:12px; box-shadow: 0 12px 40px rgba(244, 63, 94, 0.25); border: 1px solid rgba(255,255,255,0.1);" />
    <a href="{img_url}" target="_blank" download="rubinov_ai.jpg" style="display:inline-flex; align-items: center; gap: 8px; background: linear-gradient(135deg, #f43f5e, #8b5cf6); color:#fff; padding:9px 18px; border-radius:12px; font-size:12px; text-decoration:none; font-weight:600; box-shadow: 0 4px 20px rgba(244, 63, 94, 0.35);">📥 Скачать в высоком разрешении</a>
</div>"""

    api_keys = get_api_keys()
    if not api_keys:
        raise HTTPException(status_code=500, detail="API-ключи Gemini не найдены в переменных окружения.")

    num_keys = len(api_keys)
    num_models = len(MODELS)
    total_attempts = num_keys * num_models * 2

    contents = []
    if file_bytes and mime_type:
        contents.append(types.Part.from_bytes(data=file_bytes, mime_type=mime_type))
    if prompt:
        contents.append(prompt)

    system_instruction = PERSONA_INSTRUCTIONS.get(persona, PERSONA_INSTRUCTIONS["default"])
    last_error = "Неизвестная ошибка"

    for attempt in range(total_attempts):
        active_key = api_keys[current_key_idx % num_keys]
        active_model = MODELS[current_model_idx % num_models]

        try:
            client = get_gemini_client(active_key)
            response = client.models.generate_content(
                model=active_model,
                contents=contents,
                config=types.GenerateContentConfig(system_instruction=system_instruction)
            )
            if response and response.text:
                return response.text
        except Exception as err:
            last_error = str(err)
            current_model_idx += 1
            if current_model_idx >= num_models:
                current_model_idx = 0
                current_key_idx = (current_key_idx + 1) % num_keys
            time.sleep(0.3)
            continue

    raise HTTPException(status_code=500, detail=f"Ошибка генерации ИИ: {last_error}")

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    user_email = request.session.get("user_email")
    status = get_user_status(user_email)

    if not user_email:
        auth_block = """
        <a href="/auth/google" class="btn-google-login">
            <svg width="15" height="15" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"/></svg>
            Войти через Google
        </a>
        """
    else:
        badge_class = f"badge-{status}"
        admin_btn = '<button type="button" class="btn-admin-panel" onclick="toggleAdminModal(true)">👑 Панель админа</button>' if status == 'admin' else ''
        auth_block = f"""
        {admin_btn}
        <div class="user-profile-card">
            <div style="display:flex; justify-content:space-between; align-items:center; width:100%; font-size:12px;">
                <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:145px; color:#f8fafc; font-weight:600;">{user_email}</span>
                <span class="status-badge {badge_class}">{status}</span>
            </div>
            <div style="display:flex; justify-content:space-between; align-items:center; margin-top:6px;">
                <span id="sidebar-limit-info" style="font-size:10.5px; color:#94a3b8;">Загрузка лимита...</span>
                <a href="/auth/logout" style="color:#f43f5e; font-size:11px; text-decoration:none; font-weight:600;">Выйти</a>
            </div>
        </div>
        """

    rendered_html = HTML_TEMPLATE.replace("USER_AUTH_BLOCK", auth_block)
    return HTMLResponse(content=rendered_html)

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/auth/google")
def login_google(request: Request):
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=500, detail="GOOGLE_CLIENT_ID не настроен")
    current_redirect_uri = get_redirect_uri(request)
    google_auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={GOOGLE_CLIENT_ID}&"
        f"redirect_uri={current_redirect_uri}&"
        f"response_type=code&"
        f"scope=openid%20email%20profile"
    )
    return RedirectResponse(google_auth_url)

@app.get("/auth/google/callback")
async def auth_google_callback(request: Request, code: Optional[str] = None, error: Optional[str] = None):
    if error or not code:
        raise HTTPException(status_code=400, detail="Ошибка авторизации Google")

    token_url = "https://oauth2.googleapis.com/token"
    current_redirect_uri = get_redirect_uri(request)
    payload = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": current_redirect_uri,
        "grant_type": "authorization_code",
    }
    
    async with httpx.AsyncClient() as client:
        token_res = await client.post(token_url, data=payload)
        if token_res.status_code != 200:
            raise HTTPException(status_code=400, detail="Ошибка обмена токена с Google")
        
        token_data = token_res.json()
        access_token = token_data.get("access_token")
        
        user_res = await client.get(
            "https://www.googleapis.com/oauth2/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        if user_res.status_code != 200:
            raise HTTPException(status_code=400, detail="Не удалось получить профиль")
        
        user_info = user_res.json()
        user_email = user_info.get("email")

    get_user_status(user_email)
    request.session["user_email"] = user_email

    return RedirectResponse(url=str(request.base_url), status_code=303)

@app.get("/auth/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url=str(request.base_url), status_code=303)

@app.get("/api/status-check")
def status_check(request: Request):
    user_email = request.session.get("user_email")
    status = get_user_status(user_email)
    requests_used = 0
    if user_email and status == "free":
        today = time.strftime("%Y-%m-%d")
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT requests_count, last_reset_date FROM users WHERE email = %s", (user_email.lower(),))
        row = cursor.fetchone()
        if row and row[1] == today:
            requests_used = row[0]
        cursor.close()
        conn.close()
    elif not user_email:
        requests_used = int(request.cookies.get("guest_requests", "0"))
    return {"status": status, "email": user_email, "requests_used": requests_used}

@app.get("/api/admin/users")
def admin_get_users(request: Request):
    user_email = request.session.get("user_email")
    if get_user_status(user_email) != "admin":
        raise HTTPException(status_code=403, detail="Доступ запрещен")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT email, status, requests_count, created_at FROM users ORDER BY created_at DESC")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return {"users": [{"email": r[0], "status": r[1], "requests_count": r[2], "created_at": str(r[3])} for r in rows]}

@app.post("/api/admin/update-status")
async def admin_update_status(request: Request):
    user_email = (request.session.get("user_email") or "").lower()
    if get_user_status(user_email) != "admin":
        raise HTTPException(status_code=403, detail="Доступ запрещен")
    
    body = await request.json()
    target_email = (body.get("email") or "").lower()
    new_status = body.get("status")
    is_super_admin = (user_email == SUPER_ADMIN)
    
    allowed_statuses = ["free", "vip", "banned"]
    if is_super_admin:
        allowed_statuses.append("admin")
        
    if new_status not in allowed_statuses:
        raise HTTPException(status_code=400, detail="Недопустимый статус.")
    if target_email == SUPER_ADMIN:
        raise HTTPException(status_code=400, detail="Нельзя изменить статус Главного администратора!")
    if not is_super_admin and get_user_status(target_email) == "admin":
        raise HTTPException(status_code=403, detail="Обычный админ не может менять статус других админов.")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET status = %s WHERE email = %s", (new_status, target_email))
    conn.commit()
    cursor.close()
    conn.close()
    return {"success": True}

@app.post("/api/tickets/create")
async def create_ticket(request: Request):
    user_email = request.session.get("user_email")
    if not user_email:
        raise HTTPException(status_code=401, detail="Войдите через Google, чтобы обратиться в поддержку.")
    
    body = await request.json()
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Сообщение не может быть пустым.")
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO tickets (user_email, message, status) VALUES (%s, %s, 'open') RETURNING id",
        (user_email.lower(), message)
    )
    ticket_id = cursor.fetchone()[0]
    cursor.execute(
        "INSERT INTO ticket_messages (ticket_id, sender, sender_role, message) VALUES (%s, %s, 'user', %s)",
        (ticket_id, user_email.lower(), message)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return {"success": True, "ticket_id": ticket_id}

@app.post("/api/tickets/send-message")
async def send_ticket_message(request: Request):
    user_email = request.session.get("user_email")
    if not user_email:
        raise HTTPException(status_code=401, detail="Авторизуйтесь для отправки.")
    
    body = await request.json()
    ticket_id = body.get("ticket_id")
    message = (body.get("message") or "").strip()
    if not message or not ticket_id:
        raise HTTPException(status_code=400, detail="Неверные параметры сообщения.")
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM tickets WHERE id = %s AND user_email = %s", (ticket_id, user_email.lower()))
    ticket = cursor.fetchone()
    if not ticket:
        cursor.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Тикет не найден.")
    if ticket[0] == "closed":
        cursor.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Тикет закрыт.")
        
    cursor.execute(
        "INSERT INTO ticket_messages (ticket_id, sender, sender_role, message) VALUES (%s, %s, 'user', %s)",
        (ticket_id, user_email.lower(), message)
    )
    cursor.execute("UPDATE tickets SET status = 'open', updated_at = CURRENT_TIMESTAMP WHERE id = %s", (ticket_id,))
    conn.commit()
    cursor.close()
    conn.close()
    return {"success": True}

@app.get("/api/tickets/messages")
def get_ticket_messages(request: Request, ticket_id: int):
    user_email = request.session.get("user_email")
    if not user_email:
        raise HTTPException(status_code=401, detail="Требуется авторизация.")
    status = get_user_status(user_email)
    conn = get_db_connection()
    cursor = conn.cursor()
    if status != "admin":
        cursor.execute("SELECT user_email FROM tickets WHERE id = %s", (ticket_id,))
        row = cursor.fetchone()
        if not row or row[0] != user_email.lower():
            cursor.close()
            conn.close()
            raise HTTPException(status_code=403, detail="Доступ запрещен.")
    cursor.execute(
        "SELECT id, sender, sender_role, message, created_at FROM ticket_messages WHERE ticket_id = %s ORDER BY id ASC",
        (ticket_id,)
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return {"messages": [{"id": r[0], "sender": r[1], "role": r[2], "text": r[3], "time": str(r[4])} for r in rows]}

@app.get("/api/tickets/my")
def get_my_tickets(request: Request):
    user_email = request.session.get("user_email")
    if not user_email:
        return {"tickets": []}
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, message, status, created_at FROM tickets WHERE user_email = %s ORDER BY updated_at DESC",
        (user_email.lower(),)
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return {"tickets": [{"id": r[0], "message": r[1], "status": r[2], "created_at": str(r[3])} for r in rows]}

@app.get("/api/admin/tickets")
def admin_get_tickets(request: Request):
    user_email = request.session.get("user_email")
    if get_user_status(user_email) != "admin":
        raise HTTPException(status_code=403, detail="Доступ запрещен")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_email, message, status, updated_at FROM tickets ORDER BY updated_at DESC")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return {"tickets": [{"id": r[0], "user_email": r[1], "message": r[2], "status": r[3], "created_at": str(r[4])} for r in rows]}

@app.post("/api/admin/tickets/reply")
async def admin_reply_ticket(request: Request):
    user_email = request.session.get("user_email")
    if get_user_status(user_email) != "admin":
        raise HTTPException(status_code=403, detail="Доступ запрещен")
    body = await request.json()
    ticket_id = body.get("ticket_id")
    reply = (body.get("reply") or "").strip()
    close_ticket = body.get("close", False)
    conn = get_db_connection()
    cursor = conn.cursor()
    if reply:
        cursor.execute(
            "INSERT INTO ticket_messages (ticket_id, sender, sender_role, message) VALUES (%s, %s, 'admin', %s)",
            (ticket_id, user_email.lower(), reply)
        )
    new_status = "closed" if close_ticket else "replied"
    cursor.execute(
        "UPDATE tickets SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
        (new_status, ticket_id)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return {"success": True}

@app.post("/api/chat")
async def chat_endpoint(
    request: Request,
    prompt: str = Form(""),
    persona: str = Form("default"),
    file: Optional[UploadFile] = File(None)
):
    try:
        user_email = request.session.get("user_email")
        status = get_user_status(user_email)

        if status == "banned":
            raise HTTPException(status_code=403, detail="Ваш аккаунт заблокирован администратором.")

        if not user_email:
            guest_count = int(request.cookies.get("guest_requests", "0"))
            if guest_count >= 10:
                raise HTTPException(status_code=403, detail="Лимит гостя исчерпан (10 запросов). Войдите через Google.")
            if file:
                raise HTTPException(status_code=403, detail="Гости не могут отправлять файлы.")
        elif status == "free":
            if file:
                raise HTTPException(status_code=403, detail="Отправка файлов и фото доступна только VIP-пользователям.")

            today = time.strftime("%Y-%m-%d")
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT requests_count, last_reset_date FROM users WHERE email = %s", (user_email.lower(),))
            row = cursor.fetchone()
            req_count, last_date = (row[0], row[1]) if row else (0, "")
            
            if last_date != today:
                req_count = 0
                cursor.execute("UPDATE users SET requests_count = 0, last_reset_date = %s WHERE email = %s", (today, user_email.lower()))
                conn.commit()
                
            if req_count >= 50:
                cursor.close()
                conn.close()
                raise HTTPException(status_code=403, detail="Исчерпан суточный лимит (50 запросов) для Free.")
                
            cursor.execute("UPDATE users SET requests_count = %s WHERE email = %s", (req_count + 1, user_email.lower()))
            conn.commit()
            cursor.close()
            conn.close()

        if not prompt.strip() and not file:
            raise HTTPException(status_code=400, detail="Запрос или файл обязателен")
        
        file_bytes = await file.read() if file else None
        mime_type = file.content_type if file else None

        answer = get_gemini_response(prompt, persona, file_bytes, mime_type)
        json_resp = JSONResponse(content={"response": answer})

        if not user_email:
            guest_count = int(request.cookies.get("guest_requests", "0"))
            json_resp.set_cookie(key="guest_requests", value=str(guest_count + 1), httponly=False)

        return json_resp

    except HTTPException:
        raise
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера: {exc}")

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <title>Rubinov AI — Мультимодальный ИИ-центр</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <style>
        :root {
            --bg-main: #05060a;
            --bg-sidebar: rgba(11, 13, 20, 0.88);
            --card-bg: rgba(19, 23, 34, 0.65);
            --card-hover: rgba(28, 33, 48, 0.85);
            --border-color: rgba(255, 255, 255, 0.08);
            --border-ruby: rgba(244, 63, 94, 0.35);
            --ruby-gradient: linear-gradient(135deg, #f43f5e 0%, #a855f7 100%);
            --ruby-glow: rgba(244, 63, 94, 0.22);
            --violet-glow: rgba(168, 85, 247, 0.18);
            --cancel-bg: rgba(244, 63, 94, 0.12);
            --cancel-border: rgba(244, 63, 94, 0.35);
            --cancel-color: #fb7185;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --user-msg-bg: linear-gradient(135deg, rgba(244, 63, 94, 0.16) 0%, rgba(168, 85, 247, 0.16) 100%);
            --bot-msg-bg: rgba(16, 19, 29, 0.78);
            --scrollbar-thumb: rgba(255, 255, 255, 0.14);
        }

        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', -apple-system, sans-serif; -webkit-tap-highlight-color: transparent; }
        html, body { height: 100%; height: 100dvh; overflow: hidden; background: var(--bg-main); color: var(--text-main); }
        body { display: flex; position: relative; }

        body::before {
            content: ''; position: fixed; top: -18vh; left: 10vw; width: 50vw; height: 50vh;
            background: radial-gradient(circle, rgba(244, 63, 94, 0.09) 0%, rgba(168, 85, 247, 0.03) 55%, transparent 80%);
            z-index: 0; pointer-events: none; filter: blur(90px);
        }
        body::after {
            content: ''; position: fixed; bottom: -18vh; right: -10vw; width: 55vw; height: 55vh;
            background: radial-gradient(circle, rgba(168, 85, 247, 0.09) 0%, rgba(99, 102, 241, 0.02) 60%, transparent 80%);
            z-index: 0; pointer-events: none; filter: blur(90px);
        }

        ::-webkit-scrollbar { width: 5px; height: 5px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: var(--scrollbar-thumb); border-radius: 20px; }

        #sidebar-overlay {
            display: none; position: fixed; top: 0; left: 0; width: 100vw; height: 100dvh;
            background: rgba(4, 5, 8, 0.72); backdrop-filter: blur(6px); z-index: 40; opacity: 0; transition: opacity 0.3s ease;
        }
        #sidebar-overlay.active { display: block; opacity: 1; }

        #sidebar { 
            width: 285px; min-width: 285px; background: var(--bg-sidebar); backdrop-filter: blur(28px);
            -webkit-backdrop-filter: blur(28px); border-right: 1px solid var(--border-color); 
            display: flex; flex-direction: column; padding: 20px 14px; z-index: 50; height: 100dvh;
            transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1), margin-left 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            box-shadow: 15px 0 45px rgba(0, 0, 0, 0.45);
        }
        body.sidebar-collapsed #sidebar { margin-left: -285px; }

        .brand { display: flex; align-items: center; gap: 12px; margin-bottom: 20px; padding: 0 4px; }
        .brand-logo-svg { width: 34px; height: 34px; filter: drop-shadow(0 0 14px rgba(244, 63, 94, 0.6)); flex-shrink: 0; }
        .brand h2 { font-size: 16px; font-weight: 800; background: linear-gradient(90deg, #fff, #fda4af); -webkit-background-clip: text; -webkit-text-fill-color: transparent; letter-spacing: -0.3px; }
        .brand span { font-size: 10px; color: var(--text-muted); font-weight: 600; display: block; text-transform: uppercase; letter-spacing: 0.8px; }

        .btn-new-chat { 
            background: var(--ruby-gradient); color: #ffffff; border: none; padding: 11px 16px; 
            border-radius: 14px; font-size: 12.5px; font-weight: 700; cursor: pointer; 
            display: flex; align-items: center; justify-content: center; gap: 8px; margin-bottom: 10px; 
            transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1); box-shadow: 0 4px 22px rgba(244, 63, 94, 0.32);
        }
        .btn-new-chat:hover { transform: translateY(-1px); box-shadow: 0 6px 28px rgba(244, 63, 94, 0.48); }

        .sidebar-quick-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 16px; }
        .btn-side-action {
            background: rgba(255, 255, 255, 0.03); border: 1px solid var(--border-color); color: #e2e8f0;
            padding: 8px 10px; border-radius: 11px; font-size: 11px; font-weight: 600; cursor: pointer;
            display: flex; align-items: center; justify-content: center; gap: 6px; transition: all 0.2s;
        }
        .btn-side-action:hover { background: rgba(244, 63, 94, 0.14); border-color: rgba(244, 63, 94, 0.35); color: #fff; }
        .btn-side-vip { border-color: rgba(168, 85, 247, 0.35); background: rgba(168, 85, 247, 0.08); color: #e9d5ff; }
        .btn-side-vip:hover { background: rgba(168, 85, 247, 0.2); border-color: rgba(168, 85, 247, 0.55); }

        .chats-header { display: flex; justify-content: space-between; font-size: 10px; color: var(--text-muted); font-weight: 700; margin-bottom: 8px; padding: 0 4px; text-transform: uppercase; letter-spacing: 0.8px; }
        
        #chats-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; padding-right: 2px; }
        .chat-item { 
            background: rgba(255, 255, 255, 0.015); border: 1px solid var(--border-color); 
            border-radius: 12px; padding: 10px 12px; font-size: 12px; color: #cbd5e1; 
            display: flex; justify-content: space-between; align-items: center; cursor: pointer; transition: all 0.2s ease;
        }
        .chat-item.active { 
            background: linear-gradient(90deg, rgba(244, 63, 94, 0.12), rgba(168, 85, 247, 0.08)); 
            border-color: rgba(244, 63, 94, 0.38); color: #ffffff;
        }
        .chat-item:hover { background: rgba(255, 255, 255, 0.045); border-color: rgba(244, 63, 94, 0.28); color: #ffffff; }
        .chat-item .close-btn { color: var(--text-muted); font-size: 14px; cursor: pointer; border-radius: 6px; width: 22px; height: 22px; display: flex; align-items: center; justify-content: center; }
        .chat-item .close-btn:hover { color: #fb7185; background: rgba(244, 63, 94, 0.18); }

        .sidebar-footer { font-size: 11px; color: var(--text-muted); display: flex; flex-direction: column; gap: 8px; margin-top: auto; padding-top: 12px; border-top: 1px solid var(--border-color); }
        .user-profile-card { background: rgba(255,255,255,0.03); border: 1px solid var(--border-color); border-radius: 12px; padding: 9px 11px; }
        .footer-info { display: flex; align-items: center; justify-content: space-between; width: 100%; padding: 0 2px; }
        .status-dot { width: 7px; height: 7px; background: #10b981; border-radius: 50%; box-shadow: 0 0 10px rgba(16, 185, 129, 0.8); }

        .btn-google-login {
            background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.12);
            color: #ffffff; padding: 9px 12px; border-radius: 11px; font-size: 12px; font-weight: 600;
            text-decoration: none; display: flex; align-items: center; justify-content: center; gap: 8px; transition: all 0.2s ease;
        }
        .btn-google-login:hover { background: rgba(255, 255, 255, 0.1); border-color: rgba(244, 63, 94, 0.45); }

        .btn-admin-panel {
            background: linear-gradient(135deg, rgba(234, 179, 8, 0.18), rgba(244, 63, 94, 0.18)); 
            border: 1px solid rgba(234, 179, 8, 0.45);
            color: #fde047; padding: 8px 12px; border-radius: 11px; font-size: 11.5px; font-weight: 700;
            cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 6px; transition: all 0.2s ease;
            width: 100%;
        }
        .btn-admin-panel:hover { background: rgba(234, 179, 8, 0.28); color: #fff; }

        .status-badge { padding: 2px 7px; border-radius: 6px; font-size: 9.5px; font-weight: 800; text-transform: uppercase; display: inline-block; }
        .badge-vip { background: rgba(168, 85, 247, 0.25); color: #e9d5ff; border: 1px solid rgba(168,85,247,0.45); }
        .badge-free { background: rgba(148, 163, 184, 0.15); color: #cbd5e1; border: 1px solid rgba(148, 163, 184, 0.25); }
        .badge-admin { background: rgba(234, 179, 8, 0.25); color: #fde047; border: 1px solid rgba(234,179,8,0.45); }
        .badge-banned { background: rgba(244, 63, 94, 0.25); color: #fda4af; }
        .badge-open { background: rgba(59, 130, 246, 0.2); color: #93c5fd; border: 1px solid rgba(59, 130, 246, 0.4); }
        .badge-replied { background: rgba(168, 85, 247, 0.2); color: #d8b4fe; border: 1px solid rgba(168, 85, 247, 0.4); }
        .badge-closed { background: rgba(100, 116, 139, 0.2); color: #cbd5e1; }

        #banned-overlay, #admin-modal, #user-support-modal, #vip-modal {
            display: none; position: fixed; top: 0; left: 0; width: 100vw; height: 100dvh;
            background: rgba(4, 5, 8, 0.85); backdrop-filter: blur(10px); z-index: 100;
            align-items: center; justify-content: center; padding: 14px;
        }
        #banned-overlay { z-index: 999; }
        #banned-overlay.active, #admin-modal.active, #user-support-modal.active, #vip-modal.active { display: flex; }

        .banned-box {
            background: #11141d; border: 1px solid rgba(244, 63, 94, 0.4);
            padding: 30px 24px; border-radius: 24px; max-width: 400px; width: 100%; text-align: center;
        }
        .admin-box {
            background: #0d1018; border: 1px solid rgba(244, 63, 94, 0.3); border-radius: 22px;
            width: 100%; max-width: 820px; height: 85dvh; display: flex; flex-direction: column; overflow: hidden;
            box-shadow: 0 24px 60px rgba(0,0,0,0.85);
        }
        .vip-modal-box {
            background: linear-gradient(180deg, #131624 0%, #0b0d14 100%);
            border: 1px solid rgba(168, 85, 247, 0.4); border-radius: 24px;
            width: 100%; max-width: 680px; padding: 24px; box-shadow: 0 24px 60px rgba(168, 85, 247, 0.2);
        }
        .admin-header {
            padding: 15px 20px; border-bottom: 1px solid var(--border-color);
            display: flex; justify-content: space-between; align-items: center; background: rgba(18, 21, 31, 0.85);
        }
        .admin-header h3 { font-size: 14.5px; color: #fff; font-weight: 700; }
        .admin-close { background: none; border: none; color: var(--text-muted); font-size: 22px; cursor: pointer; line-height: 1; }
        .admin-close:hover { color: #fb7185; }
        
        .admin-nav-tabs, .admin-filters {
            display: flex; gap: 8px; padding: 10px 16px; background: rgba(13, 16, 24, 0.95);
            border-bottom: 1px solid var(--border-color); flex-wrap: wrap;
        }
        .tab-btn, .filter-btn {
            background: rgba(255, 255, 255, 0.03); border: 1px solid var(--border-color); color: var(--text-muted);
            padding: 6px 13px; border-radius: 9px; font-size: 11.5px; font-weight: 600; cursor: pointer; transition: all 0.2s;
        }
        .tab-btn.active { background: var(--ruby-gradient); color: #fff; border-color: transparent; }
        .filter-btn.active { background: rgba(244, 63, 94, 0.18); border-color: rgba(244, 63, 94, 0.4); color: #fff; }

        .admin-content { padding: 16px; overflow-y: auto; flex: 1; }
        .admin-table { width: 100%; border-collapse: collapse; font-size: 12px; }
        .admin-table th, .admin-table td { padding: 10px; text-align: left; border-bottom: 1px solid var(--border-color); color: #f1f5f9; }
        .admin-table th { color: var(--text-muted); font-weight: 600; background: rgba(255,255,255,0.02); }
        .admin-actions-cell select {
            background: #1a1f2c; border: 1px solid rgba(244, 63, 94, 0.35); color: #ffffff;
            padding: 5px 8px; border-radius: 7px; font-size: 11.5px; outline: none; cursor: pointer;
        }

        .ticket-card {
            background: rgba(255, 255, 255, 0.025); border: 1px solid var(--border-color);
            border-radius: 13px; padding: 12px 14px; margin-bottom: 10px; display: flex; flex-direction: column; gap: 8px; cursor: pointer; transition: all 0.2s;
        }
        .ticket-card:hover { border-color: rgba(244, 63, 94, 0.35); background: rgba(255,255,255,0.04); }
        .ticket-header { display: flex; justify-content: space-between; align-items: center; font-size: 11px; color: var(--text-muted); }
        .ticket-msg { font-size: 12.5px; color: #f1f5f9; line-height: 1.4; background: rgba(0,0,0,0.25); padding: 8px 10px; border-radius: 8px; }
        .ticket-chat-container { display: flex; flex-direction: column; height: 100%; gap: 10px; }
        .ticket-chat-messages {
            flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; padding: 12px;
            background: rgba(0,0,0,0.25); border-radius: 12px; border: 1px solid var(--border-color);
        }
        .t-msg-bubble { max-width: 80%; padding: 9px 13px; border-radius: 12px; font-size: 12.5px; line-height: 1.4; word-break: break-word; }
        .t-msg-user { align-self: flex-end; background: rgba(244, 63, 94, 0.2); border: 1px solid rgba(244, 63, 94, 0.35); color: #fff; }
        .t-msg-admin { align-self: flex-start; background: rgba(168, 85, 247, 0.2); border: 1px solid rgba(168, 85, 247, 0.35); color: #fff; }
        .t-msg-meta { font-size: 9.5px; opacity: 0.65; margin-bottom: 3px; display: block; }
        .ticket-chat-input-row { display: flex; gap: 8px; align-items: center; }
        .ticket-chat-input-row input {
            flex: 1; background: rgba(0,0,0,0.45); border: 1px solid var(--border-color); color: #fff;
            padding: 10px 13px; border-radius: 10px; font-size: 12.5px; outline: none;
        }
        .btn-ticket-action {
            background: rgba(255, 255, 255, 0.06); border: 1px solid var(--border-color); color: #fff;
            padding: 6px 12px; border-radius: 8px; font-size: 11px; cursor: pointer;
        }
        .btn-close-ticket { background: rgba(244, 63, 94, 0.16); border-color: rgba(244, 63, 94, 0.35); color: #fda4af; }

        .plans-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 16px; }
        .plan-card {
            background: rgba(255,255,255,0.03); border: 1px solid var(--border-color);
            border-radius: 18px; padding: 18px; display: flex; flex-direction: column; gap: 10px;
        }
        .plan-card.vip-featured {
            background: linear-gradient(145deg, rgba(244, 63, 94, 0.12), rgba(168, 85, 247, 0.14));
            border-color: rgba(244, 63, 94, 0.45); position: relative;
        }
        .plan-card h4 { font-size: 16px; font-weight: 800; color: #fff; }
        .plan-card ul { list-style: none; display: flex; flex-direction: column; gap: 7px; font-size: 12px; color: #cbd5e1; margin: 6px 0; }

        #main { flex: 1; display: flex; flex-direction: column; background: transparent; position: relative; height: 100dvh; overflow: hidden; z-index: 1; }
        
        #chat-header { 
            height: 60px; min-height: 60px; border-bottom: 1px solid var(--border-color); 
            display: flex; align-items: center; justify-content: space-between; 
            padding: 0 22px; background: rgba(5, 6, 10, 0.65); backdrop-filter: blur(18px); z-index: 10;
        }
        .header-left { display: flex; align-items: center; gap: 12px; }
        .header-right { display: flex; align-items: center; gap: 10px; }
        .menu-toggle { 
            background: rgba(255, 255, 255, 0.03); border: 1px solid var(--border-color); 
            color: #ffffff; border-radius: 11px; padding: 8px; cursor: pointer; display: flex; align-items: center; justify-content: center;
        }
        .menu-toggle:hover { border-color: rgba(244, 63, 94, 0.4); }
        #chat-header h3 { font-size: 14px; font-weight: 700; color: #ffffff; }
        .model-pill {
            background: rgba(244, 63, 94, 0.1); border: 1px solid rgba(244, 63, 94, 0.28);
            color: #fda4af; padding: 5px 11px; border-radius: 20px; font-size: 11px; font-weight: 700;
            display: flex; align-items: center; gap: 6px;
        }

        #chat-container { 
            flex: 1; overflow-y: auto; padding: 24px 24px 175px 24px; 
            display: flex; flex-direction: column; gap: 18px; max-width: 980px; width: 100%; margin: 0 auto; position: relative; z-index: 2;
        }

        .welcome-dashboard {
            display: flex; flex-direction: column; gap: 20px; width: 100%; margin: auto 0; padding: 10px 0;
            animation: fadeIn 0.4s ease;
        }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }

        .hero-banner {
            background: linear-gradient(135deg, rgba(244, 63, 94, 0.14) 0%, rgba(168, 85, 247, 0.12) 50%, rgba(15, 18, 28, 0.85) 100%);
            border: 1px solid rgba(244, 63, 94, 0.28); border-radius: 24px; padding: 26px 28px;
            display: flex; align-items: center; justify-content: space-between; gap: 20px;
            box-shadow: 0 20px 50px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(255,255,255,0.08);
            position: relative; overflow: hidden;
        }
        .hero-text { max-width: 600px; z-index: 2; }
        .hero-badge {
            display: inline-flex; align-items: center; gap: 6px; background: rgba(244, 63, 94, 0.18);
            border: 1px solid rgba(244, 63, 94, 0.35); color: #fda4af; font-size: 11px; font-weight: 700;
            padding: 4px 10px; border-radius: 20px; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 0.5px;
        }
        .hero-banner h1 { font-size: 26px; font-weight: 800; color: #ffffff; line-height: 1.2; margin-bottom: 8px; }
        .hero-banner p { font-size: 13.5px; color: #cbd5e1; line-height: 1.5; }
        .hero-ruby-art {
            width: 86px; height: 86px; flex-shrink: 0; filter: drop-shadow(0 0 24px rgba(244, 63, 94, 0.65));
        }

        .bento-grid {
            display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; width: 100%;
        }
        .bento-card {
            background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 18px;
            padding: 18px 20px; cursor: pointer; transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
            display: flex; flex-direction: column; gap: 8px; text-align: left; position: relative;
        }
        .bento-card:hover {
            background: var(--card-hover); border-color: rgba(244, 63, 94, 0.45);
            transform: translateY(-2px); box-shadow: 0 12px 30px rgba(244, 63, 94, 0.12);
        }
        .bento-card-top { display: flex; align-items: center; justify-content: space-between; }
        .bento-icon {
            width: 36px; height: 36px; border-radius: 11px; display: flex; align-items: center; justify-content: center;
            font-size: 18px; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08);
        }
        .bento-tag { font-size: 10px; font-weight: 700; color: #a855f7; background: rgba(168,85,247,0.14); padding: 3px 8px; border-radius: 6px; }
        .bento-card h4 { font-size: 14.5px; font-weight: 700; color: #ffffff; }
        .bento-card p { font-size: 12px; color: var(--text-muted); line-height: 1.45; }

        .quick-prompts-row { display: flex; gap: 8px; flex-wrap: wrap; }
        .quick-chip {
            background: rgba(255,255,255,0.03); border: 1px solid var(--border-color); color: #cbd5e1;
            padding: 7px 13px; border-radius: 20px; font-size: 11.5px; cursor: pointer; transition: all 0.2s;
        }
        .quick-chip:hover { background: rgba(244, 63, 94, 0.14); border-color: rgba(244, 63, 94, 0.35); color: #fff; }

        .msg-row { display: flex; flex-direction: column; width: 100%; z-index: 2; }
        .msg-row.user-row { align-items: flex-end; }
        .msg-row.bot-row { align-items: flex-start; }

        .msg-user { 
            background: var(--user-msg-bg); color: #ffffff; border: 1px solid rgba(244, 63, 94, 0.28); 
            border-radius: 18px 18px 4px 18px; padding: 12px 16px; font-size: 13.5px; line-height: 1.55; max-width: 82%; word-break: break-word; 
        }
        .msg-bot { 
            background: var(--bot-msg-bg); border: 1px solid var(--border-color); color: #e2e8f0; 
            border-radius: 18px 18px 18px 4px; padding: 18px 22px; font-size: 13.5px; line-height: 1.65; max-width: 92%; word-break: break-word;
            box-shadow: 0 8px 30px rgba(0,0,0,0.25);
        }
        .msg-bot p { margin-bottom: 10px; }
        .msg-bot p:last-child { margin-bottom: 0; }
        .msg-bot ul, .msg-bot ol { margin: 8px 0 10px 20px; }
        .msg-bot code { background: rgba(255, 255, 255, 0.07); padding: 2px 6px; border-radius: 6px; font-family: 'JetBrains Mono', monospace; font-size: 12px; color: #fda4af; }
        .msg-bot pre { background: #030407; padding: 14px; border-radius: 12px; overflow-x: auto; margin: 12px 0; border: 1px solid rgba(255,255,255,0.09); position: relative; }
        .msg-bot pre code { background: transparent; padding: 0; color: #e2e8f0; }

        .copy-code-btn {
            position: absolute; top: 8px; right: 8px; background: rgba(255,255,255,0.08);
            border: 1px solid rgba(255,255,255,0.12); color: #cbd5e1; font-size: 10.5px; font-weight: 600;
            padding: 4px 9px; border-radius: 7px; cursor: pointer; transition: all 0.2s;
        }
        .copy-code-btn:hover { background: rgba(244, 63, 94, 0.25); color: #fff; border-color: rgba(244, 63, 94, 0.4); }

        .file-preview-tag { display: inline-flex; align-items: center; gap: 6px; background: rgba(244, 63, 94, 0.16); padding: 4px 9px; border-radius: 8px; font-size: 11px; margin-bottom: 6px; color: #fda4af; }

        .loader-box {
            display: flex; align-items: center; gap: 12px; background: var(--bot-msg-bg);
            border: 1px solid var(--border-color); border-radius: 18px 18px 18px 4px; padding: 13px 18px; font-size: 13px; color: var(--text-muted);
        }
        .spinner {
            width: 15px; height: 15px; border: 2px solid rgba(244, 63, 94, 0.22);
            border-top-color: #f43f5e; border-radius: 50%; animation: spin 0.8s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }

        #input-wrapper {
            position: absolute; bottom: 0; left: 0; right: 0; 
            padding: 12px 24px 16px 24px; padding-bottom: calc(16px + env(safe-area-inset-bottom));
            background: linear-gradient(180deg, rgba(5, 6, 10, 0) 0%, rgba(5, 6, 10, 0.9) 35%, var(--bg-main) 100%);
            z-index: 20;
        }
        .input-area-max { max-width: 980px; margin: 0 auto; display: flex; flex-direction: column; gap: 8px; }

        .persona-bar { display: flex; align-items: center; gap: 6px; overflow-x: auto; padding-bottom: 2px; }
        .persona-pill {
            background: rgba(19, 23, 34, 0.8); border: 1px solid var(--border-color); color: var(--text-muted);
            padding: 5px 12px; border-radius: 20px; font-size: 11.5px; font-weight: 600; cursor: pointer;
            white-space: nowrap; transition: all 0.2s; display: flex; align-items: center; gap: 5px;
        }
        .persona-pill:hover { border-color: rgba(244, 63, 94, 0.35); color: #fff; }
        .persona-pill.active {
            background: linear-gradient(135deg, rgba(244, 63, 94, 0.22), rgba(168, 85, 247, 0.22));
            border-color: rgba(244, 63, 94, 0.55); color: #ffffff; box-shadow: 0 2px 12px rgba(244, 63, 94, 0.2);
        }

        #input-container { 
            background: rgba(15, 18, 28, 0.9); backdrop-filter: blur(26px); 
            border: 1px solid rgba(244, 63, 94, 0.25); border-radius: 18px; 
            padding: 7px 10px; display: flex; flex-direction: column; gap: 6px; box-shadow: 0 12px 35px rgba(0, 0, 0, 0.65);
        }
        #input-container:focus-within { border-color: rgba(244, 63, 94, 0.55); box-shadow: 0 12px 35px rgba(244, 63, 94, 0.14); }
        #file-info-bar { display: none; align-items: center; justify-content: space-between; background: rgba(244, 63, 94, 0.14); padding: 5px 10px; border-radius: 8px; font-size: 11px; color: #fda4af; }
        #file-info-bar button { background: none; border: none; color: #fb7185; cursor: pointer; font-size: 13px; }

        .input-row { display: flex; gap: 7px; align-items: center; width: 100%; }
        .mini-btn { 
            background: rgba(255, 255, 255, 0.03); border: 1px solid var(--border-color); color: var(--text-muted); 
            padding: 9px; border-radius: 11px; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: all 0.2s;
        }
        .mini-btn:hover { background: rgba(244, 63, 94, 0.14); border-color: rgba(244, 63, 94, 0.35); color: #fff; }
        #prompt-input { flex: 1; background: transparent; border: none; color: #ffffff; font-size: 13.5px; outline: none; min-width: 0; padding: 5px; }
        #prompt-input::placeholder { color: var(--text-muted); }
        
        .btn-action { 
            background: var(--ruby-gradient); color: #ffffff; border: none; border-radius: 11px; 
            padding: 10px 18px; font-size: 12.5px; font-weight: 700; cursor: pointer; flex-shrink: 0; 
            display: flex; align-items: center; justify-content: center; min-width: 96px; transition: all 0.2s;
        }
        .btn-action:hover { box-shadow: 0 4px 18px rgba(244, 63, 94, 0.4); }
        .btn-action.cancel-mode { background: var(--cancel-bg); border: 1px solid var(--cancel-border); color: var(--cancel-color); }

        @media (max-width: 768px) {
            #sidebar { position: fixed; top: 0; left: 0; margin-left: 0 !important; transform: translateX(-100%); }
            #sidebar.mobile-open { transform: translateX(0); }
            #chat-header { padding: 0 14px; }
            #chat-container { padding: 14px 14px 165px 14px; }
            #input-wrapper { padding: 10px 14px; }
            .bento-grid, .plans-grid { grid-template-columns: 1fr; }
            .hero-ruby-art { display: none; }
            .hero-banner { padding: 18px; }
            .hero-banner h1 { font-size: 20px; }
        }
    </style>
</head>
<body>
    <div id="sidebar-overlay" onclick="toggleSidebar()"></div>

    <div id="banned-overlay">
        <div class="banned-box">
            <h2 style="color:#fb7185; margin-bottom:10px;">🚫 Аккаунт заблокирован</h2>
            <p style="color:#94a3b8; font-size:13px; margin-bottom:18px;">Ваш аккаунт был заблокирован администратором. Доступ к нейросети приостановлен.</p>
            <a href="/auth/logout" style="background: rgba(244,63,94,0.2); border: 1px solid rgba(244,63,94,0.4); color: #fda4af; padding: 9px 18px; border-radius: 10px; font-size: 12px; text-decoration: none; font-weight: 700; display: inline-block;">Выйти из аккаунта</a>
        </div>
    </div>

    <div id="vip-modal" onclick="if(event.target.id==='vip-modal') toggleVipModal(false)">
        <div class="vip-modal-box" onclick="event.stopPropagation()">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <h3 style="font-size:18px; font-weight:800; color:#fff;">💎 Тарифы и возможности Rubinov AI</h3>
                <button type="button" class="admin-close" onclick="toggleVipModal(false)">×</button>
            </div>
            <p style="font-size:12.5px; color:#94a3b8; margin-top:4px;">Выберите подходящий уровень доступа к мультимодальным нейросетям.</p>
            
            <div class="plans-grid">
                <div class="plan-card">
                    <span class="status-badge badge-free" style="width:fit-content;">Базовый</span>
                    <h4>Free — Бесплатно</h4>
                    <ul>
                        <li>✅ До 50 запросов в сутки</li>
                        <li>✅ Доступ к Gemini 2.5 Flash</li>
                        <li>✅ Генерация картинок по тексту</li>
                        <li>✅ Все 4 роли ИИ-ассистента</li>
                        <li style="color:#64748b;">❌ Загрузка и анализ фото</li>
                    </ul>
                </div>
                <div class="plan-card vip-featured">
                    <span class="status-badge badge-vip" style="width:fit-content;">Рекомендуем</span>
                    <h4>VIP-Доступ</h4>
                    <ul>
                        <li>♾ <b>Безлимитные</b> запросы 24/7</li>
                        <li>👁 <b>Анализ фото и скриншотов</b> (решение задач, OCR, разбор кода по фото)</li>
                        <li>⚡ Максимальный приоритет генерации</li>
                        <li>🎨 Генерация изображений без ограничений</li>
                    </ul>
                    <button type="button" class="btn-action" style="margin-top:auto; width:100%;" onclick="toggleVipModal(false); toggleUserSupportModal(true);">Запросить VIP через поддержку</button>
                </div>
            </div>
        </div>
    </div>

    <div id="user-support-modal" onclick="if(event.target.id==='user-support-modal') toggleUserSupportModal(false)">
        <div class="admin-box" style="max-width:560px;" onclick="event.stopPropagation()">
            <div class="admin-header">
                <h3>💬 Служба поддержки Rubinov AI</h3>
                <button type="button" class="admin-close" onclick="toggleUserSupportModal(false)">×</button>
            </div>
            <div class="admin-content" id="user-support-content">
                <form onsubmit="submitUserTicket(event)" style="margin-bottom: 14px;">
                    <label style="font-size: 12px; color: var(--text-muted); display: block; margin-bottom: 6px;">Опишите ваш вопрос или заявку на VIP:</label>
                    <textarea id="user-ticket-input" style="width: 100%; background: rgba(0,0,0,0.4); border: 1px solid var(--border-color); color: #fff; padding: 10px; border-radius: 10px; font-size: 12.5px; outline: none; resize: vertical; min-height: 75px;" placeholder="Здравствуйте! Хочу подключить VIP-статус / задать вопрос..."></textarea>
                    <button type="submit" class="btn-action" style="margin-top: 8px; width: 100%;">Отправить обращение</button>
                </form>
                <hr style="border: none; border-top: 1px solid var(--border-color); margin: 14px 0;">
                <h4 style="font-size: 12.5px; color: #fff; margin-bottom: 10px;">История ваших тикетов:</h4>
                <div id="user-tickets-list">Загрузка...</div>
            </div>
        </div>
    </div>

    <div id="admin-modal" onclick="if(event.target.id==='admin-modal') toggleAdminModal(false)">
        <div class="admin-box" onclick="event.stopPropagation()">
            <div class="admin-header">
                <h3>👑 Панель управления Rubinov AI</h3>
                <button type="button" class="admin-close" onclick="toggleAdminModal(false)">×</button>
            </div>
            
            <div class="admin-nav-tabs">
                <button type="button" class="tab-btn active" id="tab-users-btn" onclick="switchAdminTab('users')">👥 Пользователи</button>
                <button type="button" class="tab-btn" id="tab-tickets-btn" onclick="switchAdminTab('tickets')">💬 Тикеты поддержки</button>
            </div>

            <div id="admin-tab-users" style="display: flex; flex-direction: column; flex: 1; overflow: hidden;">
                <div class="admin-filters">
                    <button type="button" class="filter-btn active" onclick="filterAdminUsers('all', this)">Все</button>
                    <button type="button" class="filter-btn" onclick="filterAdminUsers('admin', this)">👑 Админы</button>
                    <button type="button" class="filter-btn" onclick="filterAdminUsers('vip', this)">💎 VIP</button>
                    <button type="button" class="filter-btn" onclick="filterAdminUsers('free', this)">👤 Free</button>
                    <button type="button" class="filter-btn" onclick="filterAdminUsers('banned', this)">🚫 Забаненные</button>
                </div>
                <div class="admin-content">
                    <table class="admin-table">
                        <thead>
                            <tr>
                                <th>Email</th>
                                <th>Статус</th>
                                <th>Запросы</th>
                                <th>Управление</th>
                            </tr>
                        </thead>
                        <tbody id="admin-users-list">
                            <tr><td colspan="4" style="text-align:center; color:var(--text-muted);">Загрузка...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <div id="admin-tab-tickets" style="display: none; flex-direction: column; flex: 1; overflow: hidden;">
                <div class="admin-filters">
                    <button type="button" class="filter-btn active" onclick="filterAdminTickets('open', this)">🔵 Актуальные</button>
                    <button type="button" class="filter-btn" onclick="filterAdminTickets('all', this)">📋 Все тикеты</button>
                </div>
                <div class="admin-content" id="admin-tickets-list">Загрузка тикетов...</div>
            </div>
        </div>
    </div>

    <div id="sidebar">
        <div class="brand">
            <svg class="brand-logo-svg" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
                <defs><linearGradient id="rubyGrad" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#f43f5e" /><stop offset="100%" stop-color="#8b5cf6" /></linearGradient></defs>
                <path d="M50 8 L88 35 L50 92 L12 35 Z" stroke="url(#rubyGrad)" stroke-width="4.5" fill="rgba(244,63,94,0.08)" />
                <path d="M12 35 L88 35 M50 8 L30 35 M50 8 L70 35 M50 92 L30 35 M50 92 L70 35" stroke="url(#rubyGrad)" stroke-width="2.5" opacity="0.75" />
                <circle cx="50" cy="48" r="14" fill="#f43f5e" opacity="0.25" />
            </svg>
            <div><h2>Rubinov AI</h2><span>Neural Studio</span></div>
        </div>

        <button type="button" class="btn-new-chat" onclick="createNewChat()">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 5v14M5 12h14"/></svg>
            Новый диалог
        </button>

        <div class="sidebar-quick-actions">
            <button type="button" class="btn-side-action btn-side-vip" onclick="toggleVipModal(true)">💎 VIP-Тарифы</button>
            <button type="button" class="btn-side-action" onclick="toggleUserSupportModal(true)">🆘 Поддержка</button>
        </div>

        <div class="chats-header"><span>История чатов (<span id="chat-count">1</span>/5)</span></div>
        <div id="chats-list"></div>

        <div class="sidebar-footer">
            USER_AUTH_BLOCK
            <div class="footer-info">
                <div style="display:flex; align-items:center; gap:7px;"><span class="status-dot"></span><span>Gemini 2.5 Online</span></div>
                <span style="font-size:10px; opacity:0.7;">v2.5</span>
            </div>
        </div>
    </div>

    <div id="main">
        <div id="chat-header">
            <div class="header-left">
                <button type="button" class="menu-toggle" onclick="toggleSidebar()" title="Свернуть/развернуть меню">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12h18M3 6h18M3 18h18"/></svg>
                </button>
                <h3 id="current-chat-title">Новый чат</h3>
            </div>
            <div class="header-right">
                <span class="model-pill" id="active-persona-badge">🤖 Универсальный ИИ</span>
            </div>
        </div>

        <div id="chat-container"></div>

        <div id="input-wrapper">
            <div class="input-area-max">
                <div class="persona-bar">
                    <button type="button" class="persona-pill active" data-persona="default" onclick="selectPersona('default', '🤖 Универсальный ИИ', this)">🤖 Универсальный</button>
                    <button type="button" class="persona-pill" data-persona="coder" onclick="selectPersona('coder', '💻 Программист', this)">💻 Программист</button>
                    <button type="button" class="persona-pill" data-persona="copywriter" onclick="selectPersona('copywriter', '✍️ Копирайтер', this)">✍️ Копирайтер</button>
                    <button type="button" class="persona-pill" data-persona="translator" onclick="selectPersona('translator', '🌍 Переводчик', this)">🌍 Переводчик</button>
                </div>

                <div id="input-container">
                    <div id="file-info-bar">
                        <span id="file-name-text">Файл прикреплен</span>
                        <button type="button" onclick="removeSelectedFile()">✕</button>
                    </div>
                    <div class="input-row">
                        <input type="file" id="file-input" accept="image/*" style="display: none;" onchange="handleFileSelect(event)" />
                        <button type="button" class="mini-btn" onclick="checkFilePermissionAndOpen()" title="Загрузить фото для анализа (VIP)">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
                        </button>
                        <button type="button" class="mini-btn" onclick="triggerImageGenerationPrompt()" title="Сгенерировать изображение">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
                        </button>
                        <input type="text" id="prompt-input" placeholder="Задайте любой вопрос Rubinov AI..." onkeydown="handleKeyPress(event)" />
                        <button type="button" class="btn-action" id="action-btn" onclick="handleActionButton()">Отправить</button>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        let chats = JSON.parse(localStorage.getItem('rubinov_chats_v2') || '[]');
        let currentChatId = localStorage.getItem('rubinov_active_chat_v2') || null;
        let selectedFile = null;
        let activeController = null;
        let isGenerating = false;
        let currentPersona = 'default';
        let allUsersCache = [];
        let allTicketsCache = [];
        let currentFilter = 'all';
        let currentTicketFilter = 'open';
        let myCurrentStatus = 'guest';
        let windowCurrentUserEmail = '';
        let activeTicketId = null;

        const SUPER_ADMIN_EMAIL = "8914rpwtutw@gmail.com".toLowerCase();

        function selectPersona(key, label, btn) {
            currentPersona = key;
            document.querySelectorAll('.persona-pill').forEach(p => p.classList.remove('active'));
            if (btn) btn.classList.add('active');
            document.getElementById('active-persona-badge').textContent = label;
        }

        function usePresetCard(personaKey, personaLabel, promptPrefix) {
            const btn = document.querySelector(`.persona-pill[data-persona="${personaKey}"]`);
            selectPersona(personaKey, personaLabel, btn);
            const input = document.getElementById('prompt-input');
            input.value = promptPrefix;
            input.focus();
        }

        async function checkUserStatusRealtime() {
            try {
                const res = await fetch('/api/status-check');
                if (res.ok) {
                    const data = await res.json();
                    windowCurrentUserEmail = (data.email || '').toLowerCase();
                    if (data.status === 'banned') {
                        document.getElementById('banned-overlay').classList.add('active');
                    } else if (myCurrentStatus !== 'guest' && myCurrentStatus !== data.status && myCurrentStatus !== 'unknown') {
                        location.reload();
                    }
                    myCurrentStatus = data.status;

                    const limitEl = document.getElementById('sidebar-limit-info');
                    if (limitEl) {
                        if (data.status === 'vip' || data.status === 'admin') {
                            limitEl.textContent = '♾ Безлимитный доступ';
                            limitEl.style.color = '#c084fc';
                        } else {
                            limitEl.textContent = `Запросов: ${data.requests_used || 0} / 50`;
                        }
                    }
                }
            } catch(e) {}
        }
        setInterval(checkUserStatusRealtime, 8000);
        checkUserStatusRealtime();

        setInterval(() => {
            const supportModal = document.getElementById('user-support-modal');
            if (supportModal && supportModal.classList.contains('active')) {
                activeTicketId ? loadTicketChatMessages(activeTicketId) : loadMyTickets();
            }
            const adminModal = document.getElementById('admin-modal');
            if (adminModal && adminModal.classList.contains('active')) {
                const ticketsTab = document.getElementById('admin-tab-tickets');
                if (ticketsTab && ticketsTab.style.display !== 'none') {
                    activeTicketId ? loadTicketChatMessages(activeTicketId) : loadAdminTickets();
                }
            }
        }, 3500);

        if (chats.length === 0) {
            const initialChat = { id: Date.now().toString(), name: 'Новый диалог 1', messages: [] };
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
            if (window.innerWidth <= 768) {
                document.getElementById('sidebar').classList.toggle('mobile-open');
                document.getElementById('sidebar-overlay').classList.toggle('active');
            } else {
                document.body.classList.toggle('sidebar-collapsed');
            }
        }

        function toggleVipModal(show) {
            document.getElementById('vip-modal').classList.toggle('active', show);
        }

        function toggleAdminModal(show) {
            const modal = document.getElementById('admin-modal');
            if (show) {
                modal.classList.add('active');
                activeTicketId = null;
                loadAdminUsers();
            } else {
                modal.classList.remove('active');
            }
        }

        function switchAdminTab(tab) {
            activeTicketId = null;
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            if (tab === 'users') {
                document.getElementById('tab-users-btn').classList.add('active');
                document.getElementById('admin-tab-users').style.display = 'flex';
                document.getElementById('admin-tab-tickets').style.display = 'none';
                loadAdminUsers();
            } else {
                document.getElementById('tab-tickets-btn').classList.add('active');
                document.getElementById('admin-tab-users').style.display = 'none';
                document.getElementById('admin-tab-tickets').style.display = 'flex';
                loadAdminTickets();
            }
        }

        async function loadAdminUsers() {
            const tbody = document.getElementById('admin-users-list');
            tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:var(--text-muted);">Загрузка...</td></tr>';
            try {
                const res = await fetch('/api/admin/users');
                if (!res.ok) throw new Error();
                const data = await res.json();
                allUsersCache = data.users;
                renderUsersTable();
            } catch (err) {
                tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:#fb7185;">Ошибка загрузки.</td></tr>';
            }
        }

        function filterAdminUsers(filter, btn) {
            currentFilter = filter;
            btn.parentElement.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            renderUsersTable();
        }

        function renderUsersTable() {
            const tbody = document.getElementById('admin-users-list');
            tbody.innerHTML = '';
            const isCurrentSuperAdmin = (myCurrentStatus === 'admin' && windowCurrentUserEmail === SUPER_ADMIN_EMAIL);

            const filtered = allUsersCache.filter(u => currentFilter === 'all' ? true : u.status === currentFilter);
            if (filtered.length === 0) {
                tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:var(--text-muted);">Нет пользователей.</td></tr>';
                return;
            }

            filtered.forEach(u => {
                const tr = document.createElement('tr');
                let actionHtml = '';
                const userEmailLower = u.email.toLowerCase();

                if (userEmailLower === SUPER_ADMIN_EMAIL) {
                    actionHtml = `<span style="color:#fde047; font-weight:bold;">👑 Главный админ</span>`;
                } else if (u.status === 'admin' && !isCurrentSuperAdmin) {
                    actionHtml = `<span style="color:#c084fc; font-weight:bold;">Администратор</span>`;
                } else {
                    actionHtml = `
                        <select onchange="updateUserStatus('${u.email}', this.value)">
                            <option value="free" ${u.status === 'free' ? 'selected' : ''}>Free</option>
                            <option value="vip" ${u.status === 'vip' ? 'selected' : ''}>VIP</option>
                            <option value="banned" ${u.status === 'banned' ? 'selected' : ''}>Ban</option>
                            ${isCurrentSuperAdmin ? `<option value="admin" ${u.status === 'admin' ? 'selected' : ''}>Admin</option>` : ''}
                        </select>
                    `;
                }

                tr.innerHTML = `
                    <td style="word-break:break-all;">${escapeHtml(u.email)}</td>
                    <td><span class="status-badge badge-${u.status}">${u.status}</span></td>
                    <td><b>${u.requests_count || 0}</b></td>
                    <td class="admin-actions-cell">${actionHtml}</td>
                `;
                tbody.appendChild(tr);
            });
        }

        async function updateUserStatus(email, status) {
            try {
                const res = await fetch('/api/admin/update-status', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email, status })
                });
                if (!res.ok) {
                    const err = await res.json();
                    alert(err.detail || 'Ошибка изменения статуса.');
                }
                loadAdminUsers();
            } catch (e) {
                alert('Ошибка соединения с сервером.');
            }
        }

        async function loadAdminTickets() {
            if (activeTicketId) return;
            const container = document.getElementById('admin-tickets-list');
            try {
                const res = await fetch('/api/admin/tickets');
                if (!res.ok) throw new Error();
                const data = await res.json();
                allTicketsCache = data.tickets;
                renderAdminTickets();
            } catch (err) {
                if (!allTicketsCache.length) container.innerHTML = '<span style="color:#fb7185;">Ошибка загрузки тикетов.</span>';
            }
        }

        function filterAdminTickets(filter, btn) {
            activeTicketId = null;
            currentTicketFilter = filter;
            btn.parentElement.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            renderAdminTickets();
        }

        function renderAdminTickets() {
            const container = document.getElementById('admin-tickets-list');
            container.innerHTML = '';
            const filtered = allTicketsCache.filter(t => currentTicketFilter === 'open' ? (t.status === 'open' || t.status === 'replied') : true);

            if (filtered.length === 0) {
                container.innerHTML = '<div style="text-align:center; color:var(--text-muted); padding: 20px;">Нет актуальных тикетов.</div>';
                return;
            }

            filtered.forEach(t => {
                const card = document.createElement('div');
                card.className = 'ticket-card';
                card.onclick = () => openTicketChat(t.id, true);
                card.innerHTML = `
                    <div class="ticket-header">
                        <span><b>Тикет #${t.id}</b> | ${escapeHtml(t.user_email)}</span>
                        <span class="status-badge badge-${t.status}">${t.status === 'open' ? 'Открыт' : (t.status === 'replied' ? 'Отвечен' : 'Закрыт')}</span>
                    </div>
                    <div class="ticket-msg">${escapeHtml(t.message)}</div>
                `;
                container.appendChild(card);
            });
        }

        async function openTicketChat(ticketId, isAdmin = false) {
            activeTicketId = ticketId;
            const container = isAdmin ? document.getElementById('admin-tickets-list') : document.getElementById('user-support-content');
            container.innerHTML = `
                <div class="ticket-chat-container">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <button type="button" class="btn-ticket-action" onclick="closeTicketChat(${isAdmin})">← Назад к списку</button>
                        ${isAdmin ? `<button type="button" class="btn-ticket-action btn-close-ticket" onclick="closeTicket(${ticketId})">Завершить тикет</button>` : ''}
                    </div>
                    <div class="ticket-chat-messages" id="ticket-chat-messages-box">
                        <div style="text-align:center; color:var(--text-muted);">Загрузка сообщений...</div>
                    </div>
                    <div class="ticket-chat-input-row">
                        <input type="text" id="ticket-chat-input" placeholder="Напишите сообщение..." onkeydown="if(event.key==='Enter') sendTicketChatMessage(${ticketId}, ${isAdmin})" />
                        <button type="button" class="btn-action" onclick="sendTicketChatMessage(${ticketId}, ${isAdmin})">Отправить</button>
                    </div>
                </div>
            `;
            loadTicketChatMessages(ticketId);
        }

        function closeTicketChat(isAdmin) {
            activeTicketId = null;
            if (isAdmin) {
                loadAdminTickets();
            } else {
                document.getElementById('user-support-content').innerHTML = `
                    <form onsubmit="submitUserTicket(event)" style="margin-bottom: 14px;">
                        <label style="font-size: 12px; color: var(--text-muted); display: block; margin-bottom: 6px;">Опишите ваш вопрос или заявку на VIP:</label>
                        <textarea id="user-ticket-input" style="width: 100%; background: rgba(0,0,0,0.4); border: 1px solid var(--border-color); color: #fff; padding: 10px; border-radius: 10px; font-size: 12.5px; outline: none; resize: vertical; min-height: 75px;" placeholder="Здравствуйте! Хочу подключить VIP-статус / задать вопрос..."></textarea>
                        <button type="submit" class="btn-action" style="margin-top: 8px; width: 100%;">Отправить обращение</button>
                    </form>
                    <hr style="border: none; border-top: 1px solid var(--border-color); margin: 14px 0;">
                    <h4 style="font-size: 12.5px; color: #fff; margin-bottom: 10px;">История ваших тикетов:</h4>
                    <div id="user-tickets-list">Загрузка...</div>
                `;
                loadMyTickets();
            }
        }

        async function loadTicketChatMessages(ticketId) {
            const box = document.getElementById('ticket-chat-messages-box');
            if (!box) return;
            try {
                const res = await fetch(`/api/tickets/messages?ticket_id=${ticketId}`);
                if (!res.ok) return;
                const data = await res.json();
                const isAtBottom = box.scrollHeight - box.clientHeight <= box.scrollTop + 50;
                box.innerHTML = '';
                data.messages.forEach(m => {
                    const bubble = document.createElement('div');
                    bubble.className = `t-msg-bubble ${m.role === 'user' ? 't-msg-user' : 't-msg-admin'}`;
                    bubble.innerHTML = `<span class="t-msg-meta">${escapeHtml(m.sender)}</span>${escapeHtml(m.text)}`;
                    box.appendChild(bubble);
                });
                if (isAtBottom) box.scrollTop = box.scrollHeight;
            } catch(e) {}
        }

        async function sendTicketChatMessage(ticketId, isAdmin) {
            const input = document.getElementById('ticket-chat-input');
            const message = input.value.trim();
            if (!message) return;
            const url = isAdmin ? '/api/admin/tickets/reply' : '/api/tickets/send-message';
            const body = isAdmin ? { ticket_id: ticketId, reply: message } : { ticket_id: ticketId, message: message };
            try {
                const res = await fetch(url, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                if (res.ok) {
                    input.value = '';
                    loadTicketChatMessages(ticketId);
                }
            } catch(e) {}
        }

        async function closeTicket(ticketId) {
            if (!confirm('Завершить этот тикет?')) return;
            try {
                await fetch('/api/admin/tickets/reply', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ticket_id: ticketId, close: true })
                });
                closeTicketChat(true);
            } catch(e) {}
        }

        function toggleUserSupportModal(show) {
            const modal = document.getElementById('user-support-modal');
            if (show) {
                if (!windowCurrentUserEmail) {
                    alert('Для обращения в поддержку необходимо войти через Google.');
                    return;
                }
                modal.classList.add('active');
                closeTicketChat(false);
            } else {
                modal.classList.remove('active');
            }
        }

        async function loadMyTickets() {
            if (activeTicketId) return;
            const container = document.getElementById('user-tickets-list');
            if (!container) return;
            try {
                const res = await fetch('/api/tickets/my');
                const data = await res.json();
                if (data.tickets.length === 0) {
                    container.innerHTML = '<span style="color:var(--text-muted); font-size:12px;">У вас пока нет обращений.</span>';
                    return;
                }
                container.innerHTML = '';
                data.tickets.forEach(t => {
                    const item = document.createElement('div');
                    item.className = 'ticket-card';
                    item.onclick = () => openTicketChat(t.id, false);
                    item.innerHTML = `
                        <div class="ticket-header">
                            <span><b>Вопрос #${t.id}</b></span>
                            <span class="status-badge badge-${t.status}">${t.status === 'open' ? 'В обработке' : (t.status === 'replied' ? 'Есть ответ' : 'Закрыт')}</span>
                        </div>
                        <div class="ticket-msg">${escapeHtml(t.message)}</div>
                    `;
                    container.appendChild(item);
                });
            } catch(e) {}
        }

        async function submitUserTicket(e) {
            if (e) e.preventDefault();
            const input = document.getElementById('user-ticket-input');
            const message = input.value.trim();
            if (!message) return alert('Введите текст сообщения.');
            try {
                const res = await fetch('/api/tickets/create', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message })
                });
                if (res.ok) {
                    const data = await res.json();
                    input.value = '';
                    openTicketChat(data.ticket_id, false);
                } else {
                    const data = await res.json();
                    alert(data.detail || 'Ошибка отправки.');
                }
            } catch(e) {}
        }

        function checkFilePermissionAndOpen() {
            if (myCurrentStatus === 'free' || myCurrentStatus === 'guest') {
                toggleVipModal(true);
                return;
            }
            document.getElementById('file-input').click();
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
                    <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:170px;">${escapeHtml(chat.name)}</span>
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
                alert('Достигнут лимит в 5 активных диалогов. Закройте один из старых чатов.');
                return;
            }
            if (activeController) activeController.abort();
            const newChat = { id: Date.now().toString(), name: `Новый диалог ${chats.length + 1}`, messages: [] };
            chats.push(newChat);
            currentChatId = newChat.id;
            setGeneratingState(false);
            saveState();
            if (window.innerWidth <= 768) toggleSidebar();
        }

        function deleteChat(id) {
            chats = chats.filter(c => c.id !== id);
            if (currentChatId === id) currentChatId = chats[0].id;
            saveState();
        }

        function triggerImageGenerationPrompt() {
            const input = document.getElementById('prompt-input');
            input.value = "Нарисуй: ";
            input.focus();
        }

        function enhanceCodeBlocks(container) {
            container.querySelectorAll('pre').forEach(pre => {
                if (pre.querySelector('.copy-code-btn')) return;
                const btn = document.createElement('button');
                btn.className = 'copy-code-btn';
                btn.textContent = 'Копировать';
                btn.onclick = () => {
                    const codeText = pre.querySelector('code') ? pre.querySelector('code').innerText : pre.innerText;
                    navigator.clipboard.writeText(codeText);
                    btn.textContent = 'Скопировано ✓';
                    setTimeout(() => btn.textContent = 'Копировать', 1800);
                };
                pre.appendChild(btn);
            });
        }

        function renderMessages(messages) {
            const chatContainer = document.getElementById('chat-container');
            chatContainer.innerHTML = '';

            if (messages.length === 0) {
                const welcome = document.createElement('div');
                welcome.className = 'welcome-dashboard';
                welcome.innerHTML = `
                    <div class="hero-banner">
                        <div class="hero-text">
                            <div class="hero-badge">✦ Rubinov AI Studio 2.5</div>
                            <h1>Чем я могу помочь вам сегодня?</h1>
                            <p>Единая нейросетевая студия для генерации кода, создания артов в высоком разрешении, анализа изображений и работы с текстом.</p>
                        </div>
                        <svg class="hero-ruby-art" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <path d="M50 6 L90 34 L50 94 L10 34 Z" stroke="url(#rubyGrad)" stroke-width="3.5" fill="rgba(244,63,94,0.12)" />
                            <path d="M10 34 L90 34 M50 6 L30 34 M50 6 L70 34 M50 94 L30 34 M50 94 L70 34" stroke="url(#rubyGrad)" stroke-width="2" opacity="0.8" />
                        </svg>
                    </div>

                    <div class="bento-grid">
                        <div class="bento-card" onclick="usePresetCard('coder', '💻 Программист', 'Напиши скрипт на Python для: ')">
                            <div class="bento-card-top">
                                <div class="bento-icon">💻</div>
                                <span class="bento-tag">Dev Mode</span>
                            </div>
                            <h4>Разработка и отладка кода</h4>
                            <p>Создание скриптов, ботов, веб-приложений, поиск багов и рефакторинг на Python, JS, HTML/CSS.</p>
                        </div>

                        <div class="bento-card" onclick="triggerImageGenerationPrompt()">
                            <div class="bento-card-top">
                                <div class="bento-icon">🎨</div>
                                <span class="bento-tag">HD Art</span>
                            </div>
                            <h4>Генерация изображений</h4>
                            <p>Создание детализированных иллюстраций, логотипов и артов по текстовому описанию.</p>
                        </div>

                        <div class="bento-card" onclick="checkFilePermissionAndOpen()">
                            <div class="bento-card-top">
                                <div class="bento-icon">👁</div>
                                <span class="bento-tag">VIP Vision</span>
                            </div>
                            <h4>Анализ фото и скриншотов</h4>
                            <p>Распознавание текста, решение задач по фотографии, разбор графиков и ошибок на скриншоте.</p>
                        </div>

                        <div class="bento-card" onclick="usePresetCard('copywriter', '✍️ Копирайтер', 'Напиши продающий пост для Telegram на тему: ')">
                            <div class="bento-card-top">
                                <div class="bento-icon">✍️</div>
                                <span class="bento-tag">Content</span>
                            </div>
                            <h4>Копирайтинг и контент</h4>
                            <p>Написание постов для Telegram, рекламных офферов, статей, рерайт и перевод текстов.</p>
                        </div>
                    </div>

                    <div class="quick-prompts-row">
                        <button type="button" class="quick-chip" onclick="usePresetCard('default', '🤖 Универсальный ИИ', 'Составь пошаговый план запуска Telegram-бота')">🚀 План запуска проекта</button>
                        <button type="button" class="quick-chip" onclick="usePresetCard('default', '🤖 Универсальный ИИ', 'Нарисуй: футуристический рубиновый кристалл в киберпанк городе')">💎 Арт: Рубин в киберпанке</button>
                        <button type="button" class="quick-chip" onclick="usePresetCard('coder', '💻 Программист', 'Объясни простыми словами как работает асинхронность в Python')">⚡ Python AsyncIO</button>
                    </div>
                `;
                chatContainer.appendChild(welcome);
                return;
            }

            messages.forEach(msg => {
                const row = document.createElement('div');
                row.className = `msg-row ${msg.role === 'user' ? 'user-row' : 'bot-row'}`;

                if (msg.role === 'user') {
                    const bubble = document.createElement('div');
                    bubble.className = 'msg-user';
                    let html = '';
                    if (msg.file_name) html += `<div class="file-preview-tag">📎 ${escapeHtml(msg.file_name)}</div>`;
                    html += escapeHtml(msg.text);
                    bubble.innerHTML = html;
                    row.appendChild(bubble);
                } else {
                    const bubble = document.createElement('div');
                    bubble.className = 'msg-bot';
                    bubble.innerHTML = marked.parse(msg.text || '');
                    enhanceCodeBlocks(bubble);
                    row.appendChild(bubble);
                }

                chatContainer.appendChild(row);
            });

            chatContainer.scrollTop = chatContainer.scrollHeight;
        }

        function handleKeyPress(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleActionButton();
            }
        }

        function handleFileSelect(e) {
            const file = e.target.files[0];
            if (!file) return;
            selectedFile = file;
            document.getElementById('file-name-text').textContent = `📎 ${file.name}`;
            document.getElementById('file-info-bar').style.display = 'flex';
        }

        function removeSelectedFile() {
            selectedFile = null;
            document.getElementById('file-input').value = '';
            document.getElementById('file-info-bar').style.display = 'none';
        }

        function setGeneratingState(generating) {
            isGenerating = generating;
            const btn = document.getElementById('action-btn');
            if (generating) {
                btn.textContent = 'Отмена';
                btn.classList.add('cancel-mode');
            } else {
                btn.textContent = 'Отправить';
                btn.classList.remove('cancel-mode');
            }
        }

        function handleActionButton() {
            if (isGenerating) {
                if (activeController) {
                    activeController.abort();
                    activeController = null;
                }
                setGeneratingState(false);
                removeLoader();
                return;
            }

            const input = document.getElementById('prompt-input');
            const text = input.value.trim();
            if (!text && !selectedFile) return;

            const activeChat = chats.find(c => c.id === currentChatId);
            if (!activeChat) return;

            if (activeChat.messages.length === 0 && text) {
                activeChat.name = text.length > 24 ? text.substring(0, 24) + '...' : text;
            }

            activeChat.messages.push({
                role: 'user',
                text: text,
                file_name: selectedFile ? selectedFile.name : null
            });
            saveState();

            input.value = '';
            const currentFile = selectedFile;
            removeSelectedFile();

            showLoader();
            setGeneratingState(true);

            activeController = new AbortController();
            const formData = new FormData();
            formData.append('prompt', text);
            formData.append('persona', currentPersona);
            if (currentFile) formData.append('file', currentFile);

            fetch('/api/chat', {
                method: 'POST',
                body: formData,
                signal: activeController.signal
            })
            .then(async res => {
                if (!res.ok) {
                    const errData = await res.json().catch(() => ({ detail: 'Ошибка сервера' }));
                    throw new Error(errData.detail || 'Не удалось получить ответ от сервера.');
                }
                return res.json();
            })
            .then(data => {
                removeLoader();
                setGeneratingState(false);
                activeController = null;
                activeChat.messages.push({ role: 'bot', text: data.response });
                saveState();
                checkUserStatusRealtime();
            })
            .catch(err => {
                removeLoader();
                setGeneratingState(false);
                if (err.name === 'AbortError') {
                    activeChat.messages.push({ role: 'bot', text: '*Генерация остановлена пользователем.*' });
                    saveState();
                    return;
                }
                activeController = null;
                activeChat.messages.push({ role: 'bot', text: `⚠️ **Ошибка:** ${err.message}` });
                saveState();
            });
        }

        function showLoader() {
            removeLoader();
            const container = document.getElementById('chat-container');
            const loaderRow = document.createElement('div');
            loaderRow.className = 'msg-row bot-row';
            loaderRow.id = 'active-loader';
            loaderRow.innerHTML = `
                <div class="loader-box">
                    <div class="spinner"></div>
                    <span>Rubinov AI формирует ответ...</span>
                </div>
            `;
            container.appendChild(loaderRow);
            container.scrollTop = container.scrollHeight;
        }

        function removeLoader() {
            const loader = document.getElementById('active-loader');
            if (loader) loader.remove();
        }

        function escapeHtml(str) {
            if (!str) return '';
            return str
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");
        }

        renderChats();
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

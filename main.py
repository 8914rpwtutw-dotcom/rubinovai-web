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

app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])
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

DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    if not DATABASE_URL:
        raise HTTPException(status_code=500, detail="DATABASE_URL не настроена в Environment Variables.")
    return psycopg2.connect(DATABASE_URL)

SUPER_ADMIN = "8914rpwtutw@gmail.com".lower()
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
            CREATE TABLE IF NOT EXISTS vip_requests (
                id SERIAL PRIMARY KEY,
                user_email TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
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

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET status = %s WHERE email = %s", (new_status, target_email))
    conn.commit()
    cursor.close()
    conn.close()
    return {"success": True}

@app.post("/api/vip/request")
async def request_vip(request: Request):
    user_email = request.session.get("user_email")
    if not user_email:
        raise HTTPException(status_code=401, detail="Войдите через Google для отправки запроса.")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM vip_requests WHERE user_email = %s AND status = 'pending'", (user_email.lower(),))
    if cursor.fetchone():
        cursor.close()
        conn.close()
        raise HTTPException(status_code=400, detail="У вас уже есть активный поданный запрос на рассмотрении.")
    
    cursor.execute("INSERT INTO vip_requests (user_email, status) VALUES (%s, 'pending')", (user_email.lower(),))
    conn.commit()
    cursor.close()
    conn.close()
    return {"success": True}

@app.get("/api/admin/vip-requests")
def admin_get_vip_requests(request: Request):
    user_email = request.session.get("user_email")
    if get_user_status(user_email) != "admin":
        raise HTTPException(status_code=403, detail="Доступ запрещен")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_email, status, created_at FROM vip_requests ORDER BY created_at DESC")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return {"requests": [{"id": r[0], "user_email": r[1], "status": r[2], "created_at": str(r[3])} for r in rows]}

@app.post("/api/admin/vip-requests/decide")
async def admin_decide_vip_request(request: Request):
    user_email = request.session.get("user_email")
    if get_user_status(user_email) != "admin":
        raise HTTPException(status_code=403, detail="Доступ запрещен")
    
    body = await request.json()
    req_id = body.get("request_id")
    action = body.get("action") # 'approve' or 'reject'
    
    if action not in ["approve", "reject"]:
        raise HTTPException(status_code=400, detail="Неверное действие.")
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_email FROM vip_requests WHERE id = %s", (req_id,))
    row = cursor.fetchone()
    if not row:
        cursor.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Запрос не найден.")
        
    target_email = row[0]
    new_req_status = "approved" if action == "approve" else "rejected"
    
    cursor.execute("UPDATE vip_requests SET status = %s WHERE id = %s", (new_req_status, req_id))
    if action == "approve":
        cursor.execute("UPDATE users SET status = 'vip' WHERE email = %s", (target_email,))
        
    conn.commit()
    cursor.close()
    conn.close()
    return {"success": True}

@app.post("/api/tickets/create")
async def create_ticket(request: Request):
    user_email = request.session.get("user_email")
    if not user_email:
        raise HTTPException(status_code=401, detail="Войдите через Google.")
    body = await request.json()
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Сообщение не может быть пустым.")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO tickets (user_email, message, status) VALUES (%s, %s, 'open') RETURNING id", (user_email.lower(), message))
    ticket_id = cursor.fetchone()[0]
    cursor.execute("INSERT INTO ticket_messages (ticket_id, sender, sender_role, message) VALUES (%s, %s, 'user', %s)", (ticket_id, user_email.lower(), message))
    conn.commit()
    cursor.close()
    conn.close()
    return {"success": True, "ticket_id": ticket_id}

@app.post("/api/tickets/send-message")
async def send_ticket_message(request: Request):
    user_email = request.session.get("user_email")
    if not user_email:
        raise HTTPException(status_code=401, detail="Авторизуйтесь.")
    body = await request.json()
    ticket_id = body.get("ticket_id")
    message = (body.get("message") or "").strip()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO ticket_messages (ticket_id, sender, sender_role, message) VALUES (%s, %s, 'user', %s)", (ticket_id, user_email.lower(), message))
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
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, sender, sender_role, message, created_at FROM ticket_messages WHERE ticket_id = %s ORDER BY id ASC", (ticket_id,))
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
    cursor.execute("SELECT id, message, status, created_at FROM tickets WHERE user_email = %s ORDER BY updated_at DESC", (user_email.lower(),))
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
        cursor.execute("INSERT INTO ticket_messages (ticket_id, sender, sender_role, message) VALUES (%s, %s, 'admin', %s)", (ticket_id, user_email.lower(), reply))
    new_status = "closed" if close_ticket else "replied"
    cursor.execute("UPDATE tickets SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (new_status, ticket_id))
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
    <title>Rubinov AI — Neural Studio</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <style>
        :root {
            --bg-main: #010204;
            --bg-sidebar: rgba(4, 6, 10, 0.94);
            --card-bg: rgba(10, 13, 20, 0.75);
            --card-hover: rgba(18, 23, 35, 0.9);
            --border-color: rgba(255, 255, 255, 0.06);
            --border-ruby: rgba(244, 63, 94, 0.3);
            --ruby-gradient: linear-gradient(135deg, #f43f5e 0%, #8b5cf6 100%);
            --ruby-glow: rgba(244, 63, 94, 0.2);
            --text-main: #f8fafc;
            --text-muted: #8892b0;
            --user-msg-bg: linear-gradient(135deg, rgba(244, 63, 94, 0.18) 0%, rgba(168, 85, 247, 0.18) 100%);
            --bot-msg-bg: rgba(8, 11, 18, 0.85);
            --scrollbar-thumb: rgba(255, 255, 255, 0.1);
        }

        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', -apple-system, sans-serif; -webkit-tap-highlight-color: transparent; }
        html, body { height: 100%; height: 100dvh; overflow: hidden; background: var(--bg-main); color: var(--text-main); }
        body { display: flex; position: relative; }

        body::before {
            content: ''; position: fixed; top: -15vh; left: 5vw; width: 45vw; height: 45vh;
            background: radial-gradient(circle, rgba(244, 63, 94, 0.06) 0%, rgba(168, 85, 247, 0.02) 60%, transparent 85%);
            z-index: 0; pointer-events: none; filter: blur(100px);
        }

        ::-webkit-scrollbar { width: 4px; height: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: var(--scrollbar-thumb); border-radius: 20px; }

        #sidebar-overlay {
            display: none; position: fixed; top: 0; left: 0; width: 100vw; height: 100dvh;
            background: rgba(1, 2, 4, 0.8); backdrop-filter: blur(8px); z-index: 40; opacity: 0; transition: opacity 0.3s ease;
        }
        #sidebar-overlay.active { display: block; opacity: 1; }

        #sidebar { 
            width: 275px; min-width: 275px; background: var(--bg-sidebar); backdrop-filter: blur(30px);
            -webkit-backdrop-filter: blur(30px); border-right: 1px solid var(--border-color); 
            display: flex; flex-direction: column; padding: 18px 12px; z-index: 50; height: 100dvh;
            transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1), margin-left 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            box-shadow: 20px 0 50px rgba(0, 0, 0, 0.6);
        }
        body.sidebar-collapsed #sidebar { margin-left: -275px; }

        .brand { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; padding: 0 4px; }
        .brand-logo-svg { width: 30px; height: 30px; filter: drop-shadow(0 0 12px rgba(244, 63, 94, 0.5)); flex-shrink: 0; }
        .brand h2 { font-size: 15px; font-weight: 800; background: linear-gradient(90deg, #fff, #fda4af); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .brand span { font-size: 9.5px; color: var(--text-muted); font-weight: 600; display: block; text-transform: uppercase; letter-spacing: 0.8px; }

        .btn-new-chat { 
            background: var(--ruby-gradient); color: #ffffff; border: none; padding: 10px 14px; 
            border-radius: 12px; font-size: 12px; font-weight: 700; cursor: pointer; 
            display: flex; align-items: center; justify-content: center; gap: 7px; margin-bottom: 10px; 
            transition: all 0.2s ease; box-shadow: 0 4px 20px rgba(244, 63, 94, 0.3);
        }
        .btn-new-chat:hover { transform: translateY(-1px); box-shadow: 0 6px 24px rgba(244, 63, 94, 0.45); }

        .sidebar-quick-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 14px; }
        .btn-side-action {
            background: rgba(255, 255, 255, 0.02); border: 1px solid var(--border-color); color: #cbd5e1;
            padding: 7px 8px; border-radius: 10px; font-size: 10.5px; font-weight: 600; cursor: pointer;
            display: flex; align-items: center; justify-content: center; gap: 5px; transition: all 0.2s;
        }
        .btn-side-action:hover { background: rgba(244, 63, 94, 0.12); border-color: rgba(244, 63, 94, 0.3); color: #fff; }
        .btn-side-vip { border-color: rgba(168, 85, 247, 0.3); background: rgba(168, 85, 247, 0.06); color: #e9d5ff; }
        .btn-side-vip:hover { background: rgba(168, 85, 247, 0.18); border-color: rgba(168, 85, 247, 0.5); }

        .chats-header { display: flex; justify-content: space-between; font-size: 9.5px; color: var(--text-muted); font-weight: 700; margin-bottom: 6px; padding: 0 4px; text-transform: uppercase; letter-spacing: 0.8px; }
        
        #chats-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 5px; padding-right: 2px; }
        .chat-item { 
            background: rgba(255, 255, 255, 0.01); border: 1px solid var(--border-color); 
            border-radius: 10px; padding: 9px 11px; font-size: 11.5px; color: #cbd5e1; 
            display: flex; justify-content: space-between; align-items: center; cursor: pointer; transition: all 0.2s ease;
        }
        .chat-item.active { 
            background: linear-gradient(90deg, rgba(244, 63, 94, 0.1), rgba(168, 85, 247, 0.06)); 
            border-color: rgba(244, 63, 94, 0.35); color: #ffffff;
        }
        .chat-item:hover { background: rgba(255, 255, 255, 0.035); border-color: rgba(244, 63, 94, 0.25); color: #ffffff; }
        .chat-item .close-btn { color: var(--text-muted); font-size: 13px; cursor: pointer; border-radius: 5px; width: 20px; height: 20px; display: flex; align-items: center; justify-content: center; }
        .chat-item .close-btn:hover { color: #fb7185; background: rgba(244, 63, 94, 0.15); }

        .sidebar-footer { font-size: 11px; color: var(--text-muted); display: flex; flex-direction: column; gap: 7px; margin-top: auto; padding-top: 10px; border-top: 1px solid var(--border-color); }
        .user-profile-card { background: rgba(255,255,255,0.02); border: 1px solid var(--border-color); border-radius: 11px; padding: 8px 10px; }
        .footer-info { display: flex; align-items: center; justify-content: space-between; width: 100%; padding: 0 2px; }
        .status-dot { width: 6px; height: 6px; background: #10b981; border-radius: 50%; box-shadow: 0 0 8px rgba(16, 185, 129, 0.8); }

        .btn-google-login {
            background: rgba(255, 255, 255, 0.04); border: 1px solid rgba(255, 255, 255, 0.1);
            color: #ffffff; padding: 8px 10px; border-radius: 10px; font-size: 11.5px; font-weight: 600;
            text-decoration: none; display: flex; align-items: center; justify-content: center; gap: 7px; transition: all 0.2s ease;
        }
        .btn-google-login:hover { background: rgba(255, 255, 255, 0.08); border-color: rgba(244, 63, 94, 0.4); }

        .btn-admin-panel {
            background: linear-gradient(135deg, rgba(234, 179, 8, 0.15), rgba(244, 63, 94, 0.15)); 
            border: 1px solid rgba(234, 179, 8, 0.4);
            color: #fde047; padding: 7px 10px; border-radius: 10px; font-size: 11px; font-weight: 700;
            cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 5px; transition: all 0.2s ease;
            width: 100%; margin-bottom: 6px;
        }
        .btn-admin-panel:hover { background: rgba(234, 179, 8, 0.25); color: #fff; }

        .status-badge { padding: 2px 6px; border-radius: 5px; font-size: 9px; font-weight: 800; text-transform: uppercase; display: inline-block; }
        .badge-vip { background: rgba(168, 85, 247, 0.2); color: #e9d5ff; border: 1px solid rgba(168,85,247,0.4); }
        .badge-free { background: rgba(136, 146, 176, 0.12); color: #cbd5e1; border: 1px solid rgba(136, 146, 176, 0.2); }
        .badge-admin { background: rgba(234, 179, 8, 0.2); color: #fde047; border: 1px solid rgba(234,179,8,0.4); }
        .badge-banned { background: rgba(244, 63, 94, 0.2); color: #fda4af; }
        .badge-open, .badge-pending { background: rgba(59, 130, 246, 0.2); color: #93c5fd; border: 1px solid rgba(59, 130, 246, 0.4); }
        .badge-approved { background: rgba(16, 185, 129, 0.2); color: #6ee7b7; border: 1px solid rgba(16, 185, 129, 0.4); }
        .badge-rejected { background: rgba(244, 63, 94, 0.2); color: #fda4af; border: 1px solid rgba(244, 63, 94, 0.4); }
        .badge-closed, .badge-replied { background: rgba(100, 116, 139, 0.2); color: #cbd5e1; }

        #admin-modal, #user-support-modal, #vip-modal, #toast-container {
            display: none; position: fixed; top: 0; left: 0; width: 100vw; height: 100dvh;
            background: rgba(1, 2, 4, 0.85); backdrop-filter: blur(10px); z-index: 100;
            align-items: center; justify-content: center; padding: 12px;
        }
        #toast-container { z-index: 9999; pointer-events: none; justify-content: flex-end; align-items: flex-end; padding: 20px; }
        .toast {
            background: #0f1420; border: 1px solid rgba(244, 63, 94, 0.4); color: #fff; padding: 12px 18px;
            border-radius: 12px; font-size: 12.5px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); pointer-events: auto;
            animation: slideUp 0.3s ease; display: flex; align-items: center; gap: 8px;
        }
        @keyframes slideUp { from { transform: translateY(20px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }

        #admin-modal.active, #user-support-modal.active, #vip-modal.active, #toast-container.active { display: flex; }

        .admin-box {
            background: #06080d; border: 1px solid rgba(244, 63, 94, 0.25); border-radius: 20px;
            width: 100%; max-width: 820px; height: 82dvh; display: flex; flex-direction: column; overflow: hidden;
            box-shadow: 0 24px 60px rgba(0,0,0,0.9);
        }
        .vip-modal-box {
            background: linear-gradient(180deg, #0a0d14 0%, #030407 100%);
            border: 1px solid rgba(168, 85, 247, 0.35); border-radius: 22px;
            width: 100%; max-width: 600px; padding: 24px; box-shadow: 0 24px 60px rgba(168, 85, 247, 0.15);
        }
        .admin-header {
            padding: 14px 18px; border-bottom: 1px solid var(--border-color);
            display: flex; justify-content: space-between; align-items: center; background: rgba(8, 11, 17, 0.9);
        }
        .admin-header h3 { font-size: 14px; color: #fff; font-weight: 700; }
        .admin-close { background: none; border: none; color: var(--text-muted); font-size: 20px; cursor: pointer; line-height: 1; }
        .admin-close:hover { color: #fb7185; }
        
        .admin-nav-tabs, .admin-filters {
            display: flex; gap: 6px; padding: 10px 16px; background: rgba(5, 7, 12, 0.95);
            border-bottom: 1px solid var(--border-color); flex-wrap: wrap;
        }
        .tab-btn, .filter-btn {
            background: rgba(255, 255, 255, 0.02); border: 1px solid var(--border-color); color: var(--text-muted);
            padding: 5px 11px; border-radius: 8px; font-size: 11px; font-weight: 600; cursor: pointer; transition: all 0.2s;
        }
        .tab-btn.active { background: var(--ruby-gradient); color: #fff; border-color: transparent; }
        .filter-btn.active { background: rgba(244, 63, 94, 0.15); border-color: rgba(244, 63, 94, 0.35); color: #fff; }

        .admin-content { padding: 14px; overflow-y: auto; flex: 1; }
        .admin-table { width: 100%; border-collapse: collapse; font-size: 11.5px; }
        .admin-table th, .admin-table td { padding: 9px; text-align: left; border-bottom: 1px solid var(--border-color); color: #f1f5f9; }
        .admin-table th { color: var(--text-muted); font-weight: 600; background: rgba(255,255,255,0.015); }
        .admin-actions-cell select {
            background: #111520; border: 1px solid rgba(244, 63, 94, 0.3); color: #ffffff;
            padding: 4px 7px; border-radius: 6px; font-size: 11px; outline: none; cursor: pointer;
        }

        .ticket-card {
            background: rgba(255, 255, 255, 0.02); border: 1px solid var(--border-color);
            border-radius: 11px; padding: 11px 13px; margin-bottom: 8px; display: flex; flex-direction: column; gap: 6px; cursor: pointer; transition: all 0.2s;
        }
        .ticket-card:hover { border-color: rgba(244, 63, 94, 0.3); background: rgba(255,255,255,0.035); }
        .ticket-header { display: flex; justify-content: space-between; align-items: center; font-size: 10.5px; color: var(--text-muted); }
        .ticket-msg { font-size: 12px; color: #f1f5f9; line-height: 1.4; background: rgba(0,0,0,0.2); padding: 7px 9px; border-radius: 7px; }

        .vip-features-list { display: flex; flex-direction: column; gap: 8px; margin: 14px 0; font-size: 12.5px; color: #cbd5e1; }
        .vip-feature-item { display: flex; align-items: center; gap: 8px; background: rgba(255,255,255,0.02); border: 1px solid var(--border-color); padding: 8px 12px; border-radius: 10px; }

        #main { flex: 1; display: flex; flex-direction: column; background: transparent; position: relative; height: 100dvh; overflow: hidden; z-index: 1; }
        
        #chat-header { 
            height: 56px; min-height: 56px; border-bottom: 1px solid var(--border-color); 
            display: flex; align-items: center; justify-content: space-between; 
            padding: 0 20px; background: rgba(1, 2, 4, 0.7); backdrop-filter: blur(16px); z-index: 10;
        }
        .header-left { display: flex; align-items: center; gap: 10px; }
        .header-right { display: flex; align-items: center; gap: 8px; }
        .menu-toggle { 
            background: rgba(255, 255, 255, 0.02); border: 1px solid var(--border-color); 
            color: #ffffff; border-radius: 10px; padding: 7px; cursor: pointer; display: flex; align-items: center; justify-content: center;
        }
        .menu-toggle:hover { border-color: rgba(244, 63, 94, 0.35); }
        #chat-header h3 { font-size: 13.5px; font-weight: 700; color: #ffffff; }
        .model-pill {
            background: rgba(244, 63, 94, 0.08); border: 1px solid rgba(244, 63, 94, 0.25);
            color: #fda4af; padding: 4px 10px; border-radius: 18px; font-size: 10.5px; font-weight: 700;
            display: flex; align-items: center; gap: 5px;
        }

        #chat-container { 
            flex: 1; overflow-y: auto; padding: 20px 20px 160px 20px; 
            display: flex; flex-direction: column; gap: 16px; max-width: 900px; width: 100%; margin: 0 auto; position: relative; z-index: 2;
        }

        .welcome-minimal {
            display: flex; flex-direction: column; align-items: center; justify-content: center;
            text-align: center; margin: auto 0; padding: 20px; gap: 12px; animation: fadeIn 0.4s ease;
        }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
        .welcome-minimal h1 { font-size: 24px; font-weight: 800; background: linear-gradient(90deg, #fff, #fda4af); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .welcome-minimal p { font-size: 13px; color: var(--text-muted); max-width: 480px; line-height: 1.5; }

        .msg-row { display: flex; flex-direction: column; width: 100%; z-index: 2; }
        .msg-row.user-row { align-items: flex-end; }
        .msg-row.bot-row { align-items: flex-start; }

        .msg-user { 
            background: var(--user-msg-bg); color: #ffffff; border: 1px solid rgba(244, 63, 94, 0.25); 
            border-radius: 16px 16px 4px 16px; padding: 11px 15px; font-size: 13px; line-height: 1.5; max-width: 80%; word-break: break-word; 
        }
        .msg-bot { 
            background: var(--bot-msg-bg); border: 1px solid var(--border-color); color: #e2e8f0; 
            border-radius: 16px 16px 16px 4px; padding: 16px 20px; font-size: 13px; line-height: 1.6; max-width: 90%; word-break: break-word;
            box-shadow: 0 6px 25px rgba(0,0,0,0.3);
        }
        .msg-bot p { margin-bottom: 9px; }
        .msg-bot p:last-child { margin-bottom: 0; }
        .msg-bot ul, .msg-bot ol { margin: 6px 0 8px 18px; }
        .msg-bot code { background: rgba(255, 255, 255, 0.06); padding: 2px 5px; border-radius: 5px; font-family: 'JetBrains Mono', monospace; font-size: 11.5px; color: #fda4af; }
        .msg-bot pre { background: #020306; padding: 12px; border-radius: 10px; overflow-x: auto; margin: 10px 0; border: 1px solid rgba(255,255,255,0.08); position: relative; }
        .msg-bot pre code { background: transparent; padding: 0; color: #e2e8f0; }

        .copy-code-btn {
            position: absolute; top: 7px; right: 7px; background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.1); color: #cbd5e1; font-size: 10px; font-weight: 600;
            padding: 3px 8px; border-radius: 6px; cursor: pointer; transition: all 0.2s;
        }
        .copy-code-btn:hover { background: rgba(244, 63, 94, 0.2); color: #fff; border-color: rgba(244, 63, 94, 0.35); }

        .file-preview-tag { display: inline-flex; align-items: center; gap: 5px; background: rgba(244, 63, 94, 0.14); padding: 3px 8px; border-radius: 7px; font-size: 10.5px; margin-bottom: 5px; color: #fda4af; }

        .loader-box {
            display: flex; align-items: center; gap: 10px; background: var(--bot-msg-bg);
            border: 1px solid var(--border-color); border-radius: 16px 16px 16px 4px; padding: 12px 16px; font-size: 12.5px; color: var(--text-muted);
        }
        .spinner {
            width: 14px; height: 14px; border: 2px solid rgba(244, 63, 94, 0.2);
            border-top-color: #f43f5e; border-radius: 50%; animation: spin 0.8s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }

        #input-wrapper {
            position: absolute; bottom: 0; left: 0; right: 0; 
            padding: 10px 20px 14px 20px; padding-bottom: calc(14px + env(safe-area-inset-bottom));
            background: linear-gradient(180deg, rgba(1, 2, 4, 0) 0%, rgba(1, 2, 4, 0.95) 40%, var(--bg-main) 100%);
            z-index: 20;
        }
        .input-area-max { max-width: 900px; margin: 0 auto; display: flex; flex-direction: column; gap: 7px; }

        .persona-bar { display: flex; align-items: center; gap: 5px; overflow-x: auto; padding-bottom: 2px; }
        .persona-pill {
            background: rgba(10, 13, 20, 0.85); border: 1px solid var(--border-color); color: var(--text-muted);
            padding: 5px 11px; border-radius: 18px; font-size: 11px; font-weight: 600; cursor: pointer;
            white-space: nowrap; transition: all 0.2s; display: flex; align-items: center; gap: 5px;
        }
        .persona-pill:hover { border-color: rgba(244, 63, 94, 0.3); color: #fff; }
        .persona-pill.active {
            background: linear-gradient(135deg, rgba(244, 63, 94, 0.2), rgba(168, 85, 247, 0.2));
            border-color: rgba(244, 63, 94, 0.5); color: #ffffff; box-shadow: 0 2px 10px rgba(244, 63, 94, 0.15);
        }

        #input-container { 
            background: rgba(8, 11, 17, 0.95); backdrop-filter: blur(24px); 
            border: 1px solid rgba(244, 63, 94, 0.22); border-radius: 16px; 
            padding: 6px 9px; display: flex; flex-direction: column; gap: 5px; box-shadow: 0 10px 30px rgba(0, 0, 0, 0.7);
        }
        #input-container:focus-within { border-color: rgba(244, 63, 94, 0.5); box-shadow: 0 10px 30px rgba(244, 63, 94, 0.12); }
        #file-info-bar { display: none; align-items: center; justify-content: space-between; background: rgba(244, 63, 94, 0.12); padding: 4px 9px; border-radius: 7px; font-size: 10.5px; color: #fda4af; }
        #file-info-bar button { background: none; border: none; color: #fb7185; cursor: pointer; font-size: 12px; }

        .input-row { display: flex; gap: 6px; align-items: center; width: 100%; }
        .mini-btn { 
            background: rgba(255, 255, 255, 0.02); border: 1px solid var(--border-color); color: var(--text-muted); 
            padding: 8px; border-radius: 10px; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: all 0.2s;
        }
        .mini-btn:hover { background: rgba(244, 63, 94, 0.12); border-color: rgba(244, 63, 94, 0.3); color: #fff; }
        #prompt-input { flex: 1; background: transparent; border: none; color: #ffffff; font-size: 13px; outline: none; min-width: 0; padding: 4px; }
        #prompt-input::placeholder { color: var(--text-muted); }
        
        .btn-action { 
            background: var(--ruby-gradient); color: #ffffff; border: none; border-radius: 10px; 
            padding: 9px 16px; font-size: 12px; font-weight: 700; cursor: pointer; flex-shrink: 0; 
            display: flex; align-items: center; justify-content: center; min-width: 90px; transition: all 0.2s;
        }
        .btn-action:hover { box-shadow: 0 4px 15px rgba(244, 63, 94, 0.35); }
        .btn-action.cancel-mode { background: rgba(244, 63, 94, 0.12); border: 1px solid rgba(244, 63, 94, 0.3); color: #fb7185; }

        @media (max-width: 768px) {
            #sidebar { position: fixed; top: 0; left: 0; margin-left: 0 !important; transform: translateX(-100%); }
            #sidebar.mobile-open { transform: translateX(0); }
            #chat-header { padding: 0 12px; }
            #chat-container { padding: 12px 12px 150px 12px; }
            #input-wrapper { padding: 8px 12px; }
        }
    </style>
</head>
<body>
    <div id="sidebar-overlay" onclick="toggleSidebar()"></div>
    <div id="toast-container"><div class="toast" id="toast-msg">Успешно!</div></div>

    <div id="vip-modal" onclick="if(event.target.id==='vip-modal') toggleVipModal(false)">
        <div class="vip-modal-box" onclick="event.stopPropagation()">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <h3 style="font-size:17px; font-weight:800; color:#fff;">💎 VIP-Уровень Rubinov AI</h3>
                <button type="button" class="admin-close" onclick="toggleVipModal(false)">×</button>
            </div>
            <p style="font-size:12px; color:#8892b0; margin-top:3px;">Получите максимальные возможности нейросети без суточных ограничений.</p>
            
            <div class="vip-features-list">
                <div class="vip-feature-item">♾ Безлимитные запросы к Gemini 2.5 Flash 24/7</div>
                <div class="vip-feature-item">👁 Загрузка и анализ фото, документов и скриншотов</div>
                <div class="vip-feature-item">⚡ Приоритетная генерация артов и ответов ИИ</div>
                <div class="vip-feature-item">👑 Эксклюзивный статус и персональная поддержка</div>
            </div>

            <button type="button" class="btn-action" style="width:100%; margin-top:8px; padding: 11px;" onclick="submitVipRequest()">Запросить VIP-доступ</button>
        </div>
    </div>

    <div id="user-support-modal" onclick="if(event.target.id==='user-support-modal') toggleUserSupportModal(false)">
        <div class="admin-box" style="max-width:520px;" onclick="event.stopPropagation()">
            <div class="admin-header">
                <h3>🆘 Поддержка Rubinov AI</h3>
                <button type="button" class="admin-close" onclick="toggleUserSupportModal(false)">×</button>
            </div>
            <div class="admin-content" id="user-support-content">
                <form onsubmit="submitUserTicket(event)" style="margin-bottom: 12px;">
                    <label style="font-size: 11.5px; color: var(--text-muted); display: block; margin-bottom: 5px;">Опишите ваш вопрос:</label>
                    <textarea id="user-ticket-input" style="width: 100%; background: rgba(0,0,0,0.3); border: 1px solid var(--border-color); color: #fff; padding: 9px; border-radius: 9px; font-size: 12px; outline: none; resize: vertical; min-height: 70px;" placeholder="Здравствуйте! У меня вопрос по..."></textarea>
                    <button type="submit" class="btn-action" style="margin-top: 6px; width: 100%;">Отправить тикет</button>
                </form>
                <hr style="border: none; border-top: 1px solid var(--border-color); margin: 12px 0;">
                <h4 style="font-size: 12px; color: #fff; margin-bottom: 8px;">Ваши обращения:</h4>
                <div id="user-tickets-list">Загрузка...</div>
            </div>
        </div>
    </div>

    <div id="admin-modal" onclick="if(event.target.id==='admin-modal') toggleAdminModal(false)">
        <div class="admin-box" onclick="event.stopPropagation()">
            <div class="admin-header">
                <h3>👑 Админ-панель Rubinov AI</h3>
                <button type="button" class="admin-close" onclick="toggleAdminModal(false)">×</button>
            </div>
            
            <div class="admin-nav-tabs">
                <button type="button" class="tab-btn active" id="tab-users-btn" onclick="switchAdminTab('users')">👥 Пользователи</button>
                <button type="button" class="tab-btn" id="tab-vip-btn" onclick="switchAdminTab('vip')">💎 Запросы VIP</button>
                <button type="button" class="tab-btn" id="tab-tickets-btn" onclick="switchAdminTab('tickets')">💬 Поддержка</button>
            </div>

            <div id="admin-tab-users" style="display: flex; flex-direction: column; flex: 1; overflow: hidden;">
                <div class="admin-filters">
                    <button type="button" class="filter-btn active" onclick="filterAdminUsers('all', this)">Все</button>
                    <button type="button" class="filter-btn" onclick="filterAdminUsers('admin', this)">👑 Админы</button>
                    <button type="button" class="filter-btn" onclick="filterAdminUsers('vip', this)">💎 VIP</button>
                    <button type="button" class="filter-btn" onclick="filterAdminUsers('free', this)">👤 Free</button>
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

            <div id="admin-tab-vip" style="display: none; flex-direction: column; flex: 1; overflow: hidden;">
                <div class="admin-content" id="admin-vip-requests-list">Загрузка запросов...</div>
            </div>

            <div id="admin-tab-tickets" style="display: none; flex-direction: column; flex: 1; overflow: hidden;">
                <div class="admin-content" id="admin-tickets-list">Загрузка тикетов...</div>
            </div>
        </div>
    </div>

    <div id="sidebar">
        <div class="brand">
            <svg class="brand-logo-svg" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
                <defs><linearGradient id="rubyGrad" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#f43f5e" /><stop offset="100%" stop-color="#8b5cf6" /></linearGradient></defs>
                <path d="M50 8 L88 35 L50 92 L12 35 Z" stroke="url(#rubyGrad)" stroke-width="4" fill="rgba(244,63,94,0.08)" />
                <path d="M12 35 L88 35 M50 8 L30 35 M50 8 L70 35 M50 92 L30 35 M50 92 L70 35" stroke="url(#rubyGrad)" stroke-width="2" opacity="0.7" />
                <circle cx="50" cy="48" r="12" fill="#f43f5e" opacity="0.25" />
            </svg>
            <div><h2>Rubinov AI</h2><span>Neural Studio</span></div>
        </div>

        <button type="button" class="btn-new-chat" onclick="createNewChat()">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 5v14M5 12h14"/></svg>
            Новый диалог
        </button>

        <div class="sidebar-quick-actions">
            <button type="button" class="btn-side-action btn-side-vip" onclick="toggleVipModal(true)">💎 VIP-Тариф</button>
            <button type="button" class="btn-side-action" onclick="toggleUserSupportModal(true)">🆘 Поддержка</button>
        </div>

        <div class="chats-header"><span>История чатов (<span id="chat-count">1</span>/5)</span></div>
        <div id="chats-list"></div>

        <div class="sidebar-footer">
            USER_AUTH_BLOCK
            <div class="footer-info">
                <div style="display:flex; align-items:center; gap:6px;"><span class="status-dot"></span><span>Gemini 2.5 Online</span></div>
                <span style="font-size:9.5px; opacity:0.6;">v2.5 OLED</span>
            </div>
        </div>
    </div>

    <div id="main">
        <div id="chat-header">
            <div class="header-left">
                <button type="button" class="menu-toggle" onclick="toggleSidebar()" title="Меню">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12h18M3 6h18M3 18h18"/></svg>
                </button>
                <h3 id="current-chat-title">Новый чат</h3>
            </div>
            <div class="header-right">
                <span class="model-pill" id="active-persona-badge">🤖 Универсальный</span>
            </div>
        </div>

        <div id="chat-container"></div>

        <div id="input-wrapper">
            <div class="input-area-max">
                <div class="persona-bar">
                    <button type="button" class="persona-pill active" data-persona="default" onclick="selectPersona('default', '🤖 Универсальный', this)">🤖 Универсальный</button>
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
                        <button type="button" class="mini-btn" onclick="checkFilePermissionAndOpen()" title="Загрузить фото (VIP)">
                            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
                        </button>
                        <button type="button" class="mini-btn" onclick="triggerImageGenerationPrompt()" title="Сгенерировать картинку">
                            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
                        </button>
                        <input type="text" id="prompt-input" placeholder="Введите ваш запрос..." onkeydown="handleKeyPress(event)" />
                        <button type="button" class="btn-action" id="action-btn" onclick="handleActionButton()">Отправить</button>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        let chats = JSON.parse(localStorage.getItem('rubinov_chats_v3') || '[]');
        let currentChatId = localStorage.getItem('rubinov_active_chat_v3') || null;
        let selectedFile = null;
        let activeController = null;
        let isGenerating = false;
        let currentPersona = 'default';
        let allUsersCache = [];
        let allVipReqCache = [];
        let allTicketsCache = [];
        let currentFilter = 'all';
        let myCurrentStatus = 'guest';
        let windowCurrentUserEmail = '';

        const SUPER_ADMIN_EMAIL = "8914rpwtutw@gmail.com".toLowerCase();

        function showToast(text) {
            const container = document.getElementById('toast-container');
            const toast = document.getElementById('toast-msg');
            toast.textContent = text;
            container.classList.add('active');
            setTimeout(() => container.classList.remove('active'), 2500);
        }

        function selectPersona(key, label, btn) {
            currentPersona = key;
            document.querySelectorAll('.persona-pill').forEach(p => p.classList.remove('active'));
            if (btn) btn.classList.add('active');
            document.getElementById('active-persona-badge').textContent = label;
        }

        async function checkUserStatusRealtime() {
            try {
                const res = await fetch('/api/status-check');
                if (res.ok) {
                    const data = await res.json();
                    windowCurrentUserEmail = (data.email || '').toLowerCase();
                    if (myCurrentStatus !== 'guest' && myCurrentStatus !== data.status && myCurrentStatus !== 'unknown') {
                        location.reload();
                    }
                    myCurrentStatus = data.status;

                    const limitEl = document.getElementById('sidebar-limit-info');
                    if (limitEl) {
                        if (data.status === 'vip' || data.status === 'admin') {
                            limitEl.textContent = '♾ Безлимит';
                            limitEl.style.color = '#c084fc';
                        } else {
                            limitEl.textContent = `Запросы: ${data.requests_used || 0}/50`;
                        }
                    }
                }
            } catch(e) {}
        }
        setInterval(checkUserStatusRealtime, 8000);
        checkUserStatusRealtime();

        if (chats.length === 0) {
            const initialChat = { id: Date.now().toString(), name: 'Новый диалог 1', messages: [] };
            chats.push(initialChat);
            currentChatId = initialChat.id;
            saveState();
        } else if (!currentChatId || !chats.find(c => c.id === currentChatId)) {
            currentChatId = chats[0].id;
        }

        function saveState() {
            localStorage.setItem('rubinov_chats_v3', JSON.stringify(chats));
            localStorage.setItem('rubinov_active_chat_v3', currentChatId);
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

        async function submitVipRequest() {
            if (!windowCurrentUserEmail) {
                alert('Пожалуйста, войдите через Google для отправки запроса.');
                return;
            }
            try {
                const res = await fetch('/api/vip/request', { method: 'POST' });
                if (res.ok) {
                    toggleVipModal(false);
                    showToast('💎 Запрос на VIP успешно отправлен админам!');
                } else {
                    const err = await res.json();
                    alert(err.detail || 'Ошибка отправки.');
                }
            } catch(e) {
                alert('Ошибка соединения.');
            }
        }

        function toggleAdminModal(show) {
            const modal = document.getElementById('admin-modal');
            if (show) {
                modal.classList.add('active');
                loadAdminUsers();
            } else {
                modal.classList.remove('active');
            }
        }

        function switchAdminTab(tab) {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            if (tab === 'users') {
                document.getElementById('tab-users-btn').classList.add('active');
                document.getElementById('admin-tab-users').style.display = 'flex';
                document.getElementById('admin-tab-vip').style.display = 'none';
                document.getElementById('admin-tab-tickets').style.display = 'none';
                loadAdminUsers();
            } else if (tab === 'vip') {
                document.getElementById('tab-vip-btn').classList.add('active');
                document.getElementById('admin-tab-users').style.display = 'none';
                document.getElementById('admin-tab-vip').style.display = 'flex';
                document.getElementById('admin-tab-tickets').style.display = 'none';
                loadAdminVipRequests();
            } else {
                document.getElementById('tab-tickets-btn').classList.add('active');
                document.getElementById('admin-tab-users').style.display = 'none';
                document.getElementById('admin-tab-vip').style.display = 'none';
                document.getElementById('admin-tab-tickets').style.display = 'flex';
                loadAdminTickets();
            }
        }

        async function loadAdminUsers() {
            const tbody = document.getElementById('admin-users-list');
            tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:var(--text-muted);">Загрузка...</td></tr>';
            try {
                const res = await fetch('/api/admin/users');
                const data = await res.json();
                allUsersCache = data.users;
                renderUsersTable();
            } catch (e) {
                tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:#fb7185;">Ошибка.</td></tr>';
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
            const filtered = allUsersCache.filter(u => currentFilter === 'all' ? true : u.status === currentFilter);
            if (filtered.length === 0) {
                tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:var(--text-muted);">Нет пользователей.</td></tr>';
                return;
            }
            filtered.forEach(u => {
                const tr = document.createElement('tr');
                const isSuper = (u.email.toLowerCase() === SUPER_ADMIN_EMAIL);
                let actionHtml = isSuper ? '<span style="color:#fde047; font-weight:bold;">Главный админ</span>' : `
                    <select onchange="updateUserStatus('${u.email}', this.value)">
                        <option value="free" ${u.status === 'free' ? 'selected' : ''}>Free</option>
                        <option value="vip" ${u.status === 'vip' ? 'selected' : ''}>VIP</option>
                        <option value="admin" ${u.status === 'admin' ? 'selected' : ''}>Admin</option>
                        <option value="banned" ${u.status === 'banned' ? 'selected' : ''}>Ban</option>
                    </select>
                `;
                tr.innerHTML = `
                    <td style="word-break:break-all;">${escapeHtml(u.email)}</td>
                    <td><span class="status-badge badge-${u.status}">${u.status}</span></td>
                    <td><b>${u.requests_count || 0}</b></td>
                    <td>${actionHtml}</td>
                `;
                tbody.appendChild(tr);
            });
        }

        async function updateUserStatus(email, status) {
            try {
                await fetch('/api/admin/update-status', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email, status })
                });
                showToast('Статус обновлен!');
                loadAdminUsers();
            } catch (e) { alert('Ошибка'); }
        }

        async function loadAdminVipRequests() {
            const container = document.getElementById('admin-vip-requests-list');
            container.innerHTML = '<div style="text-align:center; color:var(--text-muted);">Загрузка запросов...</div>';
            try {
                const res = await fetch('/api/admin/vip-requests');
                const data = await res.json();
                allVipReqCache = data.requests;
                renderVipRequests();
            } catch (e) {
                container.innerHTML = '<span style="color:#fb7185;">Ошибка загрузки.</span>';
            }
        }

        function renderVipRequests() {
            const container = document.getElementById('admin-vip-requests-list');
            container.innerHTML = '';
            if (allVipReqCache.length === 0) {
                container.innerHTML = '<div style="text-align:center; color:var(--text-muted); padding:20px;">Нет запросов на VIP.</div>';
                return;
            }
            allVipReqCache.forEach(r => {
                const card = document.createElement('div');
                card.className = 'ticket-card';
                card.innerHTML = `
                    <div class="ticket-header">
                        <span><b>Запрос #${r.id}</b> | ${escapeHtml(r.user_email)}</span>
                        <span class="status-badge badge-${r.status}">${r.status}</span>
                    </div>
                    <div style="display:flex; gap:8px; margin-top:6px;">
                        ${r.status === 'pending' ? `
                            <button type="button" class="btn-action" style="padding:5px 12px; font-size:11px;" onclick="decideVip(${r.id}, 'approve')">Принять (VIP)</button>
                            <button type="button" class="btn-action cancel-mode" style="padding:5px 12px; font-size:11px;" onclick="decideVip(${r.id}, 'reject')">Отклонить</button>
                        ` : '<span style="font-size:11px; color:var(--text-muted);">Обработано</span>'}
                    </div>
                `;
                container.appendChild(card);
            });
        }

        async function decideVip(requestId, action) {
            try {
                const res = await fetch('/api/admin/vip-requests/decide', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ request_id: requestId, action })
                });
                if (res.ok) {
                    showToast(action === 'approve' ? 'Запрос одобрен, статус выдан!' : 'Запрос отклонен');
                    loadAdminVipRequests();
                }
            } catch(e) {}
        }

        async function loadAdminTickets() {
            const container = document.getElementById('admin-tickets-list');
            try {
                const res = await fetch('/api/admin/tickets');
                const data = await res.json();
                container.innerHTML = '';
                if (data.tickets.length === 0) {
                    container.innerHTML = '<div style="text-align:center; color:var(--text-muted); padding:20px;">Нет тикетов.</div>';
                    return;
                }
                data.tickets.forEach(t => {
                    const card = document.createElement('div');
                    card.className = 'ticket-card';
                    card.innerHTML = `
                        <div class="ticket-header">
                            <span><b>Тикет #${t.id}</b> | ${escapeHtml(t.user_email)}</span>
                            <span class="status-badge badge-${t.status}">${t.status}</span>
                        </div>
                        <div class="ticket-msg">${escapeHtml(t.message)}</div>
                    `;
                    container.appendChild(card);
                });
            } catch (e) {}
        }

        function toggleUserSupportModal(show) {
            const modal = document.getElementById('user-support-modal');
            if (show) {
                if (!windowCurrentUserEmail) {
                    alert('Войдите через Google.');
                    return;
                }
                modal.classList.add('active');
                loadMyTickets();
            } else {
                modal.classList.remove('active');
            }
        }

        async function loadMyTickets() {
            const container = document.getElementById('user-tickets-list');
            if (!container) return;
            try {
                const res = await fetch('/api/tickets/my');
                const data = await res.json();
                if (data.tickets.length === 0) {
                    container.innerHTML = '<span style="color:var(--text-muted); font-size:11.5px;">Нет обращений.</span>';
                    return;
                }
                container.innerHTML = '';
                data.tickets.forEach(t => {
                    const item = document.createElement('div');
                    item.className = 'ticket-card';
                    item.innerHTML = `
                        <div class="ticket-header"><span>Тикет #${t.id}</span><span class="status-badge badge-${t.status}">${t.status}</span></div>
                        <div class="ticket-msg">${escapeHtml(t.message)}</div>
                    `;
                    container.appendChild(item);
                });
            } catch(e) {}
        }

        async function submitUserTicket(e) {
            e.preventDefault();
            const input = document.getElementById('user-ticket-input');
            const message = input.value.trim();
            if (!message) return;
            try {
                const res = await fetch('/api/tickets/create', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message })
                });
                if (res.ok) {
                    input.value = '';
                    loadMyTickets();
                    showToast('Тикет отправлен!');
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
                alert('Достигнут лимит в 5 активных диалогов.');
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
                    setTimeout(() => btn.textContent = 'Копировать', 1500);
                };
                pre.appendChild(btn);
            });
        }

        function renderMessages(messages) {
            const chatContainer = document.getElementById('chat-container');
            chatContainer.innerHTML = '';

            if (messages.length === 0) {
                const welcome = document.createElement('div');
                welcome.className = 'welcome-minimal';
                welcome.innerHTML = `
                    <h1>Rubinov AI Studio</h1>
                    <p>Задайте любой вопрос, пишите код, создавайте арты или анализируйте изображения с помощью передовых моделей Gemini.</p>
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
                btn.textContent = 'Стоп';
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
                activeChat.name = text.length > 22 ? text.substring(0, 22) + '...' : text;
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
                    throw new Error(errData.detail || 'Не удалось получить ответ.');
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
                    activeChat.messages.push({ role: 'bot', text: '*Генерация остановлена.*' });
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
                    <span>Rubinov AI думает...</span>
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

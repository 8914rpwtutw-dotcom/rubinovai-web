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
from google.genai.errors import APIError
import httpx

app = FastAPI()

# Поддержка HTTPS заголовков прокси Render
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

# Единственный СУПЕР-АДМИНИСТРАТОР (главный владельц)
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
        
        # Таблица тикетов поддержки
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

        # Таблица переписки в тикетах (мини-чат поддержки)
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
        
        # Гарантируем статус главного супер-админа
        cursor.execute("""
            INSERT INTO users (email, status) 
            VALUES (%s, 'admin') 
            ON CONFLICT (email) DO UPDATE SET status = 'admin'
        """, (SUPER_ADMIN,))
        
        # Заносим остальных начальных админов, если их еще нет в базе
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
    
    # Супер-админ всегда имеет роль admin
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

# Актуальная линейка моделей Google Gemini
MODELS = ["gemini-3.1-flash-lite", "gemini-2.5-flash"]
current_key_idx = 0
current_model_idx = 0

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")

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

def get_gemini_response(prompt: str, file_bytes: Optional[bytes] = None, mime_type: Optional[str] = None) -> str:
    global current_key_idx, current_model_idx
    
    lowered = prompt.lower()
    if "нарисуй" in lowered or "draw" in lowered or "сгенерируй" in lowered:
        clean_prompt = prompt.replace("Нарисуй:", "").replace("нарисуй", "").replace("сгенерируй", "").strip()
        if not clean_prompt:
            clean_prompt = "beautiful futuristic neon cyberpunk landscape"
        
        import urllib.parse
        encoded_prompt = urllib.parse.quote(clean_prompt)
        img_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true"
        
        return f"""Вот ваше сгенерированное изображение по запросу: *"{clean_prompt}"*

<div style="margin-top:14px;">
    <img src="{img_url}" alt="{clean_prompt}" style="max-width:100%; border-radius:16px; display:block; margin-bottom:12px; box-shadow: 0 12px 40px rgba(99, 102, 241, 0.2); border: 1px solid rgba(255,255,255,0.08);" />
    <a href="{img_url}" target="_blank" download="rubinov_ai.jpg" style="display:inline-flex; align-items: center; gap: 8px; background: linear-gradient(135deg, #6366f1, #a855f7); color:#fff; padding:9px 18px; border-radius:12px; font-size:12px; text-decoration:none; font-weight:600; box-shadow: 0 4px 20px rgba(99, 102, 241, 0.35); transition: all 0.2s ease;">📥 Скачать в высоком разрешении</a>
</div>"""

    api_keys = get_api_keys()
    if not api_keys:
        print("ОШИБКА: Ни один API-ключ Gemini не найден в Environment Variables!")
        raise HTTPException(status_code=500, detail="API-ключи Gemini не найдены в переменные окружения Render.")

    num_keys = len(api_keys)
    num_models = len(MODELS)
    total_attempts = num_keys * num_models * 2

    contents = []
    if file_bytes and mime_type:
        contents.append(types.Part.from_bytes(data=file_bytes, mime_type=mime_type))
    if prompt:
        contents.append(prompt)

    last_error = "Неизвестная ошибка"

    for attempt in range(total_attempts):
        active_key = api_keys[current_key_idx % num_keys]
        active_model = MODELS[current_model_idx % num_models]

        try:
            client = get_gemini_client(active_key)
            response = client.models.generate_content(
                model=active_model,
                contents=contents
            )
            if response and response.text:
                return response.text
        except Exception as err:
            last_error = str(err)
            print(f"Ошибка вызова Gemini API (Модель: {active_model}, Ключ №{current_key_idx % num_keys + 1}): {err}")
            current_model_idx += 1
            if current_model_idx >= num_models:
                current_model_idx = 0
                current_key_idx = (current_key_idx + 1) % num_keys
            time.sleep(0.3)
            continue

    raise HTTPException(status_code=500, detail=f"Ошибка генерации ИИ: {last_error}")

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
    return {"status": status, "email": user_email}

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
        raise HTTPException(status_code=400, detail="Недопустимый статус для назначения.")
    
    if target_email == SUPER_ADMIN:
        raise HTTPException(status_code=400, detail="Нельзя изменить статус Главного администратора!")

    if not is_super_admin:
        target_status = get_user_status(target_email)
        if target_status == "admin":
            raise HTTPException(status_code=403, detail="Обычный админ не может менять статус других админов.")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET status = %s WHERE email = %s", (new_status, target_email))
    conn.commit()
    cursor.close()
    conn.close()
    
    return {"success": True}

# --- API ПОДДЕРЖКИ (МИНИ-ЧАТ ТИКЕТОВ) ---

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
    
    # Добавляем первое сообщение в переписку мини-чата
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
    
    # Проверяем принадлежность тикета
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

        answer = get_gemini_response(prompt, file_bytes, mime_type)
        json_resp = JSONResponse(content={"response": answer})

        if not user_email:
            guest_count = int(request.cookies.get("guest_requests", "0"))
            json_resp.set_cookie(key="guest_requests", value=str(guest_count + 1), httponly=False)

        return json_resp

    except HTTPException:
        raise
    except Exception as exc:
        print("--- EXCEPTION IN /api/chat ---")
        traceback.print_exc()
        print("------------------------------")
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера: {exc}")

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
            --bg-main: #040508;
            --bg-sidebar: rgba(10, 12, 18, 0.85);
            --card-bg: rgba(18, 21, 31, 0.5);
            --border-color: rgba(255, 255, 255, 0.08);
            --border-hover: rgba(168, 85, 247, 0.25);
            --accent-gradient: linear-gradient(135deg, #6366f1 0%, #a855f7 100%);
            --accent-glow: rgba(168, 85, 247, 0.15);
            --cancel-bg: rgba(248, 113, 113, 0.1);
            --cancel-border: rgba(248, 113, 113, 0.3);
            --cancel-color: #f87171;
            --text-main: #f1f5f9;
            --text-muted: #94a3b8;
            --user-msg-bg: linear-gradient(135deg, rgba(99, 102, 241, 0.16) 0%, rgba(168, 85, 247, 0.14) 100%);
            --bot-msg-bg: rgba(15, 18, 26, 0.65);
            --scrollbar-thumb: rgba(255, 255, 255, 0.12);
        }

        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', -apple-system, sans-serif; -webkit-tap-highlight-color: transparent; }
        html, body { height: 100%; height: 100dvh; overflow: hidden; background: var(--bg-main); color: var(--text-main); }
        body { display: flex; position: relative; }

        body::before {
            content: ''; position: fixed; top: -15vh; left: -15vw; width: 55vw; height: 55vh;
            background: radial-gradient(circle, rgba(99, 102, 241, 0.07) 0%, rgba(168, 85, 247, 0.02) 60%, transparent 80%);
            z-index: 0; pointer-events: none; filter: blur(80px);
        }
        body::after {
            content: ''; position: fixed; bottom: -15vh; right: -15vw; width: 55vw; height: 55vh;
            background: radial-gradient(circle, rgba(168, 85, 247, 0.06) 0%, rgba(236, 72, 153, 0.01) 60%, transparent 80%);
            z-index: 0; pointer-events: none; filter: blur(80px);
        }

        ::-webkit-scrollbar { width: 5px; height: 5px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: var(--scrollbar-thumb); border-radius: 20px; }

        #sidebar-overlay {
            display: none; position: fixed; top: 0; left: 0; width: 100vw; height: 100dvh;
            background: rgba(4, 5, 8, 0.7); backdrop-filter: blur(6px); z-index: 40; opacity: 0; transition: opacity 0.3s ease;
        }
        #sidebar-overlay.active { display: block; opacity: 1; }

        #sidebar { 
            width: 280px; min-width: 280px; background: var(--bg-sidebar); backdrop-filter: blur(24px);
            -webkit-backdrop-filter: blur(24px); border-right: 1px solid var(--border-color); 
            display: flex; flex-direction: column; padding: 20px 14px; z-index: 50; height: 100dvh;
            transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1), margin-left 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            box-shadow: 15px 0 40px rgba(0, 0, 0, 0.4);
        }
        body.sidebar-collapsed #sidebar { margin-left: -280px; }

        .brand { display: flex; align-items: center; gap: 12px; margin-bottom: 22px; padding: 0 4px; }
        .brand-logo-svg { width: 32px; height: 32px; filter: drop-shadow(0 0 12px rgba(168, 85, 247, 0.5)); flex-shrink: 0; }
        .brand h2 { font-size: 15px; font-weight: 700; color: #ffffff; letter-spacing: -0.3px; }
        .brand span { font-size: 10px; color: var(--text-muted); font-weight: 500; display: block; }

        .btn-new-chat { 
            background: var(--accent-gradient); color: #ffffff; border: none; padding: 11px 16px; 
            border-radius: 14px; font-size: 12px; font-weight: 600; cursor: pointer; 
            display: flex; align-items: center; gap: 9px; margin-bottom: 12px; 
            transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1); box-shadow: 0 4px 20px rgba(99, 102, 241, 0.3);
        }
        .btn-new-chat:hover { transform: translateY(-1px); box-shadow: 0 6px 25px rgba(168, 85, 247, 0.45); }

        .btn-support-chat {
            background: rgba(255, 255, 255, 0.03); border: 1px solid var(--border-color); color: #e2e8f0;
            padding: 9px 14px; border-radius: 12px; font-size: 11.5px; font-weight: 600; cursor: pointer;
            display: flex; align-items: center; gap: 8px; margin-bottom: 18px; transition: all 0.2s;
        }
        .btn-support-chat:hover { background: rgba(168, 85, 247, 0.15); border-color: rgba(168, 85, 247, 0.3); }

        .chats-header { display: flex; justify-content: space-between; font-size: 10px; color: var(--text-muted); font-weight: 700; margin-bottom: 8px; padding: 0 4px; text-transform: uppercase; letter-spacing: 0.8px; }
        
        #chats-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; padding-right: 2px; }
        .chat-item { 
            background: rgba(255, 255, 255, 0.015); border: 1px solid var(--border-color); 
            border-radius: 12px; padding: 10px 12px; font-size: 12px; color: #cbd5e1; 
            display: flex; justify-content: space-between; align-items: center; cursor: pointer; transition: all 0.2s ease;
        }
        .chat-item.active { 
            background: rgba(168, 85, 247, 0.1); border-color: rgba(168, 85, 247, 0.35); 
            color: #ffffff; box-shadow: 0 0 20px rgba(168, 85, 247, 0.08); 
        }
        .chat-item:hover { background: rgba(255, 255, 255, 0.04); border-color: var(--border-hover); color: #ffffff; }
        .chat-item .close-btn { color: var(--text-muted); font-size: 14px; cursor: pointer; border-radius: 6px; width: 22px; height: 22px; display: flex; align-items: center; justify-content: center; }
        .chat-item .close-btn:hover { color: #f87171; background: rgba(248, 113, 113, 0.15); }

        .sidebar-footer { font-size: 11px; color: var(--text-muted); display: flex; flex-direction: column; gap: 8px; margin-top: auto; padding-top: 14px; border-top: 1px solid var(--border-color); }
        .footer-info { display: flex; align-items: center; justify-content: space-between; width: 100%; }
        .status-dot { width: 7px; height: 7px; background: #a855f7; border-radius: 50%; box-shadow: 0 0 10px rgba(168, 85, 247, 0.8); }

        .btn-google-login {
            background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1);
            color: #ffffff; padding: 8px 12px; border-radius: 10px; font-size: 11.5px; font-weight: 600;
            text-decoration: none; display: flex; align-items: center; justify-content: center; gap: 8px; transition: all 0.2s ease;
        }
        .btn-google-login:hover { background: rgba(255, 255, 255, 0.1); border-color: rgba(168, 85, 247, 0.4); }

        .btn-admin-panel {
            background: rgba(168, 85, 247, 0.15); border: 1px solid rgba(168, 85, 247, 0.4);
            color: #d8b4fe; padding: 8px 12px; border-radius: 10px; font-size: 11.5px; font-weight: 600;
            cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 6px; transition: all 0.2s ease;
            width: 100%; margin-bottom: 4px;
        }
        .btn-admin-panel:hover { background: rgba(168, 85, 247, 0.25); color: #fff; }

        .btn-ticket-action {
            background: rgba(255, 255, 255, 0.05); border: 1px solid var(--border-color); color: #fff;
            padding: 6px 12px; border-radius: 8px; font-size: 11px; cursor: pointer; transition: all 0.2s;
        }
        .btn-ticket-action:hover { background: rgba(255, 255, 255, 0.1); }
        .btn-close-ticket { background: rgba(248, 113, 113, 0.15); border-color: rgba(248, 113, 113, 0.3); color: #f87171; }
        .btn-close-ticket:hover { background: rgba(248, 113, 113, 0.3); }

        .status-badge { padding: 2px 6px; border-radius: 6px; font-size: 9.5px; font-weight: 700; text-transform: uppercase; display: inline-block; margin-left: 4px; }
        .badge-vip { background: rgba(168, 85, 247, 0.25); color: #e9d5ff; border: 1px solid rgba(168,85,247,0.4); }
        .badge-free { background: rgba(148, 163, 184, 0.15); color: #cbd5e1; border: 1px solid rgba(148, 163, 184, 0.2); }
        .badge-admin { background: rgba(234, 179, 8, 0.25); color: #fde047; border: 1px solid rgba(234,179,8,0.4); }

        #banned-overlay {
            display: none; position: fixed; top: 0; left: 0; width: 100vw; height: 100dvh;
            background: rgba(4, 5, 8, 0.95); backdrop-filter: blur(12px); z-index: 999;
            align-items: center; justify-content: center; padding: 20px; text-align: center;
        }
        #banned-overlay.active { display: flex; }
        .banned-box {
            background: #11141d; border: 1px solid rgba(248, 113, 113, 0.4);
            padding: 30px 24px; border-radius: 24px; max-width: 400px; width: 100%;
            box-shadow: 0 20px 60px rgba(248, 113, 113, 0.2);
        }
        .banned-box h2 { color: #f87171; font-size: 20px; margin-bottom: 12px; }
        .banned-box p { color: var(--text-muted); font-size: 13.5px; line-height: 1.5; margin-bottom: 20px; }

        /* ОКНО АДМИН ПАНЕЛИ И ПОДДЕРЖКИ */
        #admin-modal, #user-support-modal {
            display: none; position: fixed; top: 0; left: 0; width: 100vw; height: 100dvh;
            background: rgba(4, 5, 8, 0.85); backdrop-filter: blur(8px); z-index: 100;
            align-items: center; justify-content: center; padding: 10px;
        }
        #admin-modal.active, #user-support-modal.active { display: flex; }
        .admin-box {
            background: #0d1018; border: 1px solid rgba(168, 85, 247, 0.3); border-radius: 20px;
            width: 100%; max-width: 800px; height: 85dvh; display: flex; flex-direction: column; overflow: hidden;
            box-shadow: 0 20px 50px rgba(0,0,0,0.8);
        }
        .admin-header {
            padding: 14px 18px; border-bottom: 1px solid var(--border-color);
            display: flex; justify-content: space-between; align-items: center; background: rgba(18, 21, 31, 0.8);
        }
        .admin-header h3 { font-size: 14px; color: #fff; font-weight: 700; }
        .admin-close { background: none; border: none; color: var(--text-muted); font-size: 20px; cursor: pointer; }
        .admin-close:hover { color: #f87171; }
        
        .admin-nav-tabs {
            display: flex; gap: 8px; padding: 10px 14px; background: rgba(13, 16, 24, 0.95);
            border-bottom: 1px solid var(--border-color);
        }
        .tab-btn {
            background: rgba(255, 255, 255, 0.03); border: 1px solid var(--border-color); color: var(--text-muted);
            padding: 6px 14px; border-radius: 10px; font-size: 11.5px; font-weight: 600; cursor: pointer; transition: all 0.2s;
        }
        .tab-btn.active { background: var(--accent-gradient); color: #fff; border-color: transparent; }

        .admin-filters {
            padding: 10px 14px; display: flex; gap: 6px; background: rgba(13, 16, 24, 0.7);
            border-bottom: 1px solid var(--border-color); flex-wrap: wrap;
        }
        .filter-btn {
            background: rgba(255, 255, 255, 0.03); border: 1px solid var(--border-color); color: var(--text-muted);
            padding: 5px 10px; border-radius: 8px; font-size: 11px; font-weight: 600; cursor: pointer; transition: all 0.2s;
        }
        .filter-btn.active { background: rgba(168, 85, 247, 0.2); border-color: rgba(168, 85, 247, 0.4); color: #fff; }

        .admin-content { padding: 14px; overflow-y: auto; flex: 1; }
        .admin-table { width: 100%; border-collapse: collapse; font-size: 11.5px; }
        .admin-table th, .admin-table td { padding: 8px 10px; text-align: left; border-bottom: 1px solid var(--border-color); color: #f1f5f9; }
        .admin-table th { color: var(--text-muted); font-weight: 600; background: rgba(255,255,255,0.02); }
        
        .badge { padding: 3px 8px; border-radius: 6px; font-size: 10px; font-weight: 700; text-transform: uppercase; display: inline-block; }
        .badge-free { background: rgba(148, 163, 184, 0.15); color: #cbd5e1; }
        .badge-vip { background: rgba(168, 85, 247, 0.25); color: #e9d5ff; }
        .badge-banned { background: rgba(248, 113, 113, 0.25); color: #fca5a5; }
        .badge-admin { background: rgba(234, 179, 8, 0.25); color: #fde047; }
        .badge-open { background: rgba(59, 130, 246, 0.2); color: #93c5fd; border: 1px solid rgba(59, 130, 246, 0.4); }
        .badge-replied { background: rgba(168, 85, 247, 0.2); color: #d8b4fe; border: 1px solid rgba(168, 85, 247, 0.4); }
        .badge-closed { background: rgba(100, 116, 139, 0.2); color: #cbd5e1; }

        .admin-actions-cell { display: flex; gap: 6px; align-items: center; }
        .admin-actions-cell select {
            background: #1a1f2c; border: 1px solid rgba(168, 85, 247, 0.3); color: #ffffff;
            padding: 4px 6px; border-radius: 6px; font-size: 11px; outline: none; cursor: pointer;
        }

        /* ТИКЕТЫ КАРТОЧКИ И МИНИ-ЧАТ ПОДДЕРЖКИ */
        .ticket-card {
            background: rgba(255, 255, 255, 0.02); border: 1px solid var(--border-color);
            border-radius: 12px; padding: 12px 14px; margin-bottom: 10px; display: flex; flex-direction: column; gap: 8px; cursor: pointer; transition: all 0.2s;
        }
        .ticket-card:hover { border-color: rgba(168, 85, 247, 0.3); background: rgba(255,255,255,0.03); }
        .ticket-header { display: flex; justify-content: space-between; align-items: center; font-size: 11px; color: var(--text-muted); }
        .ticket-msg { font-size: 12.5px; color: #f1f5f9; line-height: 1.4; background: rgba(0,0,0,0.2); padding: 8px 10px; border-radius: 8px; }

        .ticket-chat-container {
            display: flex; flex-direction: column; height: 100%; gap: 10px;
        }
        .ticket-chat-messages {
            flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; padding: 10px;
            background: rgba(0,0,0,0.2); border-radius: 12px; border: 1px solid var(--border-color);
        }
        .t-msg-bubble {
            max-width: 80%; padding: 8px 12px; border-radius: 12px; font-size: 12px; line-height: 1.4; word-break: break-word;
        }
        .t-msg-user {
            align-self: flex-end; background: rgba(99, 102, 241, 0.2); border: 1px solid rgba(99, 102, 241, 0.3); color: #fff; border-bottom-right-radius: 2px;
        }
        .t-msg-admin {
            align-self: flex-start; background: rgba(168, 85, 247, 0.2); border: 1px solid rgba(168, 85, 247, 0.3); color: #fff; border-bottom-left-radius: 2px;
        }
        .t-msg-meta { font-size: 9px; opacity: 0.6; margin-bottom: 3px; display: block; }

        .ticket-chat-input-row {
            display: flex; gap: 8px; align-items: center;
        }
        .ticket-chat-input-row input {
            flex: 1; background: rgba(0,0,0,0.4); border: 1px solid var(--border-color); color: #fff;
            padding: 9px 12px; border-radius: 10px; font-size: 12px; outline: none;
        }
        .ticket-chat-input-row input:focus { border-color: rgba(168, 85, 247, 0.5); }

        #main { flex: 1; display: flex; flex-direction: column; background: var(--bg-main); position: relative; height: 100dvh; overflow: hidden; z-index: 1; }
        
        #chat-header { 
            height: 60px; min-height: 60px; border-bottom: 1px solid var(--border-color); 
            display: flex; align-items: center; justify-content: space-between; 
            padding: 0 20px; background: rgba(4, 5, 8, 0.5); backdrop-filter: blur(16px); z-index: 10;
        }
        .header-left { display: flex; align-items: center; gap: 12px; }
        .menu-toggle { 
            background: rgba(255, 255, 255, 0.02); border: 1px solid var(--border-color); 
            color: #ffffff; border-radius: 12px; padding: 8px; cursor: pointer; display: flex; align-items: center; justify-content: center;
        }
        #chat-header h3 { font-size: 14px; font-weight: 600; color: #ffffff; }

        #chat-container { 
            flex: 1; overflow-y: auto; padding: 20px 20px 140px 20px; 
            display: flex; flex-direction: column; gap: 20px; max-width: 900px; width: 100%; margin: 0 auto; position: relative; z-index: 2;
        }

        .welcome-screen {
            position: absolute; top: 45%; left: 50%; transform: translate(-50%, -50%);
            text-align: center; user-select: none; pointer-events: none; width: 90%; max-width: 480px;
            display: flex; flex-direction: column; align-items: center; gap: 16px;
        }
        .welcome-avatar-glow {
            padding: 20px; border-radius: 28px; background: rgba(168, 85, 247, 0.04);
            border: 1px solid rgba(168, 85, 247, 0.15); box-shadow: 0 0 50px rgba(168, 85, 247, 0.12);
        }
        .welcome-avatar-svg { width: 60px; height: 60px; filter: drop-shadow(0 0 18px rgba(168, 85, 247, 0.6)); }
        .welcome-screen h1 { font-size: 22px; font-weight: 700; color: #ffffff; }
        .welcome-screen p { font-size: 13px; color: var(--text-muted); line-height: 1.5; }
        
        .msg-row { display: flex; flex-direction: column; width: 100%; z-index: 2; }
        .msg-row.user-row { align-items: flex-end; }
        .msg-row.bot-row { align-items: flex-start; }

        .msg-user { 
            background: var(--user-msg-bg); color: #ffffff; border: 1px solid rgba(168, 85, 247, 0.22); 
            border-radius: 18px 18px 4px 18px; padding: 12px 16px; font-size: 13px; line-height: 1.5; max-width: 85%; word-break: break-word; 
        }
        .msg-bot { 
            background: var(--bot-msg-bg); border: 1px solid var(--border-color); color: #e2e8f0; 
            border-radius: 18px 18px 18px 4px; padding: 16px 20px; font-size: 13px; line-height: 1.6; max-width: 90%; word-break: break-word; 
        }
        .msg-bot code { background: rgba(255, 255, 255, 0.06); padding: 2px 6px; border-radius: 6px; font-family: monospace; font-size: 11.5px; color: #f472b6; }
        .msg-bot pre { background: #020305; padding: 12px; border-radius: 10px; overflow-x: auto; margin: 10px 0; border: 1px solid var(--border-color); }
        
        .file-preview-tag { display: inline-flex; align-items: center; gap: 6px; background: rgba(168, 85, 247, 0.15); padding: 4px 8px; border-radius: 8px; font-size: 11px; margin-bottom: 6px; color: #d8b4fe; }

        .loader-box {
            display: flex; align-items: center; gap: 12px; background: var(--bot-msg-bg);
            border: 1px solid var(--border-color); border-radius: 18px 18px 18px 4px; padding: 12px 18px; font-size: 13px; color: var(--text-muted);
        }
        .spinner {
            width: 14px; height: 14px; border: 2px solid rgba(168,85,247,0.2);
            border-top-color: #a855f7; border-radius: 50%; animation: spin 0.8s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }

        #input-wrapper {
            position: absolute; bottom: 0; left: 0; right: 0; 
            padding: 14px 20px; padding-bottom: calc(14px + env(safe-area-inset-bottom));
            background: linear-gradient(180deg, rgba(4, 5, 8, 0) 0%, rgba(4, 5, 8, 0.85) 40%, var(--bg-main) 100%);
            z-index: 20;
        }
        #input-container { 
            max-width: 900px; margin: 0 auto; background: rgba(13, 16, 24, 0.85); 
            backdrop-filter: blur(24px); border: 1px solid rgba(168, 85, 247, 0.18); border-radius: 18px; 
            padding: 6px 10px; display: flex; flex-direction: column; gap: 6px; box-shadow: 0 10px 30px rgba(0, 0, 0, 0.6);
        }
        #file-info-bar { display: none; align-items: center; justify-content: space-between; background: rgba(168, 85, 247, 0.12); padding: 5px 10px; border-radius: 8px; font-size: 11px; color: #d8b4fe; }
        #file-info-bar button { background: none; border: none; color: #f87171; cursor: pointer; font-size: 13px; }

        .input-row { display: flex; gap: 6px; align-items: center; width: 100%; }
        .mini-btn { 
            background: rgba(255, 255, 255, 0.02); border: 1px solid var(--border-color); color: var(--text-muted); 
            padding: 8px; border-radius: 10px; cursor: pointer; display: flex; align-items: center; justify-content: center; 
        }
        #prompt-input { flex: 1; background: transparent; border: none; color: #ffffff; font-size: 13.5px; outline: none; min-width: 0; padding: 4px; }
        #prompt-input::placeholder { color: var(--text-muted); }
        
        .btn-action { 
            background: var(--accent-gradient); color: #ffffff; border: none; border-radius: 10px; 
            padding: 10px 16px; font-size: 12px; font-weight: 600; cursor: pointer; flex-shrink: 0; display: flex; align-items: center; justify-content: center; min-width: 90px;
        }
        .btn-action.cancel-mode { background: var(--cancel-bg); border: 1px solid var(--cancel-border); color: var(--cancel-color); }

        @media (max-width: 768px) {
            #sidebar { position: fixed; top: 0; left: 0; margin-left: 0 !important; transform: translateX(-100%); }
            #sidebar.mobile-open { transform: translateX(0); }
            #chat-header { padding: 0 14px; }
            #chat-container { padding: 14px 14px 110px 14px; }
            #input-wrapper { padding: 10px 14px; }
            .admin-box { max-height: 95dvh; margin: 5px; }
        }
    </style>
</head>
<body>
    <div id="sidebar-overlay" onclick="toggleSidebar()"></div>

    <div id="banned-overlay">
        <div class="banned-box">
            <h2>🚫 Аккаунт заблокирован</h2>
            <p>Ваш аккаунт был заблокирован администратором. Доступ к нейросети приостановлен.</p>
            <a href="/auth/logout" style="background: rgba(248,113,113,0.2); border: 1px solid rgba(248,113,113,0.4); color: #f87171; padding: 8px 16px; border-radius: 10px; font-size: 12px; text-decoration: none; font-weight: 600; display: inline-block;">Выйти из аккаунта</a>
        </div>
    </div>

    <!-- МОДАЛЬНОЕ ОКНО ПОДДЕРЖКИ ДЛЯ ПОЛЬЗОВАТЕЛЯ -->
    <div id="user-support-modal" onclick="if(event.target.id==='user-support-modal') toggleUserSupportModal(false)">
        <div class="admin-box" style="max-width:550px;" onclick="event.stopPropagation()">
            <div class="admin-header">
                <h3 id="user-support-title">💬 Служба поддержки Rubinov AI</h3>
                <button type="button" class="admin-close" onclick="toggleUserSupportModal(false)">×</button>
            </div>
            <div class="admin-content" id="user-support-content">
                <form onsubmit="submitUserTicket(event)" style="margin-bottom: 14px;">
                    <label style="font-size: 11.5px; color: var(--text-muted); display: block; margin-bottom: 6px;">Опишите вашу проблему или вопрос:</label>
                    <textarea id="user-ticket-input" style="width: 100%; background: rgba(0,0,0,0.4); border: 1px solid var(--border-color); color: #fff; padding: 10px; border-radius: 10px; font-size: 12px; outline: none; resize: vertical; min-height: 70px;" placeholder="Здравствуйте, у меня возник вопрос по..."></textarea>
                    <button type="submit" class="btn-action" style="margin-top: 8px; width: 100%;">Создать тикет</button>
                </form>
                <hr style="border: none; border-top: 1px solid var(--border-color); margin: 14px 0;">
                <h4 style="font-size: 12px; color: #fff; margin-bottom: 10px;">Ваши обращения:</h4>
                <div id="user-tickets-list">Загрузка...</div>
            </div>
        </div>
    </div>

    <!-- МОДАЛЬНОЕ ОКНО АДМИН ПАНЕЛИ -->
    <div id="admin-modal" onclick="closeAdminModal(event)">
        <div class="admin-box" onclick="event.stopPropagation()">
            <div class="admin-header">
                <h3>👑 Панель администратора</h3>
                <button type="button" class="admin-close" onclick="toggleAdminModal(false)">×</button>
            </div>
            
            <div class="admin-nav-tabs">
                <button type="button" class="tab-btn active" id="tab-users-btn" onclick="switchAdminTab('users')">👥 Пользователи</button>
                <button type="button" class="tab-btn" id="tab-tickets-btn" onclick="switchAdminTab('tickets')">💬 ПОДДЕРЖКА (Тикеты)</button>
            </div>

            <!-- Вкладка ПОЛЬЗОВАТЕЛИ -->
            <div id="admin-tab-users" style="display: flex; flex-direction: column; flex: 1; overflow: hidden;">
                <div class="admin-filters">
                    <button type="button" class="filter-btn active" onclick="filterAdminUsers('all', this)">Все</button>
                    <button type="button" class="filter-btn" onclick="filterAdminUsers('admin', this)">👑 Админы</button>
                    <button type="button" class="filter-btn" onclick="filterAdminUsers('vip', this)">⚡ VIP</button>
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
                                <th>Действие</th>
                            </tr>
                        </thead>
                        <tbody id="admin-users-list">
                            <tr><td colspan="4" style="text-align:center; color:var(--text-muted);">Загрузка...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Вкладка ПОДДЕРЖКА (ТИКЕТЫ) -->
            <div id="admin-tab-tickets" style="display: none; flex-direction: column; flex: 1; overflow: hidden;">
                <div class="admin-filters">
                    <button type="button" class="filter-btn active" onclick="filterAdminTickets('open', this)">🔵 Актуальные тикеты</button>
                    <button type="button" class="filter-btn" onclick="filterAdminTickets('all', this)">📋 Все обращения</button>
                </div>
                <div class="admin-content" id="admin-tickets-list">
                    Загрузка тикетов...
                </div>
            </div>

        </div>
    </div>

    <div id="sidebar">
        <div class="brand">
            <svg class="brand-logo-svg" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
                <defs><linearGradient id="rubyGrad" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#ff4b4b" /><stop offset="100%" stop-color="#900c3f" /></linearGradient></defs>
                <path d="M50 10 L85 35 L50 90 L15 35 Z" stroke="url(#rubyGrad)" stroke-width="4" fill="none" />
                <path d="M15 35 L85 35 M50 10 L32 35 M50 10 L68 35 M50 90 L32 35 M50 90 L68 35" stroke="url(#rubyGrad)" stroke-width="2.5" opacity="0.7" />
                <circle cx="50" cy="48" r="14" fill="#ff4b4b" opacity="0.25" />
                <path d="M42 45 Q46 40 50 45 Q54 40 58 45 Q60 52 50 56 Q40 52 42 45 Z" stroke="#ffffff" stroke-width="2.5" fill="none" />
            </svg>
            <div><h2>Rubinov AI</h2><span>Assistant</span></div>
        </div>

        <button type="button" class="btn-new-chat" onclick="createNewChat()">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 5v14M5 12h14"/></svg>
            Новый диалог
        </button>

        <button type="button" class="btn-support-chat" onclick="toggleUserSupportModal(true)">
            💬 Написать в поддержку
        </button>

        <div class="chats-header"><span>Чаты (<span id="chat-count">1</span>/5)</span></div>
        <div id="chats-list"></div>

        <div class="sidebar-footer">
            USER_AUTH_BLOCK
            <div class="footer-info"><div style="display:flex; align-items:center; gap:8px;"><span class="status-dot"></span><span>Online</span></div></div>
        </div>
    </div>

    <div id="main">
        <div id="chat-header">
            <div class="header-left">
                <button type="button" class="menu-toggle" onclick="toggleSidebar()" title="Меню">
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
                    <button type="button" onclick="removeSelectedFile()">✕</button>
                </div>
                <div class="input-row">
                    <input type="file" id="file-input" accept="image/*" capture="environment" style="display: none;" onchange="handleFileSelect(event)" />
                    <button type="button" class="mini-btn" onclick="checkFilePermissionAndOpen()" title="Прикрепить фото">
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
                    </button>
                    <button type="button" class="mini-btn" onclick="triggerImageGenerationPrompt()" title="Сгенерировать картинку">
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
                    </button>
                    <input type="text" id="prompt-input" placeholder="Введите сообщение..." onkeydown="handleKeyPress(event)" />
                    <button type="button" class="btn-action" id="action-btn" onclick="handleActionButton()">Отправить</button>
                </div>
            </div>
        </div>
    </div>

    <script>
        let chats = JSON.parse(localStorage.getItem('rubinov_chats_main_v1') || '[]');
        let currentChatId = localStorage.getItem('rubinov_active_chat_main_v1') || null;
        let selectedFile = null;
        let activeController = null;
        let isGenerating = false;
        let allUsersCache = [];
        let allTicketsCache = [];
        let currentFilter = 'all';
        let currentTicketFilter = 'open';
        let myCurrentStatus = 'guest';
        let windowCurrentUserEmail = '';

        let activeTicketId = null; // Текущий выбранный тикет в мини-чате

        const SUPER_ADMIN_EMAIL = "8914rpwtutw@gmail.com".toLowerCase();

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
                }
            } catch(e) {}
        }
        setInterval(checkUserStatusRealtime, 8000);
        checkUserStatusRealtime();

        // Обновление тикетов и мини-чата поддержки без перезагрузки в реальном времени (каждые 3 секунды)
        setInterval(() => {
            const supportModal = document.getElementById('user-support-modal');
            if (supportModal && supportModal.classList.contains('active')) {
                if (activeTicketId) {
                    loadTicketChatMessages(activeTicketId);
                } else {
                    loadMyTickets();
                }
            }
            const adminModal = document.getElementById('admin-modal');
            if (adminModal && adminModal.classList.contains('active')) {
                const ticketsTab = document.getElementById('admin-tab-tickets');
                if (ticketsTab && ticketsTab.style.display !== 'none') {
                    if (activeTicketId) {
                        loadTicketChatMessages(activeTicketId);
                    } else {
                        loadAdminTickets();
                    }
                }
            }
        }, 3000);

        if (chats.length === 0) {
            const initialChat = { id: Date.now().toString(), name: 'Новый чат 1', messages: [] };
            chats.push(initialChat);
            currentChatId = initialChat.id;
            saveState();
        } else if (!currentChatId || !chats.find(c => c.id === currentChatId)) {
            currentChatId = chats[0].id;
        }

        function saveState() {
            localStorage.setItem('rubinov_chats_main_v1', JSON.stringify(chats));
            localStorage.setItem('rubinov_active_chat_main_v1', currentChatId);
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

        function closeAdminModal(e) {
            if (e.target.id === 'admin-modal') toggleAdminModal(false);
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
                tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:#f87171;">Ошибка загрузки.</td></tr>';
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

            const filtered = allUsersCache.filter(u => {
                if (currentFilter === 'admin') return u.status === 'admin';
                if (currentFilter === 'vip') return u.status === 'vip';
                if (currentFilter === 'free') return u.status === 'free';
                if (currentFilter === 'banned') return u.status === 'banned';
                return true;
            });

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
                } 
                else if (u.status === 'admin' && !isCurrentSuperAdmin) {
                    actionHtml = `<span style="color:#8b5cf6; font-size:12px; font-weight:bold;">Администратор</span>`;
                }
                else {
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
                    <td><span class="badge badge-${u.status}">${u.status}</span></td>
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

        /* АДМИН - ТИКЕТЫ ПОДДЕРЖКИ */
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
                if (!allTicketsCache.length) {
                    container.innerHTML = '<span style="color:#f87171;">Ошибка загрузки тикетов.</span>';
                }
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

            const filtered = allTicketsCache.filter(t => {
                if (currentTicketFilter === 'open') return t.status === 'open' || t.status === 'replied';
                return true;
            });

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
                        <span class="badge badge-${t.status}">${t.status === 'open' ? 'Открыт' : (t.status === 'replied' ? 'Отвечен' : 'Завершен')}</span>
                    </div>
                    <div class="ticket-msg">${escapeHtml(t.message)}</div>
                `;
                container.appendChild(card);
            });
        }

        /* МИНИ-ЧАТ ТИКЕТОВ В РЕАЛЬНОМ ВРЕМЕНИ */
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
                        <label style="font-size: 11.5px; color: var(--text-muted); display: block; margin-bottom: 6px;">Опишите вашу проблему или вопрос:</label>
                        <textarea id="user-ticket-input" style="width: 100%; background: rgba(0,0,0,0.4); border: 1px solid var(--border-color); color: #fff; padding: 10px; border-radius: 10px; font-size: 12px; outline: none; resize: vertical; min-height: 70px;" placeholder="Здравствуйте, у меня возник вопрос по..."></textarea>
                        <button type="submit" class="btn-action" style="margin-top: 8px; width: 100%;">Создать тикет</button>
                    </form>
                    <hr style="border: none; border-top: 1px solid var(--border-color); margin: 14px 0;">
                    <h4 style="font-size: 12px; color: #fff; margin-bottom: 10px;">Ваши обращения:</h4>
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
                    const isUser = m.role === 'user';
                    bubble.className = `t-msg-bubble ${isUser ? 't-msg-user' : 't-msg-admin'}`;
                    bubble.innerHTML = `
                        <span class="t-msg-meta">${escapeHtml(m.sender)}</span>
                        ${escapeHtml(m.text)}
                    `;
                    box.appendChild(bubble);
                });

                if (isAtBottom) {
                    box.scrollTop = box.scrollHeight;
                }
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
                } else {
                    alert('Ошибка отправки сообщения.');
                }
            } catch(e) {
                alert('Ошибка соединения с сервером.');
            }
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

        /* ПОЛЬЗОВАТЕЛЬ - ПОДДЕРЖКА */
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
                            <span class="badge badge-${t.status}">${t.status === 'open' ? 'В обработке' : (t.status === 'replied' ? 'Есть ответ' : 'Завершен')}</span>
                        </div>
                        <div class="ticket-msg">${escapeHtml(t.message)}</div>
                    `;
                    container.appendChild(item);
                });
            } catch(e) {
                if (container && !container.children.length) {
                    container.innerHTML = '<span style="color:#f87171; font-size:12px;">Ошибка загрузки.</span>';
                }
            }
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
            } catch(e) {
                alert('Ошибка соединения.');
            }
        }

        function checkFilePermissionAndOpen() {
            if (myCurrentStatus === 'free' || myCurrentStatus === 'guest') {
                alert('🔒 Отправка файлов и фото доступна только VIP-пользователям.');
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
                if (window.innerWidth <= 768) toggleSidebar();
                return;
            }
            if (activeController) activeController.abort();
            const newChat = { id: Date.now().toString(), name: `Новый чат ${chats.length + 1}`, messages: [] };
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
                    let fileBadge = msg.fileName ? `<div class="file-preview-tag">📎 ${escapeHtml(msg.fileName)}</div><br/>` : '';
                    row.innerHTML = `<div class="msg-user">${fileBadge}${escapeHtml(msg.content)}</div>`;
                } else {
                    row.innerHTML = `<div class="msg-bot">${marked.parse(msg.content)}</div>`;
                }
                chatContainer.appendChild(row);
            });

            chatContainer.scrollTop = chatContainer.scrollHeight;
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

        function handleKeyPress(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleActionButton();
            }
        }

        function handleActionButton() {
            if (isGenerating) {
                cancelRequest();
            } else {
                sendMessage();
            }
        }

        function setGeneratingState(generating) {
            isGenerating = generating;
            const btn = document.getElementById('action-btn');
            const input = document.getElementById('prompt-input');

            if (generating) {
                btn.textContent = 'Отмена';
                btn.classList.add('cancel-mode');
                input.disabled = true;
            } else {
                btn.textContent = 'Отправить';
                btn.classList.remove('cancel-mode');
                input.disabled = false;
                input.focus();
            }
        }

        function cancelRequest() {
            if (activeController) {
                activeController.abort();
                activeController = null;
            }
            setGeneratingState(false);

            const activeChat = chats.find(c => c.id === currentChatId);
            if (activeChat) {
                const loader = document.getElementById('active-loader');
                if (loader) loader.remove();
                
                activeChat.messages.push({
                    role: 'bot',
                    content: '<i>Сообщение отменено пользователем.</i>'
                });
                saveState();
            }
        }

        async function sendMessage() {
            const input = document.getElementById('prompt-input');
            const promptText = input.value.trim();

            if (!promptText && !selectedFile) return;

            const activeChat = chats.find(c => c.id === currentChatId);
            if (!activeChat) return;

            if (activeChat.messages.length === 0 && promptText) {
                activeChat.name = promptText.slice(0, 20) + (promptText.length > 20 ? '...' : '');
            }

            const userMsg = {
                role: 'user',
                content: promptText,
                fileName: selectedFile ? selectedFile.name : null
            };
            activeChat.messages.push(userMsg);

            input.value = '';
            const attachedFile = selectedFile;
            removeSelectedFile();
            saveState();

            setGeneratingState(true);

            const chatContainer = document.getElementById('chat-container');
            const loaderRow = document.createElement('div');
            loaderRow.className = 'msg-row bot-row';
            loaderRow.id = 'active-loader';
            loaderRow.innerHTML = `
                <div class="loader-box">
                    <div class="spinner"></div>
                    <span>Rubinov AI думает...</span>
                </div>
            `;
            chatContainer.appendChild(loaderRow);
            chatContainer.scrollTop = chatContainer.scrollHeight;

            const formData = new FormData();
            formData.append('prompt', promptText);
            if (attachedFile) {
                formData.append('file', attachedFile);
            }

            activeController = new AbortController();

            try {
                const response = await fetch('/api/chat', {
                    method: 'POST',
                    body: formData,
                    signal: activeController.signal
                });

                if (!response.ok) {
                    const errData = await response.json();
                    throw new Error(errData.detail || 'Ошибка при получении ответа');
                }

                const data = await response.json();

                activeChat.messages.push({
                    role: 'bot',
                    content: data.response
                });
            } catch (err) {
                if (err.name === 'AbortError') return;

                activeChat.messages.push({
                    role: 'bot',
                    content: `⚠️ Ошибка: ${err.message}`
                });
            } finally {
                activeController = null;
                setGeneratingState(false);
                const loader = document.getElementById('active-loader');
                if (loader) loader.remove();
                saveState();
            }
        }

        function escapeHtml(text) {
            if (!text) return '';
            return text
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");
        }
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def read_root(request: Request):
    user_email = request.session.get("user_email")
    status = get_user_status(user_email)

    if user_email:
        badge_class = f"badge-{status}"
        admin_btn = '<button type="button" class="btn-admin-panel" onclick="toggleAdminModal(true)">👑 Admin Panel</button>' if status == "admin" else ""
        auth_html = f"""
            {admin_btn}
            <div style="display:flex; align-items:center; justify-content:space-between; width:100%; margin-bottom: 4px;">
                <span style="word-break:break-all; font-weight:600; font-size:11px; color:#fff;">{user_email} <span class="status-badge {badge_class}">{status}</span></span>
                <a href="/auth/logout" style="color:#f87171; text-decoration:none; font-size:11px; font-weight:600;">Выйти</a>
            </div>
        """
    else:
        auth_html = """
            <a href="/auth/google" class="btn-google-login">
                <svg width="14" height="14" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"/></svg>
                Войти через Google
            </a>
        """

    page_code = HTML_TEMPLATE.replace("USER_AUTH_BLOCK", auth_html)
    return HTMLResponse(content=page_code)

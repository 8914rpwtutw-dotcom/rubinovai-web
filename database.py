import sqlite3
import time

DB_FILE = "rubinov_ai.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            telegram_id TEXT PRIMARY KEY,
            username TEXT,
            is_banned INTEGER DEFAULT 0,
            is_vip INTEGER DEFAULT 0,
            auth_code TEXT,
            code_expires REAL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id TEXT,
            message TEXT,
            status TEXT DEFAULT 'open',
            created_at REAL
        )
    ''')
    
    conn.commit()
    conn.close()

def check_user_status(telegram_id: str):
    if not telegram_id or telegram_id == "demo_user":
        return {"is_banned": False, "is_vip": False}
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT is_banned, is_vip FROM users WHERE telegram_id = ?", (telegram_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return {"is_banned": False, "is_vip": False}
    return {"is_banned": bool(row[0]), "is_vip": bool(row[1])}

def set_user_ban(telegram_id: str, banned: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_banned = ? WHERE telegram_id = ?", (banned, telegram_id))
    conn.commit()
    conn.close()

def set_user_vip(telegram_id: str, vip: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_vip = ? WHERE telegram_id = ?", (vip, telegram_id))
    conn.commit()
    conn.close()

def register_user_if_not_exists(telegram_id: str, username: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (telegram_id, username, is_banned, is_vip) VALUES (?, ?, 0, 0)", (telegram_id, username))
    conn.commit()
    conn.close()

def save_auth_code(telegram_id: str, code: str, expires_at: float):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET auth_code = ?, code_expires = ? WHERE telegram_id = ?", (code, expires_at, telegram_id))
    conn.commit()
    conn.close()

def find_user_by_auth_code(code: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT telegram_id, code_expires FROM users WHERE auth_code = ?", (code,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
        
    telegram_id, expires_at = row[0], row[1]
    if time.time() > expires_at:
        return None # Код просрочен
        
    return telegram_id

def save_ticket(telegram_id: str, message: str, created_at: float):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO tickets (telegram_id, message, created_at) VALUES (?, ?, ?)", (telegram_id, message, created_at))
    conn.commit()
    conn.close()

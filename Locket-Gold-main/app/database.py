import sqlite3
import time
from datetime import datetime

DB_NAME = "bot_data.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS usage_logs (
                    user_id INTEGER,
                    date TEXT,
                    count INTEGER,
                    PRIMARY KEY (user_id, date)
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER PRIMARY KEY,
                    language TEXT
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS bot_config (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS request_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    uid TEXT,
                    status TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )''')
    conn.commit()
    conn.close()

def get_user_usage(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT count FROM usage_logs WHERE user_id = ? AND date = ?", (user_id, today))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0

def increment_usage(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    
    c.execute("SELECT count FROM usage_logs WHERE user_id = ? AND date = ?", (user_id, today))
    result = c.fetchone()
    
    if result:
        new_count = result[0] + 1
        c.execute("UPDATE usage_logs SET count = ? WHERE user_id = ? AND date = ?", (new_count, user_id, today))
    else:
        c.execute("INSERT INTO usage_logs (user_id, date, count) VALUES (?, ?, ?)", (user_id, today, 1))
        
    conn.commit()
    conn.close()

def check_can_request(user_id, max_limit=5):
    current = get_user_usage(user_id)
    return current < max_limit

def set_lang(user_id, lang):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO user_settings (user_id, language) VALUES (?, ?)", (user_id, lang))
    conn.commit()
    conn.close()

def get_lang(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT language FROM user_settings WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def get_all_users():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT DISTINCT user_id FROM usage_logs UNION SELECT user_id FROM user_settings")
    users = [row[0] for row in c.fetchall()]
    conn.close()
    return users

def reset_usage(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    c.execute("DELETE FROM usage_logs WHERE user_id = ? AND date = ?", (user_id, today))
    conn.commit()
    conn.close()

def set_config(key, value):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO bot_config (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def get_config(key, default=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT value FROM bot_config WHERE key = ?", (key,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else default

def log_request(user_id, uid, status):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO request_logs (user_id, uid, status) VALUES (?, ?, ?)", (user_id, uid, status))
    conn.commit()
    conn.close()

def get_stats():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM request_logs")
    total = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM request_logs WHERE status = 'SUCCESS'")
    success = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM request_logs WHERE status != 'SUCCESS'")
    fail = c.fetchone()[0]
    
    c.execute("SELECT COUNT(DISTINCT user_id) FROM request_logs")
    unique_users = c.fetchone()[0]
    
    conn.close()
    return {
        "total": total,
        "success": success,
        "fail": fail,
        "unique_users": unique_users
    }

init_db()

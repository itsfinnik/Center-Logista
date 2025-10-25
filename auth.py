"""
Модуль авторизации и аутентификации пользователей
"""
import sqlite3
import hashlib
import secrets
import jwt
from datetime import datetime, timedelta
from typing import Optional, Dict
from pydantic import BaseModel, EmailStr, validator
import re

# Секретный ключ для JWT (в продакшене должен быть в переменных окружения)
SECRET_KEY = secrets.token_urlsafe(32)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30 * 24 * 60  # 30 дней

# Инициализация базы данных
def init_db():
    """Создание таблицы пользователей и статистики"""
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            phone TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_stats (
            user_id INTEGER PRIMARY KEY,
            routes_count INTEGER DEFAULT 0,
            clients_visited INTEGER DEFAULT 0,
            total_distance REAL DEFAULT 0,
            total_time INTEGER DEFAULT 0,
            last_route_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    conn.commit()
    conn.close()

# Модели данных
class UserRegister(BaseModel):
    email: EmailStr
    phone: str
    password: str
    
    @validator('phone')
    def validate_phone(cls, v):
        # Удаляем все символы кроме цифр и +
        cleaned = re.sub(r'[^\d+]', '', v)
        if len(cleaned) < 10:
            raise ValueError('Номер телефона должен содержать минимум 10 цифр')
        return cleaned
    
    @validator('password')
    def validate_password(cls, v):
        if len(v) < 6:
            raise ValueError('Пароль должен содержать минимум 6 символов')
        if not re.match(r'^[A-Za-z0-9_]+$', v):
            raise ValueError('Пароль должен содержать только A-Z, цифры и "_"')
        return v

class UserLogin(BaseModel):
    login: str  # email или телефон
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class UserResponse(BaseModel):
    id: int
    email: str
    phone: str
    created_at: str

# Функции для работы с паролями
def hash_password(password: str) -> str:
    """Хеширование пароля"""
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.sha256((password + salt).encode()).hexdigest()
    return f"{salt}${pwd_hash}"

def verify_password(password: str, password_hash: str) -> bool:
    """Проверка пароля"""
    try:
        salt, pwd_hash = password_hash.split('$')
        return hashlib.sha256((password + salt).encode()).hexdigest() == pwd_hash
    except:
        return False

# Функции для работы с JWT
def create_access_token(data: dict) -> str:
    """Создание JWT токена"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_access_token(token: str) -> Optional[Dict]:
    """Декодирование JWT токена"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

# Функции для работы с пользователями
def create_user(email: str, phone: str, password: str) -> Optional[UserResponse]:
    """Создание нового пользователя"""
    try:
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        
        password_hash = hash_password(password)
        
        cursor.execute(
            'INSERT INTO users (email, phone, password_hash) VALUES (?, ?, ?)',
            (email, phone, password_hash)
        )
        
        user_id = cursor.lastrowid
        conn.commit()
        
        # Получаем созданного пользователя
        cursor.execute('SELECT id, email, phone, created_at FROM users WHERE id = ?', (user_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return UserResponse(
                id=row[0],
                email=row[1],
                phone=row[2],
                created_at=row[3]
            )
        return None
    except sqlite3.IntegrityError:
        return None

def authenticate_user(login: str, password: str) -> Optional[UserResponse]:
    """Аутентификация пользователя"""
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    
    # Проверяем по email или телефону
    cursor.execute(
        'SELECT id, email, phone, password_hash, created_at FROM users WHERE email = ? OR phone = ?',
        (login, login)
    )
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
    
    if not verify_password(password, row[3]):
        return None
    
    return UserResponse(
        id=row[0],
        email=row[1],
        phone=row[2],
        created_at=row[4]
    )

def get_user_by_id(user_id: int) -> Optional[UserResponse]:
    """Получение пользователя по ID"""
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT id, email, phone, created_at FROM users WHERE id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return UserResponse(
            id=row[0],
            email=row[1],
            phone=row[2],
            created_at=row[3]
        )
    return None

# Функции для работы со статистикой
def get_user_stats(user_id: int) -> Optional[Dict]:
    """Получение статистики пользователя"""
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT routes_count, clients_visited, total_distance, total_time, last_route_at 
        FROM user_stats 
        WHERE user_id = ?
    ''', (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            'routes_count': row[0],
            'clients_visited': row[1],
            'total_distance': round(row[2], 1),
            'total_time': row[3],
            'last_route_at': row[4]
        }
    return {
        'routes_count': 0,
        'clients_visited': 0,
        'total_distance': 0,
        'total_time': 0,
        'last_route_at': None
    }

def update_user_stats(user_id: int, clients_count: int, distance: float, time: int):
    """Обновление статистики пользователя после построения маршрута"""
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    
    # Проверяем, есть ли запись
    cursor.execute('SELECT user_id FROM user_stats WHERE user_id = ?', (user_id,))
    exists = cursor.fetchone()
    
    if exists:
        # Обновляем существующую запись
        cursor.execute('''
            UPDATE user_stats 
            SET routes_count = routes_count + 1,
                clients_visited = clients_visited + ?,
                total_distance = total_distance + ?,
                total_time = total_time + ?,
                last_route_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
        ''', (clients_count, distance, time, user_id))
    else:
        # Создаем новую запись
        cursor.execute('''
            INSERT INTO user_stats (user_id, routes_count, clients_visited, total_distance, total_time, last_route_at)
            VALUES (?, 1, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (user_id, clients_count, distance, time))
    
    conn.commit()
    conn.close()

# Инициализация БД при импорте
init_db()


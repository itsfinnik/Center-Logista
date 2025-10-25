"""
Система интеллектуального планирования выездов для предпринимателей
Backend на FastAPI
Production-ready version с логированием и обработкой ошибок
"""
from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from pydantic import BaseModel, ValidationError
from typing import List, Optional
import pandas as pd
import numpy as np
from datetime import datetime, time, timedelta
import io
import json
import os
import logging
import sys
from logging.handlers import RotatingFileHandler

# Импорт модуля авторизации
from auth import (
    UserRegister, UserLogin, Token, UserResponse,
    create_user, authenticate_user, get_user_by_id,
    create_access_token, decode_access_token,
    get_user_stats, update_user_stats
)

# ==================== КОНФИГУРАЦИЯ ====================
class Config:
    """Конфигурация приложения через переменные окружения"""
    APP_NAME = os.getenv("APP_NAME", "Система планирования маршрутов")
    VERSION = os.getenv("APP_VERSION", "1.0.0")
    DEBUG = os.getenv("DEBUG", "False").lower() == "true"
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    MAX_CLIENTS = int(os.getenv("MAX_CLIENTS", "100"))
    DEFAULT_VISIT_DURATION = int(os.getenv("DEFAULT_VISIT_DURATION", "30"))
    CSV_DATA_PATH = os.getenv("CSV_DATA_PATH", "test_data.csv")

config = Config()

# ==================== ЛОГИРОВАНИЕ ====================
def setup_logging():
    """Настройка системы логирования для production"""
    log_format = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Консольный handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_format)
    
    # Файловый handler с ротацией
    file_handler = RotatingFileHandler(
        'app.log',
        maxBytes=10*1024*1024,  # 10 MB
        backupCount=5
    )
    file_handler.setFormatter(log_format)
    
    # Основной logger
    logger = logging.getLogger("route_optimizer")
    logger.setLevel(getattr(logging, config.LOG_LEVEL))
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    return logger

logger = setup_logging()

# ==================== FASTAPI APP ====================
app = FastAPI(
    title=config.APP_NAME,
    version=config.VERSION,
    debug=config.DEBUG
)

# Middleware для логирования запросов
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Логирование всех HTTP запросов"""
    logger.info(f"[REQUEST] {request.method} {request.url.path}")
    try:
        response = await call_next(request)
        logger.info(f"[SUCCESS] {request.method} {request.url.path} - {response.status_code}")
        return response
    except Exception as e:
        logger.error(f"[ERROR] {request.method} {request.url.path} - Error: {str(e)}")
        raise

# Обработчик глобальных ошибок
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Обработка всех необработанных исключений"""
    logger.error(f"[CRITICAL] Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "Внутренняя ошибка сервера",
            "detail": str(exc) if config.DEBUG else "Пожалуйста, попробуйте позже"
        }
    )

# CORS для работы frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Статические файлы теперь в корне проекта (без папки static)
# Они будут раздаваться через отдельные endpoints

# Модели данных
class Client(BaseModel):
    id: int
    address: str
    latitude: float
    longitude: float
    work_start: str  # HH:MM
    work_end: str    # HH:MM
    lunch_start: str # HH:MM
    lunch_end: str   # HH:MM
    priority: str    # VIP или Standart
    
class RouteRequest(BaseModel):
    clients: List[Client]
    start_time: str = "09:00"  # Время начала работы
    visit_duration: int = 30   # Длительность визита в минутах
    start_location: Optional[List[float]] = None  # [latitude, longitude] - точка старта

class RouteStop(BaseModel):
    client: Client
    arrival_time: str
    departure_time: str
    travel_time_from_previous: int  # минуты
    distance_from_previous: float   # км
    
class RouteResponse(BaseModel):
    route: List[RouteStop]
    total_distance: float  # км
    total_time: int        # минуты
    total_clients: int
    efficiency_score: float

# Утилиты для работы со временем
def time_str_to_minutes(time_str: str) -> int:
    """Конвертирует время HH:MM в минуты от начала дня"""
    h, m = map(int, time_str.split(':'))
    return h * 60 + m

def minutes_to_time_str(minutes: int) -> str:
    """Конвертирует минуты от начала дня в HH:MM"""
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"

def is_within_working_hours(arrival_time: int, client: Client) -> bool:
    """Проверяет, попадает ли визит в рабочее время (не в обед)"""
    work_start = time_str_to_minutes(client.work_start)
    work_end = time_str_to_minutes(client.work_end)
    lunch_start = time_str_to_minutes(client.lunch_start)
    lunch_end = time_str_to_minutes(client.lunch_end)
    
    if arrival_time < work_start or arrival_time > work_end:
        return False
    if lunch_start <= arrival_time < lunch_end:
        return False
    return True

def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Вычисляет расстояние между двумя точками (формула гаверсинуса)"""
    from math import radians, sin, cos, sqrt, atan2
    
    R = 6371  # Радиус Земли в км
    
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    
    return R * c

def estimate_travel_time(distance_km: float, base_speed: float = 30.0) -> int:
    """
    Оценивает время в пути с учетом пробок
    base_speed: средняя скорость в км/ч (30 км/ч - с учетом городских условий)
    """
    # Добавляем фактор пробок (вариативность ±20%)
    speed_factor = np.random.uniform(0.8, 1.2)
    effective_speed = base_speed * speed_factor
    
    travel_time_hours = distance_km / effective_speed
    travel_time_minutes = int(travel_time_hours * 60)
    
    return max(travel_time_minutes, 5)  # Минимум 5 минут

class RouteOptimizer:
    """Оптимизатор маршрутов с учетом всех бизнес-ограничений"""
    
    def __init__(self, clients: List[Client], start_time: str, visit_duration: int, start_location: Optional[List[float]] = None):
        self.clients = clients
        self.start_time_minutes = time_str_to_minutes(start_time)
        self.visit_duration = visit_duration
        self.start_location = start_location  # [latitude, longitude]
        
    def calculate_priority_score(self, client: Client) -> float:
        """Вычисляет приоритет клиента"""
        return 2.0 if client.priority == "VIP" else 1.0
    
    def build_distance_matrix(self) -> np.ndarray:
        """Строит матрицу расстояний между всеми клиентами"""
        n = len(self.clients)
        matrix = np.zeros((n, n))
        
        for i in range(n):
            for j in range(n):
                if i != j:
                    matrix[i][j] = calculate_distance(
                        self.clients[i].latitude,
                        self.clients[i].longitude,
                        self.clients[j].latitude,
                        self.clients[j].longitude
                    )
        return matrix
    
    def optimize_route_greedy(self) -> List[RouteStop]:
        """
        Жадный алгоритм с учетом:
        - Временных окон
        - Приоритета клиентов
        - Расстояния
        - Обеденных перерывов
        """
        unvisited = self.clients.copy()
        route = []
        current_time = self.start_time_minutes
        last_position = None
        
        # Определяем точку отсчета для выбора первого клиента
        if self.start_location:
            # Используем местоположение пользователя
            reference_lat, reference_lon = self.start_location
            logger.info(f"📍 Используем стартовую точку: [{reference_lat}, {reference_lon}]")
        else:
            # Используем центр всех клиентов
            reference_lat = np.mean([c.latitude for c in unvisited])
            reference_lon = np.mean([c.longitude for c in unvisited])
            logger.info(f"📍 Используем центр клиентов: [{reference_lat}, {reference_lon}]")
        
        # Умный выбор первого клиента с учетом расстояний
        # Вычисляем расстояния от стартовой точки до всех клиентов
        distances = [(c, calculate_distance(reference_lat, reference_lon, c.latitude, c.longitude)) 
                     for c in unvisited]
        distances.sort(key=lambda x: x[1])  # Сортируем по расстоянию
        
        vip_clients = [c for c in unvisited if c.priority == "VIP"]
        
        if vip_clients:
            # Находим ближайшего VIP и его расстояние
            closest_vip = min(vip_clients, key=lambda c: calculate_distance(
                reference_lat, reference_lon, c.latitude, c.longitude
            ))
            vip_distance = calculate_distance(
                reference_lat, reference_lon, closest_vip.latitude, closest_vip.longitude
            )
            
            # Считаем сколько обычных клиентов ближе, чем VIP
            closer_regular_clients = [c for c, dist in distances 
                                     if c.priority != "VIP" and dist < vip_distance]
            
            # Если 2+ обычных клиента ближе, чем VIP - начинаем с ближайшего обычного
            if len(closer_regular_clients) >= 2:
                first_client = distances[0][0]  # Ближайший клиент (любой)
                logger.info(f"🎯 Начинаем с ближайшего клиента (есть {len(closer_regular_clients)} обычных ближе VIP)")
            else:
                first_client = closest_vip
                logger.info(f"⭐ Начинаем с VIP (менее 2 обычных клиентов ближе)")
        else:
            # Нет VIP клиентов - начинаем с ближайшего
            first_client = distances[0][0]
            logger.info(f"📍 Начинаем с ближайшего клиента (VIP нет)")
        
        max_iterations = len(self.clients) + 5  # Защита от бесконечного цикла
        iteration = 0
        
        while unvisited and current_time < 18 * 60 and iteration < max_iterations:  # До 18:00
            iteration += 1
            if last_position is None:
                # Первый клиент
                next_client = first_client
                travel_time = 0
                distance = 0.0
            else:
                # Выбираем следующего клиента по комплексному критерию
                best_client = None
                best_score = float('-inf')
                
                for client in unvisited:
                    # Расстояние от текущей позиции
                    dist = calculate_distance(
                        last_position[0], last_position[1],
                        client.latitude, client.longitude
                    )
                    travel_time_est = estimate_travel_time(dist)
                    arrival_time = current_time + travel_time_est
                    
                    # Проверяем временные окна
                    if not is_within_working_hours(arrival_time, client):
                        # Пытаемся скорректировать время
                        work_start = time_str_to_minutes(client.work_start)
                        lunch_start = time_str_to_minutes(client.lunch_start)
                        lunch_end = time_str_to_minutes(client.lunch_end)
                        
                        if arrival_time < work_start:
                            arrival_time = work_start
                        elif lunch_start <= arrival_time < lunch_end:
                            arrival_time = lunch_end
                        else:
                            continue  # Не можем посетить
                    
                    # Комплексная оценка: приоритет / расстояние
                    priority_score = self.calculate_priority_score(client)
                    distance_penalty = dist + 0.1  # Избегаем деления на 0
                    time_urgency = 1.0 / (time_str_to_minutes(client.work_end) - arrival_time + 1)
                    
                    score = (priority_score * 100 / distance_penalty) + time_urgency * 50
                    
                    if score > best_score:
                        best_score = score
                        best_client = client
                        best_distance = dist
                        best_travel_time = travel_time_est
                        best_arrival = arrival_time
                
                if best_client is None:
                    break  # Не можем посетить больше клиентов
                
                next_client = best_client
                travel_time = best_travel_time
                distance = best_distance
                current_time = best_arrival
            
            # Проверяем, не попадаем ли в обед
            lunch_start = time_str_to_minutes(next_client.lunch_start)
            lunch_end = time_str_to_minutes(next_client.lunch_end)
            
            if lunch_start <= current_time < lunch_end:
                current_time = lunch_end
            
            # Добавляем остановку
            departure_time = current_time + self.visit_duration
            
            stop = RouteStop(
                client=next_client,
                arrival_time=minutes_to_time_str(current_time),
                departure_time=minutes_to_time_str(departure_time),
                travel_time_from_previous=travel_time,
                distance_from_previous=distance
            )
            route.append(stop)
            
            # Обновляем состояние
            unvisited.remove(next_client)
            last_position = (next_client.latitude, next_client.longitude)
            current_time = departure_time
        
        return route
    
    def calculate_route_metrics(self, route: List[RouteStop]) -> dict:
        """Вычисляет метрики маршрута"""
        total_distance = sum(stop.distance_from_previous for stop in route)
        total_time = sum(stop.travel_time_from_previous for stop in route) + \
                     len(route) * self.visit_duration
        
        # Коэффициент эффективности: клиенты/час
        efficiency_score = len(route) / (total_time / 60) if total_time > 0 else 0
        
        return {
            "total_distance": round(total_distance, 2),
            "total_time": total_time,
            "total_clients": len(route),
            "efficiency_score": round(efficiency_score, 2)
        }

@app.get("/", response_class=HTMLResponse)
async def root():
    """Landing page"""
    return FileResponse("landing.html")

@app.get("/app.html")
async def app_page():
    """Main application page"""
    return FileResponse("app.html")

@app.get("/login.html")
async def login_page():
    """Login page"""
    return FileResponse("login.html")

@app.get("/register.html")
async def register_page():
    """Register page"""
    return FileResponse("register.html")

@app.get("/profile.html")
async def profile_page():
    """Profile page"""
    return FileResponse("profile.html")

@app.get("/index.html")
async def index_redirect():
    """Redirect from old index.html to root"""
    return FileResponse("index.html")

@app.get("/logo.png")
async def logo():
    """Logo image"""
    return FileResponse("logo.png")

@app.post("/api/upload-csv")
async def upload_csv(request: Request, file: Optional[UploadFile] = File(None)):
    """Загрузка CSV файла с адресами"""
    try:
        logger.info(f"=== НАЧАЛО ЗАГРУЗКИ CSV ===")
        logger.info(f"Request headers: {dict(request.headers)}")
        logger.info(f"File parameter: {file}")
        
        if file is None:
            logger.error("Файл не передан - параметр file = None")
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "Файл не передан"}
            )
        
        logger.info(f"Получен файл: {file.filename}")
        logger.info(f"Content type: {file.content_type}")
        
        if not file.filename:
            logger.error("Пустое имя файла")
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "Пустое имя файла"}
            )
        
        contents = await file.read()
        logger.info(f"Размер файла: {len(contents)} байт")
        
        if len(contents) == 0:
            logger.error("Пустой файл")
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "Файл пустой"}
            )
        
        # Пробуем разные кодировки
        try:
            df = pd.read_csv(io.BytesIO(contents), encoding='utf-8')
        except UnicodeDecodeError:
            try:
                df = pd.read_csv(io.BytesIO(contents), encoding='cp1251')
            except UnicodeDecodeError:
                df = pd.read_csv(io.BytesIO(contents), encoding='latin1')
        
        logger.info(f"CSV колонки: {list(df.columns)}")
        logger.info(f"Строк в CSV: {len(df)}")
        
        # Ищем колонку с адресами (гибкий поиск)
        address_column = None
        possible_address_columns = ['Адрес объекта', 'Адрес', 'Address', 'адрес', 'address']
        for col in df.columns:
            if col in possible_address_columns or 'адрес' in col.lower() or 'address' in col.lower():
                address_column = col
                logger.info(f"Найдена колонка с адресами: {address_column}")
                break
        
        if not address_column:
            logger.error(f"Не найдена колонка с адресами. Имеющиеся колонки: {list(df.columns)}")
            return JSONResponse(
                status_code=400,
                content={
                    "success": False, 
                    "error": f"В CSV файле не найдена колонка с адресами.\n\nИспользуйте одно из названий: 'Адрес', 'Address', 'Адрес объекта'\n\nИмеющиеся колонки в вашем файле: {', '.join(df.columns)}"
                }
            )
        
        # Проверяем наличие координат
        has_coordinates = ('Географическая широта' in df.columns or 'Широта' in df.columns or 'Latitude' in df.columns) and \
                         ('Географическая долгота' in df.columns or 'Долгота' in df.columns or 'Longitude' in df.columns)
        
        if not has_coordinates:
            logger.info("Координаты отсутствуют - будут геокодированы на клиенте")
        
        # Преобразуем в список клиентов с гибким парсингом
        clients = []
        for row_idx, row in enumerate(df.iterrows()):
            idx, row = row
            try:
                # Получаем адрес
                address = str(row[address_column]).strip()
                if not address or address == 'nan':
                    continue
                
                # Получаем координаты (если есть)
                latitude = None
                longitude = None
                try:
                    if 'Географическая широта' in df.columns and 'Географическая долгота' in df.columns:
                        latitude = float(row['Географическая широта'])
                        longitude = float(row['Географическая долгота'])
                    elif 'Широта' in df.columns and 'Долгота' in df.columns:
                        latitude = float(row['Широта'])
                        longitude = float(row['Долгота'])
                    elif 'Latitude' in df.columns and 'Longitude' in df.columns:
                        latitude = float(row['Latitude'])
                        longitude = float(row['Longitude'])
                except:
                    latitude = None
                    longitude = None
                
                # Если координат нет - используем временные значения (будут геокодированы на клиенте)
                if latitude is None or longitude is None:
                    latitude = 47.222 + row_idx * 0.001  # Временные координаты в Ростове
                    longitude = 39.720 + row_idx * 0.001
                
                # Получаем время работы (с дефолтами)
                work_start = str(row['Время начала рабочего дня']) if 'Время начала рабочего дня' in df.columns else '09:00'
                work_end = str(row['Время окончания рабочего дня']) if 'Время окончания рабочего дня' in df.columns else '18:00'
                lunch_start = str(row['Время начала обеда']) if 'Время начала обеда' in df.columns else '13:00'
                lunch_end = str(row['Время окончания обеда']) if 'Время окончания обеда' in df.columns else '14:00'
                
                # Получаем приоритет (с дефолтом)
                priority = 'Standart'
                if 'Уровень клиента' in df.columns:
                    priority = str(row['Уровень клиента'])
                if priority not in ['VIP', 'Standart']:
                    priority = 'Standart'
                
                # Получаем ID (или генерируем)
                client_id = row_idx + 1
                if 'Номер объекта' in df.columns:
                    try:
                        client_id = int(row['Номер объекта'])
                    except:
                        client_id = row_idx + 1
                
                client = Client(
                    id=client_id,
                    address=address,
                    latitude=latitude,
                    longitude=longitude,
                    work_start=work_start,
                    work_end=work_end,
                    lunch_start=lunch_start,
                    lunch_end=lunch_end,
                    priority=priority
                )
                clients.append(client)
            except Exception as e:
                logger.warning(f"Ошибка в строке {row_idx + 2}: {str(e)}")
                continue
        
        if len(clients) == 0:
            logger.error("Не удалось обработать ни одной строки")
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "Не удалось обработать данные из файла"}
            )
        
        logger.info(f"Загружено {len(clients)} клиентов")
        return JSONResponse(
            status_code=200,
            content={"success": True, "clients": [c.model_dump() for c in clients]}
        )
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        logger.error(f"Ошибка загрузки CSV: {str(e)}")
        logger.error(f"Traceback: {error_trace}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"Ошибка обработки файла: {str(e)}"}
        )

@app.post("/api/optimize-route", response_model=RouteResponse)
async def optimize_route(request: RouteRequest):
    """Оптимизация маршрута с полной обработкой ошибок"""
    try:
        logger.info(f"🚗 Начало оптимизации маршрута: {len(request.clients)} клиентов, старт {request.start_time}")
        
        # Валидация входных данных
        if len(request.clients) == 0:
            logger.warning("⚠️ Попытка оптимизации с пустым списком клиентов")
            raise HTTPException(status_code=400, detail="Список клиентов пуст")
        
        if len(request.clients) > config.MAX_CLIENTS:
            logger.warning(f"⚠️ Превышен лимит клиентов: {len(request.clients)} > {config.MAX_CLIENTS}")
            raise HTTPException(
                status_code=400,
                detail=f"Слишком много клиентов. Максимум: {config.MAX_CLIENTS}"
            )
        
        optimizer = RouteOptimizer(
            clients=request.clients,
            start_time=request.start_time,
            visit_duration=request.visit_duration,
            start_location=request.start_location
        )
        
        # Строим маршрут
        route = optimizer.optimize_route_greedy()
        logger.info(f"✅ Маршрут построен: {len(route)} точек")
        
        # Вычисляем метрики
        metrics = optimizer.calculate_route_metrics(route)
        logger.info(f"📊 Метрики: {metrics['total_distance']:.1f} км, {metrics['total_time']} мин")
        
        return RouteResponse(
            route=route,
            **metrics
        )
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"❌ Ошибка валидации: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Некорректные данные: {str(e)}")
    except Exception as e:
        logger.error(f"❌ Ошибка оптимизации: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Не удалось построить маршрут: {str(e)}" if config.DEBUG else "Ошибка построения маршрута"
        )

@app.get("/api/test-data")
async def get_test_data():
    """Возвращает случайные 15 адресов из всей базы (100 точек)"""
    try:
        csv_path = os.path.join(os.path.dirname(__file__), config.CSV_DATA_PATH)
        
        if not os.path.exists(csv_path):
            logger.error(f"❌ CSV файл не найден: {csv_path}")
            raise HTTPException(status_code=500, detail="Файл с данными не найден")
        
        df = pd.read_csv(csv_path)
        logger.info(f"📊 Загружено {len(df)} адресов из CSV")
        
        if len(df) == 0:
            logger.warning("⚠️ CSV файл пуст")
            raise HTTPException(status_code=500, detail="Нет доступных адресов")
        
        # Выбираем случайные 15 точек из всех доступных
        sample_size = min(15, len(df))
        random_sample = df.sample(n=sample_size, random_state=None).reset_index(drop=True)
        
        clients = []
        for idx, row in random_sample.iterrows():
            try:
                client = Client(
                    id=idx + 1,  # Переиндексируем от 1 до 15
                    address=row['Адрес объекта'],
                    latitude=float(row['Географическая широта']),
                    longitude=float(row['Географическая долгота']),
                    work_start=row['Время начала рабочего дня'],
                    work_end=row['Время окончания рабочего дня'],
                    lunch_start=row['Время начала обеда'],
                    lunch_end=row['Время окончания обеда'],
                    priority=row['Уровень клиента']
                )
                clients.append(client)
            except Exception as e:
                logger.warning(f"⚠️ Ошибка парсинга клиента #{idx + 1}: {str(e)}")
                continue
        
        if len(clients) == 0:
            logger.error("❌ Не удалось загрузить ни одного клиента")
            raise HTTPException(status_code=500, detail="Ошибка обработки данных")
        
        logger.info(f"✅ Загружено {len(clients)} новых случайных адресов из {len(df)} доступных")
        logger.debug(f"   Первые адреса: {', '.join([c.address[:30] + '...' for c in clients[:3]])}")
        
        return {"success": True, "clients": [c.model_dump() for c in clients], "total_available": len(df)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки тестовых данных: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка загрузки данных: {str(e)}")


@app.get("/api/all-data")
async def get_all_data():
    """Возвращает ВСЕ 100 адресов для геокодирования"""
    try:
        csv_path = os.path.join(os.path.dirname(__file__), config.CSV_DATA_PATH)
        
        if not os.path.exists(csv_path):
            logger.error(f"❌ CSV файл не найден: {csv_path}")
            raise HTTPException(status_code=500, detail="Файл с данными не найден")
        
        df = pd.read_csv(csv_path)
        logger.info(f"📊 Загружаем ВСЕ {len(df)} адресов из CSV для геокодирования")
        
        if len(df) == 0:
            logger.warning("⚠️ CSV файл пуст")
            raise HTTPException(status_code=500, detail="Нет доступных адресов")
        
        clients = []
        for idx, row in df.iterrows():
            try:
                client = Client(
                    id=idx + 1,
                    address=row['Адрес объекта'],
                    latitude=float(row['Географическая широта']),
                    longitude=float(row['Географическая долгота']),
                    work_start=row['Время начала рабочего дня'],
                    work_end=row['Время окончания рабочего дня'],
                    lunch_start=row['Время начала обеда'],
                    lunch_end=row['Время окончания обеда'],
                    priority=row['Уровень клиента']
                )
                clients.append(client)
            except Exception as e:
                logger.warning(f"⚠️ Ошибка парсинга клиента #{idx + 1}: {str(e)}")
                continue
        
        if len(clients) == 0:
            logger.error("❌ Не удалось загрузить ни одного клиента")
            raise HTTPException(status_code=500, detail="Ошибка обработки данных")
        
        logger.info(f"✅ Загружено {len(clients)} адресов для геокодирования")
        
        return {"success": True, "clients": [c.model_dump() for c in clients], "total": len(clients)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки всех данных: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка загрузки данных: {str(e)}")

# ==================== AUTH ENDPOINTS ====================

@app.post("/api/auth/register", response_model=dict)
async def register(user: UserRegister):
    """Регистрация нового пользователя"""
    try:
        logger.info(f"📝 Попытка регистрации: {user.email}")
        
        new_user = create_user(user.email, user.phone, user.password)
        
        if not new_user:
            logger.warning(f"⚠️ Пользователь с email {user.email} или телефоном {user.phone} уже существует")
            raise HTTPException(
                status_code=400,
                detail="Пользователь с таким email или телефоном уже существует"
            )
        
        # Создаем токен
        access_token = create_access_token({"sub": str(new_user.id)})
        
        logger.info(f"✅ Пользователь зарегистрирован: {new_user.email} (ID: {new_user.id})")
        
        return {
            "success": True,
            "message": "Регистрация успешна",
            "access_token": access_token,
            "token_type": "bearer",
            "user": new_user.model_dump()
        }
    except HTTPException:
        raise
    except ValidationError as e:
        logger.error(f"❌ Ошибка валидации при регистрации: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"❌ Ошибка регистрации: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка сервера при регистрации")


@app.post("/api/auth/login", response_model=dict)
async def login(user: UserLogin):
    """Авторизация пользователя"""
    try:
        logger.info(f"🔐 Попытка входа: {user.login}")
        
        authenticated_user = authenticate_user(user.login, user.password)
        
        if not authenticated_user:
            logger.warning(f"⚠️ Неудачная попытка входа: {user.login}")
            raise HTTPException(
                status_code=401,
                detail="Неверный email/телефон или пароль"
            )
        
        # Создаем токен
        access_token = create_access_token({"sub": str(authenticated_user.id)})
        
        logger.info(f"✅ Пользователь вошел: {authenticated_user.email} (ID: {authenticated_user.id})")
        
        return {
            "success": True,
            "message": "Авторизация успешна",
            "access_token": access_token,
            "token_type": "bearer",
            "user": authenticated_user.model_dump()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка авторизации: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка сервера при авторизации")


@app.get("/api/auth/me", response_model=dict)
async def get_current_user(authorization: Optional[str] = Header(None)):
    """Получение текущего пользователя по токену"""
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Требуется авторизация")
        
        token = authorization.replace("Bearer ", "")
        payload = decode_access_token(token)
        
        if not payload:
            raise HTTPException(status_code=401, detail="Недействительный или истекший токен")
        
        user_id = int(payload.get("sub"))
        user = get_user_by_id(user_id)
        
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        
        return {
            "success": True,
            "user": user.model_dump()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка получения пользователя: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка сервера")


# ==================== USER STATS ENDPOINTS ====================

@app.get("/api/stats/me", response_model=dict)
async def get_my_stats(authorization: Optional[str] = Header(None)):
    """Получение статистики текущего пользователя"""
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Требуется авторизация")
        
        token = authorization.replace("Bearer ", "")
        payload = decode_access_token(token)
        
        if not payload:
            raise HTTPException(status_code=401, detail="Недействительный или истекший токен")
        
        user_id = int(payload.get("sub"))
        stats = get_user_stats(user_id)
        
        logger.info(f"📊 Статистика запрошена для пользователя ID: {user_id}")
        
        return {
            "success": True,
            "stats": stats
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка получения статистики: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка сервера")


class RouteStats(BaseModel):
    """Модель для сохранения статистики маршрута"""
    clients_count: int
    distance: float
    time: int


@app.post("/api/stats/route", response_model=dict)
async def save_route_stats(stats: RouteStats, authorization: Optional[str] = Header(None)):
    """Сохранение статистики построенного маршрута"""
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Требуется авторизация")
        
        token = authorization.replace("Bearer ", "")
        payload = decode_access_token(token)
        
        if not payload:
            raise HTTPException(status_code=401, detail="Недействительный или истекший токен")
        
        user_id = int(payload.get("sub"))
        
        # Обновляем статистику
        update_user_stats(user_id, stats.clients_count, stats.distance, stats.time)
        
        logger.info(f"✅ Статистика обновлена для пользователя ID: {user_id} | +{stats.clients_count} клиентов, +{stats.distance:.1f} км")
        
        return {
            "success": True,
            "message": "Статистика обновлена"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения статистики: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка сервера")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


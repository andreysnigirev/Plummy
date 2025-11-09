"""
Централизованный Rate Limiter для соблюдения лимитов API
"""
import asyncio
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Централизованный rate limiter для API запросов
    
    Обеспечивает:
    - Строгое соблюдение лимита (0.5 req/sec = 2 сек между запросами)
    - Адаптивный backoff при 429 ошибках
    - Thread-safe операции
    """
    
    def __init__(self, requests_per_second: float = 0.5):
        """
        Args:
            requests_per_second: Максимальное количество запросов в секунду
        """
        self.requests_per_second = requests_per_second
        self.min_interval = 1.0 / requests_per_second  # 2.0 секунды для 0.5 req/sec
        self.last_request_time: Optional[float] = None
        self.total_requests = 0
        self.rate_limit_errors = 0
        self._lock = asyncio.Lock()
        
        logger.info(f"🚦 RateLimiter инициализирован: {requests_per_second} req/sec (интервал {self.min_interval} сек)")
    
    async def acquire(self):
        """
        Ожидает разрешение на выполнение запроса
        Автоматически добавляет задержку если нужно
        """
        async with self._lock:
            current_time = time.time()
            
            if self.last_request_time is not None:
                elapsed = current_time - self.last_request_time
                wait_time = self.min_interval - elapsed
                
                if wait_time > 0:
                    logger.debug(f"⏳ Rate limit: ожидание {wait_time:.2f} сек")
                    await asyncio.sleep(wait_time)
                    current_time = time.time()
            
            self.last_request_time = current_time
            self.total_requests += 1
            
            if self.total_requests % 100 == 0:
                logger.info(f"📊 API запросов выполнено: {self.total_requests}")
    
    async def handle_rate_limit_error(self, wait_time: int = 30):
        """
        Обработка 429 ошибки (rate limit exceeded)
        
        Args:
            wait_time: Время ожидания в секундах (по умолчанию 30)
        """
        self.rate_limit_errors += 1
        logger.warning(f"⚠️  429 Rate Limit Error #{self.rate_limit_errors}")
        logger.info(f"⏳ Ожидание {wait_time} секунд перед продолжением...")
        
        await asyncio.sleep(wait_time)
        
        # Сбрасываем счетчик для нового отсчета
        self.last_request_time = time.time()
    
    def get_stats(self) -> dict:
        """Возвращает статистику использования"""
        return {
            'total_requests': self.total_requests,
            'rate_limit_errors': self.rate_limit_errors,
            'requests_per_second': self.requests_per_second,
            'min_interval': self.min_interval
        }
    
    def estimate_time(self, num_requests: int) -> float:
        """
        Оценивает время выполнения для заданного количества запросов
        
        Args:
            num_requests: Количество запросов
            
        Returns:
            Оценка времени в секундах
        """
        return num_requests * self.min_interval
    
    def format_eta(self, num_requests: int) -> str:
        """
        Форматирует ETA (estimated time of arrival) в читаемый формат
        
        Args:
            num_requests: Количество запросов
            
        Returns:
            Строка вида "2ч 15мин" или "45мин" или "30сек"
        """
        total_seconds = self.estimate_time(num_requests)
        
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        seconds = int(total_seconds % 60)
        
        if hours > 0:
            return f"{hours}ч {minutes}мин"
        elif minutes > 0:
            return f"{minutes}мин {seconds}сек"
        else:
            return f"{seconds}сек"


# Глобальный экземпляр rate limiter
rate_limiter = RateLimiter(requests_per_second=0.5)


async def with_rate_limit(func, *args, **kwargs):
    """
    Декоратор-хелпер для выполнения функции с rate limiting
    
    Пример:
        result = await with_rate_limit(scraper.get_product_detail, session, spu_id)
    """
    await rate_limiter.acquire()
    return await func(*args, **kwargs)


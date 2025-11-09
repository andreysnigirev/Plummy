"""
API клиент для Poizon (dewu)
Получение данных о товарах через официальное API
"""
import aiohttp
import asyncio
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class PoizonScraper:
    """Клиент для работы с Poizon API"""
    
    def __init__(self, api_key: str):
        """
        Инициализация клиента
        
        Args:
            api_key: API ключ для доступа к Poizon API
        """
        self.api_key = api_key
        self.base_url = "https://poizon-api.com"
        self.api_requests = 0
        self.successful_requests = 0
        
    def get_headers(self, include_content_type: bool = False) -> dict:
        """Возвращает заголовки для API запросов
        
        Args:
            include_content_type: Включить ли Content-Type (для POST запросов)
        """
        headers = {
            "x-api-key": self.api_key,
            "Accept": "application/json"
        }
        
        if include_content_type:
            headers["Content-Type"] = "application/json"
        
        return headers
    
    async def search_products(self, session: aiohttp.ClientSession, 
                             keyword: str = "nike", 
                             page: int = 1, 
                             limit: int = 50) -> List[Dict]:
        """
        Поиск товаров по ключевому слову
        
        Args:
            session: aiohttp сессия
            keyword: Ключевое слово для поиска
            page: Номер страницы
            limit: Количество товаров на странице
            
        Returns:
            List[Dict]: Список товаров
        """
        try:
            self.api_requests += 1
            
            url = f"{self.base_url}/api/dewu/searchProducts"
            params = {
                "keyword": keyword,
                "limit": limit,
                "page": page
            }
            
            logger.info(f"🌐 API запрос: поиск товаров (keyword={keyword}, page={page}, limit={limit})")
            
            async with session.get(url, params=params, headers=self.get_headers(),  # Content-Type не нужен для GET запросов 
                                  timeout=30, ssl=False) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    if isinstance(data, dict) and 'productList' in data:
                        products = data['productList']
                        total = data.get('total', 0)
                        
                        self.successful_requests += 1
                        logger.info(f"✅ Получено {len(products)} товаров (всего: {total})")
                        
                        return products
                    else:
                        logger.error(f"❌ Неожиданная структура ответа: {type(data)}")
                        return []
                else:
                    error_text = await response.text()
                    logger.error(f"❌ Ошибка API {response.status}: {error_text[:200]}")
                    return []
                    
        except Exception as e:
            logger.error(f"❌ Ошибка поиска товаров: {e}")
            return []
    
    async def get_price_info(self, session: aiohttp.ClientSession,
                             spu_id: str, max_retries: int = 3) -> Optional[Dict]:
        """
        Получение детальной информации о ценах через /priceInfo endpoint
        
        Args:
            session: aiohttp сессия
            spu_id: ID товара (SPU)
            max_retries: Максимум попыток при ошибке 429
            
        Returns:
            Optional[Dict]: Данные о ценах или None
        """
        for attempt in range(max_retries):
            try:
                self.api_requests += 1
                
                url = f"{self.base_url}/api/dewu/priceInfo"
                params = {"spuId": spu_id}
                
                if attempt > 0:
                    logger.info(f"🔄 Повторная попытка {attempt + 1}/{max_retries} для priceInfo {spu_id}")
                else:
                    logger.info(f"🌐 API запрос (priceInfo): цены для spuId={spu_id}")
                
                async with session.get(url, params=params, headers=self.get_headers(),  # Content-Type не нужен для GET запросов
                                      timeout=20, ssl=False) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        if isinstance(data, dict):
                            self.successful_requests += 1
                            logger.info(f"✅ Получены цены для товара {spu_id} через priceInfo")
                            return data
                        else:
                            logger.error(f"❌ Неожиданная структура ответа priceInfo для {spu_id}")
                            return None
                            
                    elif response.status == 404:
                        logger.warning(f"⚠️ Цены для {spu_id} не найдены")
                        return None
                        
                    elif response.status == 429:
                        error_text = await response.text()
                        logger.warning(f"⚠️ Rate limit (429) для priceInfo {spu_id}: {error_text[:100]}")
                        
                        if attempt < max_retries - 1:
                            wait_time = 5 + (attempt * 5)
                            logger.info(f"⏳ Ожидание {wait_time} сек перед повтором...")
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            logger.error(f"❌ Превышено количество попыток для priceInfo {spu_id}")
                            return None
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ Ошибка API priceInfo {response.status} для {spu_id}: {error_text[:200]}")
                        return None
                        
            except Exception as e:
                logger.error(f"❌ Ошибка получения priceInfo для {spu_id}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
                    continue
                return None
        
        return None
    
    async def get_product_detail_with_price(self, session: aiohttp.ClientSession,
                                            spu_id: str, max_retries: int = 3) -> Optional[Dict]:
        """
        Получение детальной информации о товаре с ценами для каждого размера
        Использует endpoint /productDetailWithPrice для получения точных цен
        
        Args:
            session: aiohttp сессия
            spu_id: ID товара (SPU)
            max_retries: Максимум попыток при ошибке 429
            
        Returns:
            Optional[Dict]: Данные товара с детальными ценами или None
        """
        for attempt in range(max_retries):
            try:
                self.api_requests += 1
                
                url = f"{self.base_url}/api/dewu/productDetailWithPrice"
                params = {"spuId": spu_id}
                
                if attempt > 0:
                    logger.info(f"🔄 Повторная попытка {attempt + 1}/{max_retries} для {spu_id}")
                else:
                    logger.info(f"🌐 API запрос (с ценами): детали товара (spuId={spu_id})")
                
                async with session.get(url, params=params, headers=self.get_headers(),  # Content-Type не нужен для GET запросов
                                      timeout=20, ssl=False) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        if isinstance(data, dict):
                            self.successful_requests += 1
                            logger.info(f"✅ Получены детали товара {spu_id} с ценами")
                            return data
                        else:
                            logger.error(f"❌ Неожиданная структура ответа для {spu_id}")
                            return None
                            
                    elif response.status == 404:
                        logger.warning(f"⚠️ Товар {spu_id} не найден")
                        return None
                        
                    elif response.status == 429:
                        error_text = await response.text()
                        logger.warning(f"⚠️ Rate limit (429) для {spu_id}: {error_text[:100]}")
                        
                        if attempt < max_retries - 1:
                            wait_time = 5 + (attempt * 5)
                            logger.info(f"⏳ Ожидание {wait_time} сек перед повтором...")
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            logger.error(f"❌ Превышено количество попыток для {spu_id}")
                            return None
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ Ошибка API {response.status} для {spu_id}: {error_text[:200]}")
                        return None
                        
            except Exception as e:
                logger.error(f"❌ Ошибка получения деталей товара {spu_id}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
                    continue
                return None
        
        return None
    
    async def get_product_detail(self, session: aiohttp.ClientSession, 
                                 spu_id: str, max_retries: int = 3) -> Optional[Dict]:
        """
        Получение детальной информации о товаре
        
        Args:
            session: aiohttp сессия
            spu_id: ID товара (SPU)
            max_retries: Максимум попыток при ошибке 429
            
        Returns:
            Optional[Dict]: Данные товара или None
        """
        for attempt in range(max_retries):
            try:
                self.api_requests += 1
                
                url = f"{self.base_url}/api/dewu/productDetail"
                params = {"spuId": spu_id}
                
                if attempt > 0:
                    logger.info(f"🔄 Повторная попытка {attempt + 1}/{max_retries} для {spu_id}")
                else:
                    logger.info(f"🌐 API запрос: детали товара (spuId={spu_id})")
                
                async with session.get(url, params=params, headers=self.get_headers(),  # Content-Type не нужен для GET запросов
                                      timeout=20, ssl=False) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        if isinstance(data, dict):
                            self.successful_requests += 1
                            logger.info(f"✅ Получены детали товара {spu_id}")
                            return data
                        else:
                            logger.error(f"❌ Неожиданная структура ответа для {spu_id}")
                            return None
                            
                    elif response.status == 404:
                        logger.warning(f"⚠️ Товар {spu_id} не найден")
                        return None
                        
                    elif response.status == 429:
                        error_text = await response.text()
                        logger.warning(f"⚠️ Rate limit (429) для {spu_id}: {error_text[:100]}")
                        
                        if attempt < max_retries - 1:
                            wait_time = 5 + (attempt * 5)  # 5, 10, 15 секунд
                            logger.info(f"⏳ Ожидание {wait_time} сек перед повтором...")
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            logger.error(f"❌ Превышено количество попыток для {spu_id}")
                            logger.error(f"💡 СОВЕТ: API Poizon возвращает ошибку 429 'Очередь переполнена'")
                            logger.error(f"   Это может означать:")
                            logger.error(f"   1. Слишком частые запросы - увеличьте задержки")
                            logger.error(f"   2. API перегружен - попробуйте позже")
                            logger.error(f"   3. Проблема с API ключом - проверьте ключ")
                            return None
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ Ошибка API {response.status} для {spu_id}: {error_text[:200]}")
                        return None
                        
            except Exception as e:
                logger.error(f"❌ Ошибка получения деталей товара {spu_id}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
                    continue
                return None
        
        return None
    
    async def get_products_by_article_list(self, session: aiohttp.ClientSession,
                                          article_list: List[str]) -> List[Dict]:
        """
        Получение товаров по списку артикулов
        
        Args:
            session: aiohttp сессия
            article_list: Список SPU ID для загрузки
            
        Returns:
            List[Dict]: Список товаров с деталями
        """
        products = []
        
        logger.info(f"📋 Загрузка {len(article_list)} товаров по артикулам")
        
        for i, spu_id in enumerate(article_list, 1):
            logger.info(f"🎯 Товар {i}/{len(article_list)}: {spu_id}")
            
            # Шаг 1: Получаем базовые детали товара
            product_detail = await self.get_product_detail(session, spu_id)
            
            if not product_detail:
                logger.warning(f"⚠️ Товар {spu_id} пропущен - нет базовых данных")
                await asyncio.sleep(1.5)
                continue
            
            # Шаг 2: Получаем детальную информацию о ценах через /priceInfo
            await asyncio.sleep(0.5)  # Небольшая пауза между запросами
            price_info = await self.get_price_info(session, spu_id)
            
            if price_info:
                # Объединяем данные о ценах с основными данными
                # priceInfo возвращает структуру {"skus": {...}}
                logger.info(f"🔗 Объединяем данные товара и цен для {spu_id}")
                product_detail['priceInfo'] = price_info
            else:
                logger.warning(f"⚠️ Для товара {spu_id} не удалось получить детальные цены")
            
            # Добавляем SPU ID для удобства
            product_detail['spuId'] = spu_id
            products.append(product_detail)
            
            # Увеличенная пауза между товарами для избежания rate limit
            await asyncio.sleep(1.5)
        
        logger.info(f"✅ Загружено {len(products)}/{len(article_list)} товаров")
        return products
    
    def get_efficiency(self) -> float:
        """Возвращает эффективность API запросов (% успешных)"""
        if self.api_requests == 0:
            return 0.0
        return (self.successful_requests / self.api_requests) * 100
    
    def get_stats(self) -> Dict:
        """Возвращает статистику API запросов"""
        return {
            "total_requests": self.api_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.api_requests - self.successful_requests,
            "efficiency_percent": self.get_efficiency()
        }


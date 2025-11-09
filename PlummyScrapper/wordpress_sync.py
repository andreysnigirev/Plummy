"""
Синхронизация базы данных с WordPress/WooCommerce
Создание, обновление и удаление товаров на сайте
"""
import asyncio
import aiohttp
import logging
import traceback
from typing import List, Dict, Optional
from database import db, Product, SyncAction, SyncStatus
from price_calculator import price_calculator

logger = logging.getLogger(__name__)


class WordPressSync:
    """Синхронизатор товаров с WordPress"""
    
    def __init__(self, wp_url: str, wp_key: str, wp_secret: str):
        """
        Инициализация синхронизатора
        
        Args:
            wp_url: URL WordPress сайта
            wp_key: Consumer Key для WooCommerce API
            wp_secret: Consumer Secret для WooCommerce API
        """
        self.wp_url = wp_url.rstrip('/')
        self.wp_key = wp_key
        self.wp_secret = wp_secret
        
        self.created_count = 0
        self.updated_count = 0
        self.deleted_count = 0
        self.failed_count = 0
        
        # Загружаем маппинг категорий один раз
        self.category_mapping = self._load_category_mapping()
    
    def _load_category_mapping(self):
        """
        Загружает маппинг категорий Dewu → WooCommerce
        
        ПРИМЕЧАНИЕ: Больше не используем category_mapping.json
        Категории теперь берутся из plummy_categories.json и указываются
        пользователем при добавлении артикула через category_ids
        """
        # Возвращаем пустой маппинг - категории теперь хранятся в articles.json
        logger.info(f"ℹ️  Маппинг категорий не используется (категории в articles.json)")
        return {}
    
    def get_auth(self):
        """Возвращает BasicAuth для WooCommerce"""
        from aiohttp import BasicAuth
        return BasicAuth(self.wp_key, self.wp_secret)
    
    async def get_wp_categories(self, session: aiohttp.ClientSession) -> List[Dict]:
        """
        Получает список всех категорий из WooCommerce
        
        Args:
            session: aiohttp сессия
            
        Returns:
            List[Dict]: Список категорий с полями id, name, slug, parent
        """
        categories = []
        page = 1
        per_page = 100
        
        logger.info("📂 Получаем список категорий из WooCommerce...")
        
        try:
            while True:
                url = f"{self.wp_url}/wp-json/wc/v3/products/categories"
                params = {
                    "page": page,
                    "per_page": per_page,
                    "hide_empty": 0  # Показывать пустые категории (0 = false)
                }
                
                async with session.get(url, params=params, auth=self.get_auth()) as response:
                    if response.status == 200:
                        page_categories = await response.json()
                        
                        if not page_categories:
                            break
                        
                        for cat in page_categories:
                            categories.append({
                                'id': cat['id'],
                                'name': cat['name'],
                                'slug': cat['slug'],
                                'parent': cat['parent']
                            })
                        
                        logger.info(f"  📄 Страница {page}: {len(page_categories)} категорий")
                        page += 1
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ Ошибка получения категорий: {response.status}")
                        logger.error(f"   {error_text[:200]}")
                        break
            
            logger.info(f"✅ Всего категорий загружено: {len(categories)}")
            return categories
            
        except Exception as e:
            logger.error(f"❌ Ошибка при загрузке категорий: {e}")
            return []
    
    async def get_wp_products(self, session: aiohttp.ClientSession) -> Dict[str, int]:
        """
        Получает список всех товаров из WordPress
        
        Args:
            session: aiohttp сессия
            
        Returns:
            Dict[str, int]: Словарь {spu_id: wp_product_id}
        """
        wp_products = {}
        page = 1
        per_page = 100
        
        logger.info("🔍 Получаем список товаров из WordPress...")
        print("🔍 Получаем список товаров из WordPress...")
        
        max_retries = 3
        base_retry_delay = 3
        
        try:
            while True:
                url = f"{self.wp_url}/wp-json/wc/v3/products"
                params = {
                    "page": page,
                    "per_page": per_page,
                    "status": "any"
                }
                
                # Retry логика для получения товаров
                success = False
                is_last_page = False
                for attempt in range(max_retries):
                    try:
                        # Увеличенный timeout: 120 сек (может быть много товаров!)
                        timeout_value = 120
                        
                        async with session.get(url, params=params, auth=self.get_auth(), 
                                              timeout=timeout_value) as response:
                            if response.status == 200:
                                products = await response.json()
                                
                                if not products:
                                    success = True
                                    is_last_page = True
                                    break  # Больше нет товаров
                                
                                # Извлекаем SPU ID из meta_data
                                for product in products:
                                    meta_data = product.get('meta_data', [])
                                    spu_id = None
                                    
                                    for meta in meta_data:
                                        if meta.get('key') == 'spu_id':
                                            spu_id = meta.get('value')
                                            break
                                    
                                    if spu_id:
                                        wp_products[spu_id] = product.get('id')
                                
                                # Прогресс с общим количеством
                                logger.info(f"📄 Страница {page}: получено {len(products)} товаров (всего: {len(wp_products)})")
                                print(f"📄 Страница {page}: получено {len(products)} товаров (всего: {len(wp_products)})")
                                
                                success = True
                                
                                if len(products) < per_page:
                                    # Последняя страница - выходим из обоих циклов
                                    is_last_page = True
                                    break
                                
                                # Переходим к следующей странице
                                page += 1
                                await asyncio.sleep(0.1)
                                break  # Выходим из retry loop
                            
                            # Временные ошибки сервера
                            elif response.status in [502, 503, 504]:
                                if attempt < max_retries - 1:
                                    retry_delay = base_retry_delay * (2 ** attempt)
                                    logger.warning(f"⚠️  HTTP {response.status} при получении страницы {page}, попытка {attempt + 1}/{max_retries}")
                                    logger.warning(f"   Ждём {retry_delay} сек...")
                                    print(f"⚠️  HTTP {response.status} при получении страницы {page}, попытка {attempt + 1}/{max_retries}")
                                    print(f"   Ждём {retry_delay} сек...")
                                    await asyncio.sleep(retry_delay)
                                    continue
                                else:
                                    logger.error(f"❌ HTTP {response.status} после {max_retries} попыток")
                                    print(f"❌ HTTP {response.status} после {max_retries} попыток")
                                    return wp_products  # Возвращаем что успели получить
                            
                            # Другие ошибки
                            else:
                                logger.error(f"❌ Ошибка получения товаров: HTTP {response.status}")
                                return wp_products  # Возвращаем что успели получить
                    
                    except asyncio.TimeoutError:
                        if attempt < max_retries - 1:
                            retry_delay = base_retry_delay * (2 ** attempt)
                            logger.warning(f"⚠️  Таймаут ({timeout_value}сек) при получении страницы {page}, попытка {attempt + 1}/{max_retries}")
                            logger.warning(f"   Ждём {retry_delay} сек...")
                            print(f"⚠️  Таймаут ({timeout_value}сек) при получении страницы {page}, попытка {attempt + 1}/{max_retries}")
                            print(f"   Ждём {retry_delay} сек...")
                            await asyncio.sleep(retry_delay)
                            continue
                        else:
                            logger.error(f"❌ Таймаут после {max_retries} попыток для страницы {page}")
                            print(f"❌ Таймаут после {max_retries} попыток для страницы {page}")
                            return wp_products  # Возвращаем что успели получить
                    
                    except Exception as e:
                        if attempt < max_retries - 1:
                            retry_delay = base_retry_delay * (2 ** attempt)
                            logger.warning(f"⚠️  Ошибка при получении страницы {page}: {e}, попытка {attempt + 1}/{max_retries}")
                            logger.warning(f"   Ждём {retry_delay} сек...")
                            await asyncio.sleep(retry_delay)
                            continue
                        else:
                            logger.error(f"❌ Ошибка после {max_retries} попыток: {e}")
                            return wp_products  # Возвращаем что успели получить
                
                # Если не успешно после всех попыток, выходим
                if not success:
                    break
                
                # Если это была последняя страница, выходим
                if is_last_page:
                    break
            
            logger.info(f"✅ Всего товаров в WordPress: {len(wp_products)}")
            print(f"✅ Всего товаров в WordPress: {len(wp_products)}\n")
            return wp_products
            
        except Exception as e:
            logger.error(f"❌ Общая ошибка получения товаров из WordPress: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return wp_products  # Возвращаем что успели получить
    
    async def create_product_in_wp(self, session: aiohttp.ClientSession, 
                                   product: Product) -> Optional[int]:
        """
        Создает товар в WordPress
        
        Args:
            session: aiohttp сессия
            product: Объект товара из БД
            
        Returns:
            Optional[int]: ID созданного товара или None
        """
        try:
            # КРИТИЧНО: Проверяем наличие хотя бы ОДНОГО размера в наличии
            available_variants = [v for v in product.variants if v.is_available and v.stock_status == 1]
            
            if not available_variants:
                logger.warning(f"⚠️ Товар {product.spu_id}: НЕТ размеров в наличии - НЕ создаем на сайте!")
                return None
            
            # Собираем ВСЕ размеры для атрибута (включая недоступные, но создаем варианты для всех)
            sizes = [v.size_eu for v in product.variants]
            
            # Сначала определяем категории
            # Используем ВСЕ категории из product.category_ids (отфильтрованные по размерам)
            category_ids_to_send = []
            
            if product.category_ids and len(product.category_ids) > 0:
                # Используем отфильтрованные категории из БД (конвертируем в int!)
                category_ids_to_send = [int(cid) for cid in product.category_ids]
                logger.info(f"📂 Категории WC (из БД): {category_ids_to_send}")
            else:
                # Fallback: используем category_id или определяем по типу размера
                category_id = product.category_id
                
                if not category_id:
                    # Определяем по типу размера из вариантов
                    size_type = product.variants[0].size_type.value if product.variants else 'shoes'
                    if size_type == 'shoes':
                        category_id = 103  # По умолчанию "Кроссовки и кеды"
                    else:
                        category_id = 105  # По умолчанию "Одежда"
                    logger.info(f"📂 Категория (fallback по типу): {category_id}")
                else:
                    logger.info(f"📂 Категория WC: {category_id}")
                
                category_ids_to_send = [category_id]
            
            # ОПРЕДЕЛЯЕМ ТИП АТРИБУТА РАЗМЕРА ПО КАТЕГОРИЯМ (НЕ ПО API DEWU!)
            from category_filter import get_size_attribute_id_for_categories
            size_attr_id = get_size_attribute_id_for_categories(category_ids_to_send)
            logger.info(f"📏 Атрибут размера: {size_attr_id} ({'pa_shoe_size' if size_attr_id == 4 else 'pa_clothing_size'})")
            
            # Для расчета цен берем первую категорию
            primary_category_id = category_ids_to_send[0] if category_ids_to_send else 103
            
            # Получаем варианты доставки
            delivery_options = price_calculator.get_delivery_options()
            
            # Payload для создания товара
            payload = {
                "name": product.title,
                "type": "variable",
                "status": "publish",
                "catalog_visibility": "visible",
                "categories": [{"id": cat_id} for cat_id in category_ids_to_send],
                # Для вариативного товара НЕ управляем запасами на уровне родителя
                "manage_stock": False,
                "backorders": "no",
                "attributes": [
                    {
                        "id": 1,  # Бренд
                        "options": [product.brand] if product.brand else ["Unknown"],
                        "variation": False,
                        "visible": True
                    },
                    {
                        "id": size_attr_id,  # Размер
                        "options": sizes,
                        "variation": True,
                        "visible": True
                    },
                    {
                        "id": 6,  # pa_days (Срок доставки)
                        "options": delivery_options,
                        "variation": True,
                        "visible": True
                    }
                ],
                "meta_data": [
                    {"key": "spu_id", "value": product.spu_id},
                    {"key": "article_number", "value": product.article_number},
                    {"key": "_product_brand", "value": product.brand if product.brand else ""}
                ]
            }
            
            # ОПТИМИЗАЦИЯ: НЕ добавляем изображения при создании (чтобы избежать таймаута)
            # Изображения добавим ПОСЛЕ создания товара отдельным запросом
            image_objects = []
            if product.images and isinstance(product.images, list):
                for img_url in product.images[:5]:  # Максимум 5 изображений для скорости
                    if isinstance(img_url, str) and img_url.strip():
                        image_objects.append({"src": img_url.strip()})
            
            # Создаем родительский товар БЕЗ изображений (быстрее!)
            url = f"{self.wp_url}/wp-json/wc/v3/products"
            
            # RETRY ЛОГИКА: 3 попытки для временных ошибок сервера
            max_retries = 3
            base_retry_delay = 3  # базовая задержка между попытками
            
            for attempt in range(max_retries):
                try:
                    # Увеличиваем timeout: 120 сек для первой попытки, 180 для последующих
                    timeout_value = 120 if attempt == 0 else 180
                    
                    async with session.post(url, json=payload, auth=self.get_auth(),
                                           timeout=timeout_value) as response:
                        if response.status == 201:
                            data = await response.json()
                            parent_id = data.get('id')
                            
                            logger.info(f"✅ Создан товар в WP: ID {parent_id} ({product.title[:50]}...)")
                            
                            # ДОБАВЛЯЕМ ИЗОБРАЖЕНИЯ отдельно (если есть)
                            if image_objects:
                                # Задержка перед добавлением изображений (чтобы WordPress успел обработать создание)
                                await asyncio.sleep(2)
                                
                                # RETRY для добавления изображений
                                img_max_retries = 3
                                img_added = False
                                
                                for img_attempt in range(img_max_retries):
                                    try:
                                        msg = f"   🖼️ Добавляем {len(image_objects)} изображений (попытка {img_attempt + 1}/{img_max_retries})..."
                                        logger.info(msg)
                                        print(msg, flush=True)  # ВЫВОД В КОНСОЛЬ С FLUSH
                                        
                                        update_url = f"{self.wp_url}/wp-json/wc/v3/products/{parent_id}"
                                        image_payload = {"images": image_objects}
                                        
                                        # Увеличенный timeout: 180 сек (3 мин) для изображений
                                        img_timeout = aiohttp.ClientTimeout(total=180)
                                        async with session.put(update_url, json=image_payload, 
                                                              auth=self.get_auth(), timeout=img_timeout) as img_response:
                                            if img_response.status == 200:
                                                success_msg = f"      ✅ Изображения добавлены!"
                                                logger.info(success_msg)
                                                print(success_msg, flush=True)  # ВЫВОД В КОНСОЛЬ С FLUSH
                                                img_added = True
                                                break
                                            else:
                                                error_text = await img_response.text()
                                                error_msg = f"      ⚠️  HTTP {img_response.status}: {error_text[:200]}"
                                                logger.warning(error_msg)
                                                print(error_msg, flush=True)  # ВЫВОД В КОНСОЛЬ С FLUSH
                                                if img_attempt < img_max_retries - 1:
                                                    print(f"      ⏳ Ждем 5 сек перед повтором...", flush=True)
                                                    await asyncio.sleep(5)  # Задержка перед повтором
                                    
                                    except asyncio.TimeoutError:
                                        err_msg = f"      ⚠️  Таймаут (180 сек) при добавлении изображений"
                                        logger.warning(err_msg)
                                        print(err_msg, flush=True)  # ВЫВОД В КОНСОЛЬ С FLUSH
                                        if img_attempt < img_max_retries - 1:
                                            print(f"      ⏳ Ждем 5 сек перед повтором...", flush=True)
                                            await asyncio.sleep(5)
                                    
                                    except Exception as img_e:
                                        err_msg = f"      ⚠️  Ошибка: {type(img_e).__name__}: {str(img_e)[:200]}"
                                        logger.warning(err_msg)
                                        print(err_msg, flush=True)  # ВЫВОД В КОНСОЛЬ С FLUSH
                                        if img_attempt < img_max_retries - 1:
                                            print(f"      ⏳ Ждем 5 сек перед повтором...", flush=True)
                                            await asyncio.sleep(5)
                                
                                if not img_added:
                                    fail_msg = f"      ❌ НЕ УДАЛОСЬ добавить изображения после {img_max_retries} попыток!"
                                    logger.error(fail_msg)
                                    print(fail_msg, flush=True)  # ВЫВОД В КОНСОЛЬ С FLUSH
                                    # Продолжаем без изображений - не критично!
                            
                            # Создаем вариации (размеры)
                            await self.create_variations(session, parent_id, product, primary_category_id)
                            
                            self.created_count += 1
                            return parent_id
                        
                        # ВРЕМЕННЫЕ ОШИБКИ СЕРВЕРА - повторяем попытку
                        elif response.status in [502, 503, 504]:
                            error_text = await response.text()
                            if attempt < max_retries - 1:
                                # Exponential backoff: 3, 6, 12 секунд
                                retry_delay = base_retry_delay * (2 ** attempt)
                                logger.warning(f"⚠️  HTTP {response.status} для {product.spu_id}, попытка {attempt + 1}/{max_retries}")
                                logger.warning(f"   Ждём {retry_delay} сек перед повтором...")
                                await asyncio.sleep(retry_delay)
                                continue  # Повторяем попытку
                            else:
                                logger.error(f"❌ HTTP {response.status} для {product.spu_id} после {max_retries} попыток")
                                logger.error(f"   Ответ: {error_text[:200]}")
                                logger.warning(f"⚠️  Пропускаем товар {product.spu_id}, продолжаем со следующим")
                                return None
                        
                        # ДРУГИЕ ОШИБКИ - не повторяем
                        else:
                            error_text = await response.text()
                            logger.error(f"❌ Ошибка создания товара {product.spu_id}: HTTP {response.status}")
                            logger.error(f"   Ответ: {error_text[:200]}")
                            logger.warning(f"⚠️  Пропускаем товар {product.spu_id}, продолжаем со следующим")
                            return None
                
                except asyncio.TimeoutError:
                    if attempt < max_retries - 1:
                        # Exponential backoff: 3, 6, 12 секунд
                        retry_delay = base_retry_delay * (2 ** attempt)
                        logger.warning(f"⚠️  Таймаут ({timeout_value}сек) для {product.spu_id}, попытка {attempt + 1}/{max_retries}")
                        logger.warning(f"   Ждём {retry_delay} сек перед повтором...")
                        await asyncio.sleep(retry_delay)
                        continue  # Повторяем попытку
                    else:
                        logger.error(f"❌ Таймаут при создании товара {product.spu_id} после {max_retries} попыток")
                        logger.warning(f"⚠️  Пропускаем товар {product.spu_id}, продолжаем со следующим")
                        return None
                
                except Exception as e:
                    if attempt < max_retries - 1:
                        # Exponential backoff: 3, 6, 12 секунд
                        retry_delay = base_retry_delay * (2 ** attempt)
                        logger.warning(f"⚠️  Ошибка для {product.spu_id}: {e}, попытка {attempt + 1}/{max_retries}")
                        logger.warning(f"   Ждём {retry_delay} сек перед повтором...")
                        await asyncio.sleep(retry_delay)
                        continue  # Повторяем попытку
                    else:
                        logger.error(f"❌ Ошибка при создании товара {product.spu_id} после {max_retries} попыток: {e}")
                        logger.warning(f"⚠️  Пропускаем товар {product.spu_id}, продолжаем со следующим")
                        return None
            
            return None
                    
        except Exception as e:
            logger.error(f"❌ Ошибка создания товара {product.spu_id} в WP: {e}")
            return None
    
    async def create_variations(self, session: aiohttp.ClientSession,
                               parent_id: int, product: Product, category_id_for_price: int = None):
        """
        Создает вариации (размеры × сроки доставки) для товара
        
        Args:
            session: aiohttp сессия
            parent_id: ID родительского товара в WP
            product: Объект товара из БД
            category_id_for_price: ID категории для расчета цен
        """
        try:
            # ОПРЕДЕЛЯЕМ ТИП АТРИБУТА РАЗМЕРА ПО КАТЕГОРИЯМ (НЕ ПО API DEWU!)
            from category_filter import get_size_attribute_id_for_categories
            
            # Используем категории из product.category_ids (конвертируем в int!)
            category_ids_to_use = [int(cid) for cid in product.category_ids] if (product.category_ids and len(product.category_ids) > 0) else [category_id_for_price or 103]
            size_attr_id = get_size_attribute_id_for_categories(category_ids_to_use)
            logger.debug(f"📏 Атрибут размера для вариаций: {size_attr_id} ({'pa_shoe_size' if size_attr_id == 4 else 'pa_clothing_size'})")
            
            # Используем переданную категорию для расчета цен
            category_id = category_id_for_price or product.category_id or 103
            
            delivery_options = price_calculator.get_delivery_options()
            
            variations = []
            for variant in product.variants:
                # ВАЖНО: Создаем ВСЕ варианты, даже без наличия!
                # Для недоступных устанавливаем stock_status = "outofstock"
                
                # Создаем ДВЕ вариации для каждого размера (разные сроки доставки)
                for delivery_days in delivery_options:
                    # Рассчитываем цену по формуле для категории и срока доставки
                    price_rub = price_calculator.calculate_price(
                        variant.price_cny,
                        category_id,
                        delivery_days
                    )
                    
                    price_str = str(int(price_rub))
                    
                    # Определяем наличие и статус
                    is_in_stock = variant.is_available and variant.stock_status == 1
                    stock_status = "instock" if is_in_stock else "outofstock"
                    stock_quantity = 50 if is_in_stock else 0
                    
                    variation_data = {
                        "regular_price": price_str,
                        "sale_price": price_str,
                        "manage_stock": True,
                        "stock_quantity": stock_quantity,
                        "stock_status": stock_status,
                        "attributes": [
                            {"id": size_attr_id, "option": variant.size_eu},
                            {"id": 6, "option": delivery_days}  # pa_days
                        ]
                    }
                    variations.append(variation_data)
                    
                    # ДЕТАЛЬНЫЙ ЛОГ того что отправляем
                    availability = "✅ в наличии" if is_in_stock else "❌ нет в наличии"
                    logger.info(f"      Вариация: {variant.size_eu} EU / {delivery_days} → {price_str} RUB ({availability})")
            
            logger.info(f"   📤 Отправляем {len(variations)} вариаций в WordPress...")
            
            # Batch создание вариаций
            url = f"{self.wp_url}/wp-json/wc/v3/products/{parent_id}/variations/batch"
            payload = {"create": variations}
            
            # RETRY ЛОГИКА для вариаций
            max_retries = 3
            base_retry_delay = 3
            
            for attempt in range(max_retries):
                try:
                    # Увеличенный timeout: 120 сек (вариаций может быть много)
                    timeout_value = 120
                    
                    async with session.post(url, json=payload, auth=self.get_auth(),
                                           timeout=timeout_value) as response:
                        if response.status == 200:
                            data = await response.json()
                            created = len(data.get('create', []))
                            logger.info(f"   📦 Создано {created} вариаций для товара {parent_id}")
                            
                            # ДЕТАЛЬНАЯ ПРОВЕРКА: Выводим первые 3 созданные вариации
                            created_variations = data.get('create', [])
                            if created_variations and len(created_variations) > 0:
                                for i, var in enumerate(created_variations[:3], 1):
                                    var_id = var.get('id')
                                    var_price = var.get('regular_price')
                                    var_attrs = var.get('attributes', [])
                                    size_str = next((a['option'] for a in var_attrs if a.get('id') == size_attr_id), '?')
                                    days_str = next((a['option'] for a in var_attrs if a.get('id') == 6), '?')
                                    logger.debug(f"      [{i}] Вариация {var_id}: {size_str} EU, {days_str}, {var_price} RUB")
                            return  # Успешно создали
                        
                        # ВРЕМЕННЫЕ ОШИБКИ СЕРВЕРА - повторяем попытку
                        elif response.status in [502, 503, 504]:
                            if attempt < max_retries - 1:
                                retry_delay = base_retry_delay * (2 ** attempt)
                                logger.warning(f"⚠️  HTTP {response.status} при создании вариаций для {parent_id}, попытка {attempt + 1}/{max_retries}")
                                logger.warning(f"   Ждём {retry_delay} сек...")
                                await asyncio.sleep(retry_delay)
                                continue
                            else:
                                error_text = await response.text()
                                logger.error(f"   ❌ HTTP {response.status} при создании вариаций после {max_retries} попыток")
                                logger.error(f"   Ответ: {error_text[:200]}")
                                return
                        
                        # ДРУГИЕ ОШИБКИ
                        else:
                            error_text = await response.text()
                            logger.error(f"   ❌ Ошибка создания вариаций для {parent_id}: HTTP {response.status}")
                            logger.error(f"   Ответ: {error_text[:200]}")
                            return
                
                except asyncio.TimeoutError:
                    if attempt < max_retries - 1:
                        retry_delay = base_retry_delay * (2 ** attempt)
                        logger.warning(f"⚠️  Таймаут ({timeout_value}сек) при создании вариаций для {parent_id}, попытка {attempt + 1}/{max_retries}")
                        logger.warning(f"   Ждём {retry_delay} сек...")
                        await asyncio.sleep(retry_delay)
                        continue
                    else:
                        logger.error(f"   ❌ Таймаут при создании вариаций для {parent_id} после {max_retries} попыток")
                        return
                
                except Exception as e:
                    if attempt < max_retries - 1:
                        retry_delay = base_retry_delay * (2 ** attempt)
                        logger.warning(f"⚠️  Ошибка при создании вариаций для {parent_id}: {e}, попытка {attempt + 1}/{max_retries}")
                        logger.warning(f"   Ждём {retry_delay} сек...")
                        await asyncio.sleep(retry_delay)
                        continue
                    else:
                        logger.error(f"   ❌ Ошибка создания вариаций для {parent_id} после {max_retries} попыток: {e}")
                        return
        
        except Exception as e:
            logger.error(f"   ❌ Общая ошибка при создании вариаций для {parent_id}: {e}")
    
    async def update_product_in_wp(self, session: aiohttp.ClientSession,
                                   product: Product, wp_product_id: int) -> bool:
        """
        Обновляет товар в WordPress
        
        Args:
            session: aiohttp сессия
            product: Объект товара из БД
            wp_product_id: ID товара в WordPress
            
        Returns:
            bool: True если успешно
        """
        try:
            # КРИТИЧНО: Проверяем наличие хотя бы ОДНОГО размера в наличии
            available_variants = [v for v in product.variants if v.is_available and v.stock_status == 1]
            
            # Если НЕТ размеров в наличии - скрываем товар
            product_status = "publish" if available_variants else "draft"
            
            if not available_variants:
                logger.warning(f"⚠️ Товар {product.spu_id}: НЕТ размеров в наличии - скрываем на сайте (draft)")
            
            # Используем ВСЕ категории из product.category_ids (отфильтрованные по размерам)
            category_ids_to_send = []
            
            if product.category_ids and len(product.category_ids) > 0:
                # Используем отфильтрованные категории из БД (конвертируем в int!)
                category_ids_to_send = [int(cid) for cid in product.category_ids]
                logger.info(f"📂 Категории WC (из БД): {category_ids_to_send}")
            else:
                # Fallback
                size_type = product.variants[0].size_type.value if product.variants else 'shoes'
                category_id = product.category_id or (103 if size_type == 'shoes' else 105)
                category_ids_to_send = [category_id]
                logger.info(f"📂 Категория (fallback): {category_id}")
            
            # ОПРЕДЕЛЯЕМ ТИП АТРИБУТА РАЗМЕРА ПО КАТЕГОРИЯМ (НЕ ПО API DEWU!)
            from category_filter import get_size_attribute_id_for_categories
            size_attr_id = get_size_attribute_id_for_categories(category_ids_to_send)
            logger.info(f"📏 Атрибут размера: {size_attr_id} ({'pa_shoe_size' if size_attr_id == 4 else 'pa_clothing_size'})")
            
            # Для расчета цен берем первую категорию
            primary_category_id = category_ids_to_send[0] if category_ids_to_send else 103
            
            # Обновляем основную информацию
            payload = {
                "name": product.title,
                "status": product_status,  # "publish" если есть наличие, "draft" если нет
                "catalog_visibility": "visible" if product_status == "publish" else "hidden",
                "categories": [{"id": cat_id} for cat_id in category_ids_to_send],
                # Для вариативного товара управление запасами на уровне вариаций
                "manage_stock": False,
                "backorders": "no"
            }
            
            # ИЗОБРАЖЕНИЯ НЕ ОБНОВЛЯЕМ при обновлении товара (только при создании)
            # Если нужно обновить изображения, раскомментируйте код ниже:
            # if product.images and isinstance(product.images, list):
            #     image_objects = []
            #     for img_url in product.images[:10]:
            #         if isinstance(img_url, str) and img_url.strip():
            #             image_objects.append({"src": img_url.strip()})
            #     
            #     if image_objects:
            #         payload["images"] = image_objects
            #         logger.info(f"🖼️ Обновление изображений: {len(image_objects)} шт.")
            
            url = f"{self.wp_url}/wp-json/wc/v3/products/{wp_product_id}"
            
            # RETRY ЛОГИКА для обновления
            max_retries = 3
            base_retry_delay = 3
            
            for attempt in range(max_retries):
                try:
                    # Увеличенный timeout: 120 сек
                    timeout_value = 120
                    
                    async with session.put(url, json=payload, auth=self.get_auth(),
                                          timeout=timeout_value) as response:
                        if response.status == 200:
                            logger.info(f"✅ Обновлен товар в WP: ID {wp_product_id}")
                            
                            # ВАЖНО: Пересоздаём вариации с новыми ценами
                            logger.info(f"🔄 Обновляем вариации с новыми ценами...")
                            await self.update_variations(session, wp_product_id, product, primary_category_id)
                            
                            self.updated_count += 1
                            return True
                        
                        # ВРЕМЕННЫЕ ОШИБКИ СЕРВЕРА - повторяем попытку
                        elif response.status in [502, 503, 504]:
                            if attempt < max_retries - 1:
                                retry_delay = base_retry_delay * (2 ** attempt)
                                logger.warning(f"⚠️  HTTP {response.status} при обновлении {wp_product_id}, попытка {attempt + 1}/{max_retries}")
                                logger.warning(f"   Ждём {retry_delay} сек...")
                                await asyncio.sleep(retry_delay)
                                continue
                            else:
                                error_text = await response.text()
                                logger.error(f"❌ HTTP {response.status} при обновлении {wp_product_id} после {max_retries} попыток")
                                logger.error(f"   Ответ: {error_text[:200]}")
                                logger.warning(f"⚠️  Пропускаем товар {wp_product_id}, продолжаем")
                                return False
                        
                        # ДРУГИЕ ОШИБКИ
                        else:
                            error_text = await response.text()
                            logger.error(f"❌ Ошибка обновления товара {wp_product_id}: {error_text[:200]}")
                            logger.warning(f"⚠️  Пропускаем товар {wp_product_id}, продолжаем")
                            return False
                
                except asyncio.TimeoutError:
                    if attempt < max_retries - 1:
                        retry_delay = base_retry_delay * (2 ** attempt)
                        logger.warning(f"⚠️  Таймаут ({timeout_value}сек) при обновлении {wp_product_id}, попытка {attempt + 1}/{max_retries}")
                        logger.warning(f"   Ждём {retry_delay} сек...")
                        await asyncio.sleep(retry_delay)
                        continue
                    else:
                        logger.error(f"❌ Таймаут при обновлении {wp_product_id} после {max_retries} попыток")
                        logger.warning(f"⚠️  Пропускаем товар {wp_product_id}, продолжаем")
                        return False
                
                except Exception as e:
                    if attempt < max_retries - 1:
                        retry_delay = base_retry_delay * (2 ** attempt)
                        logger.warning(f"⚠️  Ошибка при обновлении {wp_product_id}: {e}, попытка {attempt + 1}/{max_retries}")
                        logger.warning(f"   Ждём {retry_delay} сек...")
                        await asyncio.sleep(retry_delay)
                        continue
                    else:
                        logger.error(f"❌ Ошибка обновления {wp_product_id} после {max_retries} попыток: {e}")
                        logger.warning(f"⚠️  Пропускаем товар {wp_product_id}, продолжаем")
                        return False
            
            return False
                    
        except Exception as e:
            logger.error(f"❌ Ошибка обновления товара {wp_product_id}: {e}")
            return False
    
    async def update_variations(self, session: aiohttp.ClientSession,
                                parent_id: int, product: Product, category_id_for_price: int = None):
        """
        Обновляет вариации (размеры) для товара - удаляет старые и создаёт новые
        
        Args:
            session: aiohttp сессия
            parent_id: ID родительского товара в WP
            product: Объект товара из БД
        """
        try:
            # Шаг 1: Получаем существующие вариации (с retry)
            url = f"{self.wp_url}/wp-json/wc/v3/products/{parent_id}/variations"
            params = {"per_page": 100}
            
            existing_variations = []
            max_retries = 3
            base_retry_delay = 3
            
            for attempt in range(max_retries):
                try:
                    # Увеличенный timeout: 120 сек
                    timeout_value = 120
                    
                    async with session.get(url, params=params, auth=self.get_auth(),
                                          timeout=timeout_value) as response:
                        if response.status == 200:
                            existing_variations = await response.json()
                            logger.info(f"   📋 Найдено {len(existing_variations)} существующих вариаций")
                            break
                        elif response.status in [502, 503, 504] and attempt < max_retries - 1:
                            retry_delay = base_retry_delay * (2 ** attempt)
                            logger.warning(f"⚠️  HTTP {response.status} при получении вариаций, повтор...")
                            logger.warning(f"   Ждём {retry_delay} сек...")
                            await asyncio.sleep(retry_delay)
                            continue
                except (asyncio.TimeoutError, Exception) as e:
                    if attempt < max_retries - 1:
                        retry_delay = base_retry_delay * (2 ** attempt)
                        logger.warning(f"⚠️  Ошибка получения вариаций: {e}, повтор...")
                        logger.warning(f"   Ждём {retry_delay} сек...")
                        await asyncio.sleep(retry_delay)
                        continue
            
            # Шаг 2: Удаляем все существующие вариации (с retry)
            if existing_variations:
                delete_ids = [v['id'] for v in existing_variations]
                delete_url = f"{self.wp_url}/wp-json/wc/v3/products/{parent_id}/variations/batch"
                delete_payload = {"delete": delete_ids}
                
                for attempt in range(max_retries):
                    try:
                        async with session.post(delete_url, json=delete_payload, auth=self.get_auth(),
                                               timeout=timeout_value) as response:
                            if response.status == 200:
                                logger.info(f"   🗑️ Удалено {len(delete_ids)} старых вариаций")
                                break
                            elif response.status in [502, 503, 504] and attempt < max_retries - 1:
                                retry_delay = base_retry_delay * (2 ** attempt)
                                logger.warning(f"⚠️  HTTP {response.status} при удалении вариаций, повтор...")
                                logger.warning(f"   Ждём {retry_delay} сек...")
                                await asyncio.sleep(retry_delay)
                                continue
                    except (asyncio.TimeoutError, Exception) as e:
                        if attempt < max_retries - 1:
                            retry_delay = base_retry_delay * (2 ** attempt)
                            logger.warning(f"⚠️  Ошибка удаления вариаций: {e}, повтор...")
                            logger.warning(f"   Ждём {retry_delay} сек...")
                            await asyncio.sleep(retry_delay)
                            continue
            
            # Шаг 3: Создаём новые вариации с актуальными ценами
            await self.create_variations(session, parent_id, product, category_id_for_price)
            
        except Exception as e:
            logger.error(f"❌ Ошибка обновления вариаций для товара {parent_id}: {e}")
    
    async def delete_product_from_wp(self, session: aiohttp.ClientSession,
                                    wp_product_id: int) -> bool:
        """
        Удаляет товар из WordPress
        
        Args:
            session: aiohttp сессия
            wp_product_id: ID товара в WordPress
            
        Returns:
            bool: True если успешно
        """
        try:
            url = f"{self.wp_url}/wp-json/wc/v3/products/{wp_product_id}"
            params = {"force": "true"}
            
            async with session.delete(url, params=params, auth=self.get_auth(),
                                     timeout=30) as response:
                if response.status == 200:
                    logger.info(f"🗑️ Удален товар из WP: ID {wp_product_id}")
                    self.deleted_count += 1
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"❌ Ошибка удаления товара {wp_product_id}: {error_text[:200]}")
                    return False
                    
        except Exception as e:
            logger.error(f"❌ Ошибка удаления товара {wp_product_id}: {e}")
            return False
    
    async def sync_all(self, session: aiohttp.ClientSession):
        """
        Синхронизирует все товары из БД с WordPress
        
        Args:
            session: aiohttp сессия
        """
        logger.info("🔄 ЗАПУСК СИНХРОНИЗАЦИИ С WORDPRESS")
        logger.info("="*60)
        print("="*60)
        print("🔄 ЗАПУСК СИНХРОНИЗАЦИИ")
        print("="*60)
        
        # Получаем товары из WordPress
        wp_products = await self.get_wp_products(session)
        
        # Получаем товары из БД
        print("\n📂 Получаем товары из БД...")
        all_products = db.get_all_active_products()
        
        # Фильтруем: синхронизируем ТОЛЬКО товары с загруженными данными
        db_products = [p for p in all_products if p.data_loaded]
        skipped_no_data = len(all_products) - len(db_products)
        
        db_spu_ids = {p.spu_id for p in db_products}
        
        logger.info(f"📊 БД: {len(db_products)} товаров (готовы к синхронизации)")
        print(f"📊 БД: {len(db_products)} товаров (готовы к синхронизации)")
        if skipped_no_data > 0:
            logger.info(f"⏸️  Пропущено: {skipped_no_data} товаров без загруженных данных")
            print(f"⏸️  Пропущено: {skipped_no_data} товаров без загруженных данных")
        logger.info(f"📊 WordPress: {len(wp_products)} товаров")
        print(f"📊 WordPress: {len(wp_products)} товаров\n")
        
        # Создаем новые товары
        to_create = [p for p in db_products if p.spu_id not in wp_products]
        to_update = [p for p in db_products if p.spu_id in wp_products]
        
        if to_create:
            print(f"📦 СОЗДАНИЕ НОВЫХ ТОВАРОВ ({len(to_create)} шт)")
            print("="*60)
        
        created_count = 0
        for i, product in enumerate(to_create, 1):
            # КРИТИЧНО: Проверяем наличие хотя бы ОДНОГО размера в наличии
            available_variants = [v for v in product.variants if v.is_available and v.stock_status == 1]
            
            if not available_variants:
                logger.info(f"⏭️  Пропускаем товар {product.spu_id}: НЕТ в наличии")
                print(f"[{i}/{len(to_create)}] ⏭️  {product.title[:40]} - НЕТ в наличии")
                continue
            
            # Товар есть в БД, но нет в WP - создаем
            logger.info(f"➕ Создаем товар: {product.spu_id}")
            print(f"[{i}/{len(to_create)}] 📦 Создание: {product.title[:40]}...", end=" ", flush=True)
            wp_id = await self.create_product_in_wp(session, product)
            
            if wp_id:
                db.add_sync_log(product.id, wp_id, SyncAction.create, 
                               SyncStatus.success)
                print(f"✅ ID {wp_id}")
                created_count += 1
            else:
                db.add_sync_log(product.id, None, SyncAction.create,
                               SyncStatus.failed, "Ошибка создания")
                print("❌ Ошибка")
                self.failed_count += 1
            
            await asyncio.sleep(0.5)
        
        # Обновляем существующие товары
        if to_update:
            print(f"\n🔄 ОБНОВЛЕНИЕ ТОВАРОВ ({len(to_update)} шт)")
            print("="*60)
        
        updated_count = 0
        deleted_count = 0
        for i, product in enumerate(to_update, 1):
            # КРИТИЧНО: Проверяем наличие хотя бы ОДНОГО размера в наличии
            available_variants = [v for v in product.variants if v.is_available and v.stock_status == 1]
            
            if not available_variants:
                # Товар БЕЗ наличия - удаляем из WP если он там есть
                wp_id = wp_products[product.spu_id]
                logger.info(f"🗑️  Удаляем товар {product.spu_id} (WP ID: {wp_id}): НЕТ в наличии")
                print(f"[{i}/{len(to_update)}] 🗑️  {product.title[:40]} - НЕТ в наличии, удаляем")
                await self.delete_product_from_wp(session, wp_id)
                deleted_count += 1
                await asyncio.sleep(0.5)
                continue
            
            wp_id = wp_products[product.spu_id]
            # Можно добавить проверку на необходимость обновления
            logger.info(f"🔄 Обновляем товар: {product.spu_id} (WP ID: {wp_id})")
            print(f"[{i}/{len(to_update)}] 🔄 Обновление: {product.title[:40]}...", end=" ", flush=True)
            success = await self.update_product_in_wp(session, product, wp_id)
            
            if success:
                db.add_sync_log(product.id, wp_id, SyncAction.update,
                               SyncStatus.success)
                print("✅")
                updated_count += 1
            else:
                db.add_sync_log(product.id, wp_id, SyncAction.update,
                               SyncStatus.failed, "Ошибка обновления")
                print("❌")
                self.failed_count += 1
            
            await asyncio.sleep(0.5)
        
        # Удаляем товары, которых нет в БД
        for spu_id, wp_id in wp_products.items():
            if spu_id not in db_spu_ids:
                # Товар есть в WP, но нет в БД - удаляем
                logger.info(f"🗑️ Удаляем товар: {spu_id} (WP ID: {wp_id})")
                success = await self.delete_product_from_wp(session, wp_id)
                
                if not success:
                    self.failed_count += 1
                
                await asyncio.sleep(0.3)
        
        logger.info("="*60)
        logger.info("✅ СИНХРОНИЗАЦИЯ ЗАВЕРШЕНА")
        logger.info(f"   ➕ Создано: {self.created_count}")
        logger.info(f"   🔄 Обновлено: {self.updated_count}")
        logger.info(f"   🗑️ Удалено: {self.deleted_count}")
        logger.info(f"   ❌ Ошибок: {self.failed_count}")
        
        print("\n" + "="*60)
        print("✅ СИНХРОНИЗАЦИЯ ЗАВЕРШЕНА")
        print("="*60)
        print(f"   ➕ Создано: {self.created_count}")
        print(f"   🔄 Обновлено: {self.updated_count}")
        print(f"   🗑️ Удалено: {self.deleted_count}")
        print(f"   ❌ Ошибок: {self.failed_count}")
        print("="*60 + "\n")
    
    def get_stats(self) -> Dict:
        """Возвращает статистику синхронизации"""
        return {
            "created": self.created_count,
            "updated": self.updated_count,
            "deleted": self.deleted_count,
            "failed": self.failed_count
        }


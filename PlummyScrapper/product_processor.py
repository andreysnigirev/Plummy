"""
Обработка и валидация данных товаров
Валидация размеров, подготовка к сохранению в БД
"""
import logging
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ProductProcessor:
    """Процессор для обработки данных товаров"""
    
    # Валидные европейские размеры обуви (с шагом 0.5)
    VALID_EU_SHOE_SIZES = set([str(size/2) if size % 2 != 0 else str(size//2) 
                                for size in range(66, 101)])  # 33.0 до 50.0
    
    # Валидные размеры одежды
    VALID_CLOTHING_SIZES = {
        'XXXS', 'XXS', 'XS', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL', 
        '4XL', '5XL', '6XL', '7XL'
    }
    
    def __init__(self, price_formula=None):
        """
        Инициализация процессора
        
        Args:
            price_formula: Функция для расчета цены (опционально)
        """
        self.price_formula = price_formula
        self.processed_count = 0
        self.valid_count = 0
        self.invalid_reasons = {}
    
    def clean_title(self, title: str) -> str:
        """
        Очищает название товара, оставляя ТОЛЬКО английские буквы, цифры и пробелы.
        Удаляет ВСЕ остальные символы: китайские, эмодзи, спецсимволы, знаки препинания и т.д.
        
        Args:
            title: Название из API
            
        Returns:
            str: Очищенное название (только A-Z, a-z, 0-9 и пробелы)
        
        Примеры:
            "Nike Air Jordan 1 ❤️【热销】" → "Nike Air Jordan 1"
            "adidas Yeezy 350 V2 ★★★" → "adidas Yeezy 350 V2"
            "New Balance 574中国限定" → "New Balance 574"
        """
        if not title:
            return ""
        
        # КРИТИЧНО: Оставляем ТОЛЬКО английские буквы (A-Z, a-z), цифры (0-9) и пробелы
        # Удаляем ВСЕ остальное: китайские символы, эмодзи, знаки препинания, спецсимволы и т.д.
        title = re.sub(r'[^A-Za-z0-9\s]+', '', title)
        
        # Убираем лишние пробелы (несколько подряд → один)
        title = re.sub(r'\s+', ' ', title).strip()
        
        logger.debug(f"Очищенное название: '{title}'")
        return title
    
    def _sanitize_brand_name(self, brand: str) -> str:
        """
        Очищает название бренда, оставляя только английские буквы, цифры и основные символы
        
        Args:
            brand: Название бренда из API
            
        Returns:
            str: Очищенное название бренда (только английские буквы и цифры)
        """
        if not brand:
            return ""
        
        # Оставляем только английские буквы (A-Z, a-z), цифры (0-9) и пробелы
        # Также сохраняем дефисы и амперсанды для брендов типа "G-STAR" или "H&M"
        cleaned = re.sub(r'[^A-Za-z0-9\s\-&]', '', brand)
        
        # Убираем лишние пробелы
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        logger.debug(f"Бренд очищен: '{brand}' → '{cleaned}'")
        return cleaned
    
    def extract_eu_sizes(self, size_template: dict) -> List[str]:
        """
        Извлекает европейские размеры из size template
        
        Args:
            size_template: Словарь с размерной сеткой
            
        Returns:
            List[str]: Список европейских размеров
        """
        try:
            template_list = size_template.get('list', [])
            
            for item in template_list:
                if isinstance(item, dict):
                    size_key = item.get('sizeKey', '')
                    size_value = item.get('sizeValue', '')
                    
                    # Ищем европейские размеры
                    if 'EU' in size_key or '欧码' in size_key:
                        if size_value:
                            eu_sizes = [s.strip() for s in size_value.split(',') if s.strip()]
                            logger.debug(f"Найдено EU размеров: {len(eu_sizes)}")
                            return eu_sizes
            
            logger.warning("⚠️ EU размеры не найдены в template")
            return []
            
        except Exception as e:
            logger.error(f"❌ Ошибка извлечения EU размеров: {e}")
            return []
    
    def validate_eu_size(self, size: str, size_type: str = 'shoes') -> bool:
        """
        Проверяет валидность европейского размера
        
        Args:
            size: Размер для проверки
            size_type: Тип размера ('shoes' или 'clothing')
            
        Returns:
            bool: True если размер валидный
        """
        size = str(size).strip()
        
        if size_type == 'shoes':
            return size in self.VALID_EU_SHOE_SIZES
        elif size_type == 'clothing':
            return size.upper() in self.VALID_CLOTHING_SIZES
        
        return False
    
    def parse_product_detail(self, product_data: dict, reference_sku_id: Optional[str] = None, category_ids: Optional[List[int]] = None) -> Optional[Dict]:
        """
        Парсит детали товара и извлекает нужную информацию
        
        Args:
            product_data: Данные товара от API
            reference_sku_id: Опциональный SKU ID для определения правильного цвета
            category_ids: Опциональный список ID категорий WooCommerce для определения типа товара
            
        Returns:
            Optional[Dict]: Обработанные данные или None
        """
        try:
            self.processed_count += 1
            
            # SPU ID может быть в разных местах
            spu_id = product_data.get('spuId')
            if not spu_id and 'detail' in product_data:
                spu_id = product_data['detail'].get('spuId')
            
            if not spu_id:
                self._log_invalid("no_spu_id")
                logger.error(f"❌ SPU ID не найден в product_data")
                logger.error(f"   Доступные поля: {list(product_data.keys())[:15]}")
                return None
            
            logger.debug(f"🔍 Обработка SPU {spu_id}...")
            
            # ДИАГНОСТИКА: Выводим все ключи данных товара
            logger.info(f"🔍 Товар {spu_id} - доступные поля: {list(product_data.keys())}")
            
            # Извлекаем основную информацию - пробуем разные варианты
            title = None
            
            # Вариант 1: Прямые поля
            title = (product_data.get('title') or 
                    product_data.get('name') or 
                    product_data.get('productName') or 
                    product_data.get('spuName'))
            
            # Вариант 2: Поле detail
            if not title and 'detail' in product_data:
                detail = product_data['detail']
                if isinstance(detail, dict):
                    title = (detail.get('title') or 
                            detail.get('name') or 
                            detail.get('productName') or
                            detail.get('spuName') or
                            detail.get('desc') or
                            detail.get('description'))
                    logger.info(f"🔍 Проверяем detail: {list(detail.keys())[:10]}")
            
            # Вариант 3: Поле basicParam
            if not title and 'basicParam' in product_data:
                basic = product_data['basicParam']
                if isinstance(basic, dict):
                    title = (basic.get('title') or 
                            basic.get('name') or
                            basic.get('productName') or
                            basic.get('spuName'))
                    logger.info(f"🔍 Проверяем basicParam: {list(basic.keys())[:10]}")
            
            # Вариант 4: Поле detailModel
            if not title and 'detailModel' in product_data:
                detail_model = product_data['detailModel']
                if isinstance(detail_model, dict):
                    title = (detail_model.get('title') or 
                            detail_model.get('name') or
                            detail_model.get('productName'))
                    logger.info(f"🔍 Проверяем detailModel: {list(detail_model.keys())[:10]}")
            
            # Очищаем название от китайских символов
            if title:
                original_title = title
                title = self.clean_title(title)
                logger.info(f"📝 Название: '{original_title}' → '{title}'")
            
            if not title:
                self._log_invalid("empty_title")
                logger.error(f"❌ Товар {spu_id}: название не найдено в полях API!")
                logger.error(f"   Проверьте структуру данных: {list(product_data.keys())[:20]}")
                
                # Дополнительная диагностика - выводим содержимое вложенных полей
                if 'detail' in product_data and isinstance(product_data['detail'], dict):
                    logger.error(f"   detail поля: {list(product_data['detail'].keys())[:10]}")
                if 'basicParam' in product_data and isinstance(product_data['basicParam'], dict):
                    logger.error(f"   basicParam поля: {list(product_data['basicParam'].keys())[:10]}")
                if 'detailModel' in product_data and isinstance(product_data['detailModel'], dict):
                    logger.error(f"   detailModel поля: {list(product_data['detailModel'].keys())[:10]}")
                
                return None
            
            # Изображения - правильная структура согласно API документации
            images = []
            logo_url = None
            
            # ПРИОРИТЕТ 1: Если указан reference_sku_id - берем изображение специфичное для этого SKU
            if reference_sku_id and 'skus' in product_data and isinstance(product_data['skus'], list):
                for sku in product_data['skus']:
                    if isinstance(sku, dict) and str(sku.get('skuId')) == str(reference_sku_id):
                        sku_logo = sku.get('logoUrl')
                        if sku_logo:
                            logo_url = sku_logo
                            logger.info(f"🎨 Изображение для SKU {reference_sku_id}: {sku_logo[:80]}...")
                            break
            
            # ПРИОРИТЕТ 2: Если не нашли SKU-специфичное изображение - берем из detail.logoUrl
            if not logo_url:
                if 'detail' in product_data and isinstance(product_data['detail'], dict):
                    logo_url = product_data['detail'].get('logoUrl')
                    logger.info(f"🖼️ Основное изображение из detail.logoUrl: {bool(logo_url)}")
            
            # Из image.spuImage.images - дополнительные изображения (согласно документации)
            if 'image' in product_data and isinstance(product_data['image'], dict):
                spu_image = product_data['image'].get('spuImage', {})
                if isinstance(spu_image, dict):
                    images_list = spu_image.get('images', [])
                    if isinstance(images_list, list):
                        # Изображения - это объекты с полем 'url'
                        for img in images_list:
                            if isinstance(img, dict):
                                img_url = img.get('url')
                                if img_url:
                                    images.append(img_url)
                            elif isinstance(img, str):
                                images.append(img)
                        logger.info(f"🖼️ Дополнительные изображения из image.spuImage.images: {len(images)}")
            
            # Собираем все изображения
            all_images = []
            if logo_url:
                all_images.append(logo_url)
            all_images.extend(images)
            
            if not all_images:
                self._log_invalid("no_images")
                logger.warning(f"⚠️ Товар {spu_id}: нет изображений")
                logger.error(f"   Проверьте структуру API ответа")
                return None
            
            logger.info(f"✅ Всего изображений: {len(all_images)}")
            
            # Бренд - из brandRootInfo или detail
            brand = ''
            if 'brandRootInfo' in product_data:
                brand_root = product_data['brandRootInfo']
                if isinstance(brand_root, dict):
                    brand_items = brand_root.get('brandItemList', [])
                    if brand_items and isinstance(brand_items, list) and len(brand_items) > 0:
                        raw_brand = brand_items[0].get('brandName', '')
                        # Валидация: оставляем только английские буквы, цифры и пробелы
                        brand = self._sanitize_brand_name(raw_brand)
            
            # Артикул - из detail
            article_number = ''
            if 'detail' in product_data and isinstance(product_data['detail'], dict):
                article_number = product_data['detail'].get('articleNumber', '')
            
            # Категория Dewu - из detail
            category_id = None
            category_name = ''
            if 'detail' in product_data and isinstance(product_data['detail'], dict):
                detail = product_data['detail']
                category_id = detail.get('categoryId')
                category_name = detail.get('categoryName', '')
            
            logger.info(f"🏷️  Бренд: {brand}, Артикул: {article_number}")
            if category_id:
                logger.info(f"📂 Категория Dewu: {category_name} (ID: {category_id})")
            
            # Размеры и цены
            skus = product_data.get('skus', [])
            size_dto = product_data.get('sizeDto', {})
            size_info = size_dto.get('sizeInfo', {})
            size_template = size_info.get('sizeTemplate', {})
            
            # Извлекаем EU размеры из template (для справки)
            eu_sizes_template = self.extract_eu_sizes(size_template)
            
            # Извлекаем saleProperties - тут связь propertyValueId → размер
            sale_properties = product_data.get('saleProperties', {})
            properties_list = sale_properties.get('list', [])
            
            # Создаём маппинг propertyValueId → размер
            property_to_size = {}
            primary_color_id = None  # ID основного цвета для фильтрации SKU
            
            # ===== ОПРЕДЕЛЕНИЕ ПРАВИЛЬНОГО ЦВЕТА =====
            # Если указан reference_sku_id, используем цвет от этого SKU
            # НО! Проверяем что это именно ЦВЕТ, а не размер!
            if reference_sku_id:
                reference_sku_id_int = int(reference_sku_id)
                for sku in skus:
                    if sku.get('skuId') == reference_sku_id_int:
                        # Нашли reference SKU - берём его цвет (level=1)
                        for prop in sku.get('properties', []):
                            if isinstance(prop, dict) and prop.get('level') == 1:
                                prop_value_id = prop.get('propertyValueId')
                                
                                # КРИТИЧЕСКИ ВАЖНО: Проверяем что это ЦВЕТ, а НЕ РАЗМЕР!
                                # Ищем этот propertyValueId в saleProperties и проверяем name
                                is_color = False
                                for sale_prop in properties_list:
                                    if sale_prop.get('propertyValueId') == prop_value_id:
                                        prop_name = sale_prop.get('name', '')
                                        # Это цвет если name содержит "颜色" (цвет) или "Color"
                                        if prop_name in ['颜色', 'Color', 'color']:
                                            is_color = True
                                        # Это НЕ цвет если name содержит "尺码" (размер)
                                        elif prop_name in ['尺码', '尺寸', 'Size', 'size', '码']:
                                            is_color = False
                                        break
                                
                                if is_color:
                                    primary_color_id = prop_value_id
                                    logger.info(f"🎨 Используем цвет от reference_sku_id {reference_sku_id} (color_id: {primary_color_id})")
                                else:
                                    logger.info(f"⚠️  reference_sku_id {reference_sku_id}: property level=1 это размер, а не цвет! Пропускаем фильтрацию по цвету")
                                break
                        break
            
            for prop in properties_list:
                if isinstance(prop, dict):
                    prop_id = prop.get('propertyValueId')
                    prop_value = prop.get('value', '')  # Это и есть размер!
                    prop_name = prop.get('name', '')
                    level = prop.get('level', 0)
                    
                    # ВАЖНО: Определяем основной цвет (первый level=1 с name="颜色")
                    # Только если НЕ указан reference_sku_id
                    if primary_color_id is None and level == 1 and prop_name in ['颜色', 'Color', 'color']:
                        primary_color_id = prop_id
                        logger.info(f"🎨 Определен основной цвет (первый): {prop_value} (ID: {prop_id})")
                    
                    # Берём размеры: обычно level=2, но иногда level=1
                    # Проверяем что это размер по name='尺码' (размер) или level=2
                    is_size = (level == 2) or (level == 1 and prop_name in ['尺码', '尺寸', 'Size', 'size', '码'])
                    if prop_id and prop_value and is_size:
                        property_to_size[prop_id] = prop_value
            
            logger.debug(f"📏 Найдено {len(property_to_size)} размеров в saleProperties")
            
            if not skus:
                self._log_invalid("no_skus")
                logger.error(f"❌ Товар {spu_id}: нет SKU в данных")
                return None
            
            logger.debug(f"📊 Найдено SKU: {len(skus)}")
            
            # Извлекаем данные из priceInfo если есть
            price_info_data = product_data.get('priceInfo', {})
            price_info_skus = {}

            if price_info_data:
                # priceInfo возвращает {"skus": {skuId: {...}, ...}}
                price_info_skus = price_info_data.get('skus', {})
                logger.info(f"💰 Получены цены для {len(price_info_skus)} SKU из priceInfo")
            
            # Подсчёт источников цен для статистики
            price_sources_count = {'priceInfo': 0, 'price.prices': 0, 'authPrice': 0}
            for sku in skus:
                sku_id = str(sku.get('skuId', 0))
                if sku_id in price_info_skus:
                    price_sources_count['priceInfo'] += 1
            logger.debug(f"💰 SKU с ценами в priceInfo: {price_sources_count['priceInfo']}")
            
            # Определяем тип размера (обувь, одежда или аксессуары)
            # ПРИОРИТЕТ 1: Проверяем категории (если переданы)
            size_type = None
            if category_ids:
                from category_filter import is_one_size_category_check
                if is_one_size_category_check(category_ids):
                    size_type = 'accessories'
                    logger.info(f"👜 Определен тип: АКСЕССУАРЫ (по категориям: {category_ids})")
                    logger.info(f"   📏 Для аксессуаров будет использован только ONE SIZE")
                    # Для аксессуаров с определенными категориями очищаем property_to_size
                    property_to_size = {}
            
            # ПРИОРИТЕТ 2: Если тип не определен по категориям, проверяем размеры
            if size_type is None:
                size_type = 'shoes'  # По умолчанию обувь
                has_valid_sizes = False
                
                for size_value in property_to_size.values():
                    # Проверка на размеры одежды
                    if size_value.upper() in self.VALID_CLOTHING_SIZES:
                        size_type = 'clothing'
                        has_valid_sizes = True
                        logger.info(f"👕 Определен тип: ОДЕЖДА (найден размер {size_value})")
                        break
                    # Проверка на размеры обуви (должны содержать цифры)
                    elif any(char.isdigit() for char in str(size_value)):
                        has_valid_sizes = True
                
                # Если нет валидных размеров - это аксессуары (сумки, шапки и т.д.)
                if not has_valid_sizes and len(property_to_size) > 0:
                    size_type = 'accessories'
                    logger.info(f"👜 Определен тип: АКСЕССУАРЫ (нет валидных размеров обуви/одежды)")
                    # Для аксессуаров очищаем property_to_size, чтобы использовать ONE SIZE
                    property_to_size = {}
                    logger.info(f"   📏 Для аксессуаров будет использован ONE SIZE")
                elif size_type == 'shoes':
                    logger.debug(f"👟 Определен тип: ОБУВЬ")
                    # КРИТИЧЕСКАЯ ПРОВЕРКА: Если property_to_size пустой для обуви - это проблема!
                    if len(property_to_size) == 0:
                        logger.warning(f"⚠️  ОБУВЬ БЕЗ РАЗМЕРОВ в property_to_size!")
                        logger.warning(f"   Товар будет обработан через fallback логику (может загрузиться 1 размер)")
                        logger.warning(f"   Проверьте структуру данных API для SPU {spu_id}")
            
            # Определяем сколько SKU доступно для обработки
            logger.debug(f"📊 Всего SKU: {len(skus)}, из них в priceInfo: {len(price_info_skus)}")
            
            # Обрабатываем SKU и создаем варианты
            variants = []
            found_one_size_variant = False  # Флаг для аксессуаров с ONE SIZE
            
            for i, sku in enumerate(skus):
                if not isinstance(sku, dict):
                    continue
                
                sku_id = sku.get('skuId', 0)
                
                # ПРАВИЛЬНАЯ ЛОГИКА: Берём размер из properties SKU!
                # properties содержит propertyValueId который соответствует размеру
                properties = sku.get('properties', [])
                size_eu = None
                sku_color_id = None
                
                # ===== ФИЛЬТР ПО SKU/ЦВЕТУ =====
                # ДЛЯ АКСЕССУАРОВ: Если указан reference_sku_id - загружаем ТОЛЬКО этот SKU
                if size_type == 'accessories' and reference_sku_id:
                    if str(sku_id) != str(reference_sku_id):
                        logger.debug(f"   ⏭️  SKU {sku_id}: не совпадает с reference_sku_id {reference_sku_id}, пропускаем")
                        continue
                    logger.debug(f"   ✅ SKU {sku_id}: совпадает с reference_sku_id, загружаем")
                
                # ДЛЯ ОБУВИ/ОДЕЖДЫ: Если указан reference_sku_id - фильтруем по цвету
                # КРИТИЧЕСКИ ВАЖНО: Если указан reference_sku_id, то:
                # 1. Мы уже определили primary_color_id из этого SKU (строки 329-339)
                # 2. Нужно загрузить ВСЕ размеры этого ЦВЕТА, а не только один SKU!
                # 3. Поэтому фильтруем по primary_color_id для обуви/одежды
                elif size_type != 'accessories' and primary_color_id:
                    for prop in properties:
                        if isinstance(prop, dict) and prop.get('level') == 1:
                            sku_color_id = prop.get('propertyValueId')
                            break
                    
                    # Если это SKU другого цвета - пропускаем
                    if sku_color_id and sku_color_id != primary_color_id:
                        logger.debug(f"   ⏭️  SKU {sku_id}: другой цвет (ID {sku_color_id}), пропускаем")
                        continue
                
                # Ищем размер в properties (обычно level=2, но иногда level=1)
                for prop in properties:
                    if isinstance(prop, dict):
                        level = prop.get('level', 0)
                        prop_value_id = prop.get('propertyValueId')
                        # Проверяем и level=2 и level=1
                        if prop_value_id in property_to_size and level in [1, 2]:
                            size_eu = property_to_size[prop_value_id]
                            break
                
                # FALLBACK: Если размер не найден в маппинге, пробуем другие способы
                if not size_eu:
                    # Способ 1: Ищем prop с level=2 (обычно размер), НО пропускаем ширину обуви
                    width_indicators = ['D', 'E', 'W', 'EE', 'EEE', '2E', '3E', '4E', 'D宽', 'E宽', '2E宽', '宽', '窄']
                    
                    for prop in properties:
                        if isinstance(prop, dict) and prop.get('level') == 2:
                            prop_value = prop.get('propertyValue')
                            if prop_value:
                                prop_value_str = str(prop_value).strip()
                                
                                # КРИТИЧЕСКИ ВАЖНО: Пропускаем обозначения ширины обуви!
                                is_width = False
                                for indicator in width_indicators:
                                    if indicator in prop_value_str or prop_value_str.upper() == indicator:
                                        is_width = True
                                        logger.debug(f"   ⏭️  level=2: пропускаем ширину обуви '{prop_value_str}'")
                                        break
                                
                                if not is_width:
                                    size_eu = prop_value_str
                                    logger.debug(f"   📏 Размер из level=2: {size_eu} (fallback 1)")
                                    break
                
                # Способ 2: Если все еще не нашли, берем первое ЧИСЛОВОЕ значение из properties
                if not size_eu and properties:
                    for prop in properties:
                        if isinstance(prop, dict):
                            prop_value = prop.get('propertyValue')
                            if prop_value:
                                prop_value_str = str(prop_value).strip()
                                
                                # Пропускаем:
                                # 1. Китайские/японские символы (не ASCII)
                                # 2. Длинные строки (>10 символов)
                                # 3. Одиночные буквы (D, W, M и т.д. - это ширина обуви)
                                # 4. Строки состоящие только из букв
                                # 5. Строки с символами ширины обуви (宽, 窄, E, D)
                                
                                # Проверяем что это ASCII
                                try:
                                    prop_value_str.encode('ascii')
                                except UnicodeEncodeError:
                                    logger.debug(f"   ⏭️  Пропускаем не-ASCII значение: {prop_value_str}")
                                    continue
                                
                                # Пропускаем длинные строки
                                if len(prop_value_str) > 10:
                                    continue
                                
                                # ВАЖНО: Пропускаем обозначения ширины обуви (D, E, 2E, 3E, W и т.д.)
                                # Ширина обуви: обычно одна-две буквы, иногда с цифрой впереди
                                # Примеры: D, E, 2E, 3E, W, EE, EEE
                                width_indicators = ['D', 'E', 'W', 'EE', 'EEE', '2E', '3E', '4E', 'D宽', 'E宽', '2E宽']
                                if prop_value_str.upper() in width_indicators or prop_value_str.upper().endswith('宽'):
                                    logger.debug(f"   ⏭️  Пропускаем обозначение ширины обуви: {prop_value_str}")
                                    continue
                                
                                # Пропускаем одиночные буквы или строки только из букв
                                if prop_value_str.isalpha():
                                    logger.debug(f"   ⏭️  Пропускаем буквенное значение (возможно ширина): {prop_value_str}")
                                    continue
                                
                                # Для обуви - берем только значения с цифрами
                                if size_type == 'shoes':
                                    if not any(char.isdigit() for char in prop_value_str):
                                        logger.debug(f"   ⏭️  Пропускаем значение без цифр: {prop_value_str}")
                                        continue
                                
                                size_eu = prop_value_str
                                logger.debug(f"   📏 Размер из properties[any]: {size_eu} (fallback 2)")
                                break
                
                # Способ 3: НОВЫЙ - Проверяем другие поля SKU
                if not size_eu:
                    # Пробуем извлечь размер из других полей SKU
                    # Возможные поля: size, sizeValue, sizeName и т.д.
                    possible_size_fields = ['size', 'sizeValue', 'sizeName', 'sizeEu', 'sizeUs', 'sizeUk']
                    for field in possible_size_fields:
                        field_value = sku.get(field)
                        if field_value:
                            field_value_str = str(field_value).strip()
                            # Проверяем что это валидный размер (содержит цифры для обуви)
                            if size_type == 'shoes' and any(char.isdigit() for char in field_value_str):
                                size_eu = field_value_str
                                logger.debug(f"   📏 Размер из sku.{field}: {size_eu} (fallback 3)")
                                break
                            elif size_type == 'clothing' and field_value_str.upper() in self.VALID_CLOTHING_SIZES:
                                size_eu = field_value_str
                                logger.debug(f"   📏 Размер из sku.{field}: {size_eu} (fallback 3)")
                                break
                
                # Способ 4: Используем SKU ID как последний fallback для обуви
                # Иногда SKU ID сам по себе содержит информацию о размере
                if not size_eu and size_type == 'shoes':
                    # Извлекаем числа из SKU ID
                    sku_id_str = str(sku_id)
                    # Проверяем есть ли в конце SKU ID что-то похожее на размер (35-50)
                    import re
                    # Ищем паттерны типа: 35, 36.5, 40, 42 в конце SKU ID
                    size_match = re.search(r'(\d{2}(?:\.\d)?)\D*$', sku_id_str)
                    if size_match:
                        potential_size = size_match.group(1)
                        # Проверяем что это валидный размер обуви (33-50)
                        try:
                            size_float = float(potential_size)
                            if 33.0 <= size_float <= 50.0:
                                size_eu = potential_size
                                logger.debug(f"   📏 Размер извлечён из SKU ID {sku_id}: {size_eu} (fallback 4)")
                        except ValueError:
                            pass
                
                # Способ 5: ONE SIZE ТОЛЬКО для аксессуаров
                if not size_eu:
                    if size_type == 'accessories':
                        # ТОЛЬКО ДЛЯ АКСЕССУАРОВ: используем ONE SIZE
                        size_eu = "ONE SIZE"
                        logger.debug(f"   📏 SKU {sku_id}: аксессуар, используем ONE SIZE (fallback 5)")
                    else:
                        # ДЛЯ ОБУВИ/ОДЕЖДЫ: Если размер не найден - ПРОПУСКАЕМ SKU
                        logger.warning(f"   ⚠️ SKU {sku_id}: размер НЕ НАЙДЕН для {size_type}, пропускаем")
                        logger.warning(f"      Проверьте структуру данных API! SKU: {sku}")
                        continue  # Пропускаем этот SKU (не загружаем)
                
                # КРИТИЧНО ДЛЯ АКСЕССУАРОВ БЕЗ reference_sku_id: 
                # Если это аксессуар (ONE SIZE) и мы уже нашли один вариант - пропускаем остальные
                # НО! Если указан reference_sku_id - эта проверка не нужна (мы уже отфильтровали выше)
                if size_type == 'accessories' and size_eu == "ONE SIZE" and found_one_size_variant and not reference_sku_id:
                    logger.debug(f"   ⏭️  SKU {sku_id}: пропускаем (уже есть ONE SIZE вариант)")
                    continue
                
                # Теперь у нас ВСЕГДА есть size_eu (хотя бы ONE SIZE)
                
                # Нормализация размера для ВСЕХ размеров (кроме ONE SIZE)
                # 40.0 → 40 для обуви
                if size_type == 'shoes' and size_eu != 'ONE SIZE':
                    try:
                        size_float = float(size_eu)
                        if size_float.is_integer():
                            original_size = size_eu
                            size_eu = str(int(size_float))
                            if original_size != size_eu:
                                logger.debug(f"   📏 Нормализован размер: {original_size} → {size_eu}")
                    except (ValueError, TypeError):
                        pass  # Оставляем как есть, если не число
                
                # Для логирования
                in_price_info = str(sku_id) in price_info_skus if price_info_skus else False
                status = sku.get('status', 0)
                
                # ========== КРИТИЧЕСКИ ВАЖНАЯ ПРОВЕРКА ==========
                # НОВЫЙ API: productDetailWithPrice уже содержит только доступные SKU
                # Старая проверка priceInfo больше не нужна
                
                # ПРИОРИТЕТ 2: Статус (1 = в наличии)
                status = sku.get('status', 0)
                
                # Пропускаем товары не в наличии
                if status != 1:
                    logger.debug(f"   ⏭️  {size_eu} EU (SKU {sku_id}): нет в наличии (status={status})")
                    continue
                
                # Валидация размера ОТКЛЮЧЕНА - загружаем все размеры
                # if not self.validate_eu_size(size_eu, size_type):
                #     logger.debug(f"   ⚠️ Невалидный размер: {size_eu}")
                #     continue
                
                # ПРИОРИТЕТ ИСТОЧНИКОВ ЦЕН:
                price_cny = None
                price_source = None
                
                # Вариант 1: ПРИОРИТЕТ - Цена из priceInfo endpoint
                if str(sku_id) in price_info_skus:
                    sku_price_data = price_info_skus[str(sku_id)]
                    if isinstance(sku_price_data, dict):
                        prices_list = sku_price_data.get('prices', [])
                        if prices_list and len(prices_list) > 0:
                            # ВАЖНО: Загружаем размеры с ДОПУСТИМЫМИ типами цен
                            # ПРИОРИТЕТ 1: type=2 - обычная цена
                            # ПРИОРИТЕТ 2: type=12 - спец. цена
                            # ПРИОРИТЕТ 3: type=0 - неизвестный тип (цены нормальные)
                            # ПРИОРИТЕТ 4: type=8 - скидочная цена (со скидками 20-60%)
                            # ПРИОРИТЕТ 5: type=11 - новинка/спец. предложение
                            # Остальные типы (3, 4, 95 и др.) - пропускаем
                            
                            ALLOWED_PRICE_TYPES = [2, 12, 0, 8, 11]  # Разрешенные типы цен
                            
                            selected_price_obj = None
                            selected_type = None
                            
                            # ПРИОРИТЕТ 1: Ищем обычную цену (type=2)
                            for price_obj in prices_list:
                                if isinstance(price_obj, dict):
                                    trade_type = price_obj.get('tradeType', 0)
                                    time_delivery = price_obj.get('timeDelivery', {})
                                    max_delivery = time_delivery.get('max', 999)
                                    is_fast = max_delivery <= 4 and trade_type != 95
                                    
                                    if trade_type == 2 and is_fast:
                                        selected_price_obj = price_obj
                                        selected_type = 2
                                        logger.debug(f"   💰 {size_eu}: найдена обычная цена (type=2)")
                                        break
                            
                            # ПРИОРИТЕТ 2: Если type=2 не найдена, ищем type=12
                            if not selected_price_obj:
                                for price_obj in prices_list:
                                    if isinstance(price_obj, dict):
                                        trade_type = price_obj.get('tradeType', 0)
                                        
                                        if trade_type == 12:
                                            selected_price_obj = price_obj
                                            selected_type = 12
                                            logger.debug(f"   💰 {size_eu}: найдена спец. цена (type=12)")
                                            break
                            
                            # ПРИОРИТЕТ 3: Если type=2 и type=12 не найдены, ищем type=0
                            if not selected_price_obj:
                                for price_obj in prices_list:
                                    if isinstance(price_obj, dict):
                                        trade_type = price_obj.get('tradeType', 0)
                                        
                                        if trade_type == 0:
                                            selected_price_obj = price_obj
                                            selected_type = 0
                                            logger.debug(f"   💰 {size_eu}: найдена цена type=0 (неизвестный тип)")
                                            break
                            
                            # ПРИОРИТЕТ 4: Если type=0 не найдена, ищем type=8 (скидочная)
                            if not selected_price_obj:
                                for price_obj in prices_list:
                                    if isinstance(price_obj, dict):
                                        trade_type = price_obj.get('tradeType', 0)
                                        
                                        if trade_type == 8:
                                            selected_price_obj = price_obj
                                            selected_type = 8
                                            logger.debug(f"   💰 {size_eu}: найдена скидочная цена (type=8)")
                                            break
                            
                            # ПРИОРИТЕТ 5: Если type=8 не найдена, ищем type=11 (новинка)
                            if not selected_price_obj:
                                for price_obj in prices_list:
                                    if isinstance(price_obj, dict):
                                        trade_type = price_obj.get('tradeType', 0)
                                        
                                        if trade_type == 11:
                                            selected_price_obj = price_obj
                                            selected_type = 11
                                            logger.debug(f"   💰 {size_eu}: найдена цена новинки (type=11)")
                                            break
                            
                            # Если нет допустимых цен - пропускаем этот размер!
                            if not selected_price_obj:
                                logger.debug(f"   ⏭️  {size_eu} EU (SKU {sku_id}): НЕТ допустимых цен (type=2, 12, 0, 8, 11), пропускаем")
                                continue
                            
                            if isinstance(selected_price_obj, dict):
                                # КРИТИЧЕСКИ ВАЖНО: Используем activePrice (активная/скидочная цена)
                                # Это та цена, которая реально отображается пользователю на сайте!
                                price_raw = selected_price_obj.get('activePrice')
                                
                                # Если activePrice отсутствует - используем обычную price
                                if not price_raw or price_raw <= 0:
                                    price_raw = selected_price_obj.get('price', 0)
                                    logger.debug(f"   💰 {size_eu}: используем price (activePrice отсутствует)")
                                else:
                                    logger.debug(f"   💰 {size_eu}: используем activePrice (скидочная цена)")
                                
                                if price_raw > 0:
                                    # API ВСЕГДА возвращает цены в фенях (1/100 юаня)
                                    price_cny = price_raw / 100
                                    price_source = "priceInfo"
                                    logger.debug(f"   💰 {size_eu} EU: цена из priceInfo = {price_cny} CNY (было {price_raw} феней)")
                
                # Вариант 2: Детальная цена из price.prices[] (productDetailWithPrice)
                # ⚠️ ВАЖНО: Применяем ту же фильтрацию по типам цен!
                if price_cny is None or price_cny <= 0:
                    price_obj = sku.get('price', {})
                    if isinstance(price_obj, dict):
                        prices_list = price_obj.get('prices', [])
                        if prices_list and len(prices_list) > 0:
                            # КРИТИЧНО: Фильтруем по допустимым типам цен (как в Варианте 1)
                            ALLOWED_PRICE_TYPES = [2, 12, 0, 8, 11]
                            
                            selected_price_obj = None
                            selected_type = None
                            
                            # ПРИОРИТЕТ 1: Ищем type=2 (обычная цена)
                            for price_obj_item in prices_list:
                                if isinstance(price_obj_item, dict):
                                    trade_type = price_obj_item.get('tradeType', 0)
                                    time_delivery = price_obj_item.get('timeDelivery', {})
                                    max_delivery = time_delivery.get('max', 999)
                                    is_fast = max_delivery <= 4 and trade_type != 95
                                    
                                    if trade_type == 2 and is_fast:
                                        selected_price_obj = price_obj_item
                                        selected_type = 2
                                        break
                            
                            # ПРИОРИТЕТ 2: type=12
                            if not selected_price_obj:
                                for price_obj_item in prices_list:
                                    if isinstance(price_obj_item, dict) and price_obj_item.get('tradeType') == 12:
                                        selected_price_obj = price_obj_item
                                        selected_type = 12
                                        break
                            
                            # ПРИОРИТЕТ 3: type=0
                            if not selected_price_obj:
                                for price_obj_item in prices_list:
                                    if isinstance(price_obj_item, dict) and price_obj_item.get('tradeType') == 0:
                                        selected_price_obj = price_obj_item
                                        selected_type = 0
                                        break
                            
                            # ПРИОРИТЕТ 4: type=8
                            if not selected_price_obj:
                                for price_obj_item in prices_list:
                                    if isinstance(price_obj_item, dict) and price_obj_item.get('tradeType') == 8:
                                        selected_price_obj = price_obj_item
                                        selected_type = 8
                                        break
                            
                            # ПРИОРИТЕТ 5: type=11
                            if not selected_price_obj:
                                for price_obj_item in prices_list:
                                    if isinstance(price_obj_item, dict) and price_obj_item.get('tradeType') == 11:
                                        selected_price_obj = price_obj_item
                                        selected_type = 11
                                        break
                            
                            # Если нашли подходящую цену
                            if selected_price_obj:
                                detailed_price = selected_price_obj.get('price', 0)
                                if detailed_price > 0:
                                    # API ВСЕГДА возвращает цены в фенях (1/100 юаня)
                                    price_cny = detailed_price / 100
                                    price_source = f"price.prices[] (type={selected_type})"
                                    logger.debug(f"   💰 {size_eu} EU: цена type={selected_type} = {price_cny} CNY (было {detailed_price} феней)")
                            else:
                                # КРИТИЧНО: Если в price.prices[] нет допустимых типов - пропускаем!
                                logger.debug(f"   ⏭️  {size_eu} EU (SKU {sku_id}): НЕТ допустимых цен в price.prices[], пропускаем")
                                continue
                
                # Вариант 3: Fallback на authPrice - УДАЛЁН!
                # authPrice не содержит информацию о типе цены, поэтому использовать его НЕЛЬЗЯ
                # Только Варианты 1 и 2 с проверкой типа цены!
                
                # ВАЖНО: Пропускаем если нет цены
                # Размеры без цены НЕ загружаются в БД и на сайт
                if not price_cny or price_cny <= 0:
                    logger.warning(f"   ⚠️ {size_eu} EU: нет цены, размер НЕ ЗАГРУЖАЕТСЯ")
                    self._log_invalid("no_price_for_size")
                    continue
                
                # Применяем формулу цены
                price_rub = price_cny
                if self.price_formula:
                    price_rub = self.price_formula(price_cny)
                
                variants.append({
                    'sku_id': sku_id,  # КРИТИЧНО для БД!
                    'size_eu': size_eu,
                    'size_type': size_type,
                    'price_cny': float(price_cny),
                    'price_rub': float(price_rub),
                    'is_available': True,
                    'stock_status': status,
                    'price_source': price_source  # Для отладки
                })
                
                # Устанавливаем флаг для аксессуаров с ONE SIZE (только если НЕ указан reference_sku_id)
                if size_type == 'accessories' and size_eu == "ONE SIZE" and not reference_sku_id:
                    found_one_size_variant = True
                    logger.debug(f"   ✅ ONE SIZE вариант найден, остальные SKU будут пропущены")
            
            if not variants:
                self._log_invalid("no_valid_variants")
                logger.error(f"❌ Товар {spu_id}: нет валидных размеров после обработки")
                logger.error(f"   Всего SKU: {len(skus)}, priceInfo SKU: {len(price_info_skus)}")
                logger.error(f"   Основной цвет ID: {primary_color_id}")
                logger.error(f"   Размеров в маппинге: {len(property_to_size)}")
                return None
            
            logger.debug(f"✅ Создано вариантов: {len(variants)}")
            
            # Краткая информация о размерах
            # Сортируем по-разному для обуви, одежды и аксессуаров
            if size_type == 'accessories':
                # Для аксессуаров просто берем размеры как есть (обычно ONE SIZE)
                sizes_list = [v['size_eu'] for v in variants]
            elif size_type == 'shoes':
                # Для обуви: пробуем конвертировать в float, если не получается - оставляем как есть
                def safe_float_sort(x):
                    try:
                        return float(x)
                    except (ValueError, TypeError):
                        return 999  # Неконвертируемые значения в конец
                sizes_list = sorted([v['size_eu'] for v in variants], key=safe_float_sort)
            else:
                # Для одежды используем предопределённый порядок
                size_order = {'XXXS': 1, 'XXS': 2, 'XS': 3, 'S': 4, 'M': 5, 'L': 6, 'XL': 7, 'XXL': 8, 'XXXL': 9, '4XL': 10, '5XL': 11, '6XL': 12, '7XL': 13}
                sizes_list = sorted([v['size_eu'] for v in variants], key=lambda x: size_order.get(str(x).upper(), 999))
            
            logger.info(f"📏 Размеры: {', '.join(sizes_list[:5])}{'...' if len(sizes_list) > 5 else ''}")
            
            # Все проверки пройдены
            self.valid_count += 1
            
            result = {
                'spu_id': spu_id,
                'title': title,
                'brand': brand,
                'category': category_name,
                'category_id': category_id,
                'article_number': article_number,
                'main_image_url': all_images[0] if all_images else '',
                'images': all_images,
                'variants': variants,
                'is_active': True
            }
            
            logger.info(f"✅ Товар {spu_id} обработан: {len(variants)} размеров")
            return result
            
        except Exception as e:
            self._log_invalid("processing_error")
            import traceback
            logger.error(f"❌ Ошибка обработки товара: {e}")
            logger.error(f"🔍 Traceback: {traceback.format_exc()}")
            return None
    
    def validate_product(self, product_data: dict) -> Tuple[bool, str]:
        """
        Валидирует данные товара перед сохранением в БД
        
        Args:
            product_data: Данные товара для валидации
            
        Returns:
            Tuple[bool, str]: (валиден, причина невалидности)
        """
        # Проверка наличия обязательных полей
        if not product_data.get('spu_id'):
            return False, "Отсутствует SPU ID"
        
        if not product_data.get('title'):
            return False, "Отсутствует название"
        
        # Проверка изображений
        if not product_data.get('images') or len(product_data['images']) == 0:
            return False, "Нет изображений"
        
        # Проверка размеров
        variants = product_data.get('variants', [])
        if not variants:
            return False, "Нет размеров"
        
        # Проверка что есть хотя бы один валидный размер EU
        has_valid_size = False
        for variant in variants:
            if variant.get('size_eu') and variant.get('is_available'):
                has_valid_size = True
                break
        
        if not has_valid_size:
            return False, "Нет валидных размеров EU"
        
        # Проверка цен
        has_valid_price = False
        for variant in variants:
            if variant.get('price_rub', 0) > 0:
                has_valid_price = True
                break
        
        if not has_valid_price:
            return False, "Нет валидных цен"
        
        # Проверка наличия
        is_available = any(v.get('is_available', False) for v in variants)
        if not is_available:
            return False, "Нет в наличии"
        
        return True, "Valid"
    
    def _log_invalid(self, reason: str):
        """Логирует причину невалидности товара"""
        self.invalid_reasons[reason] = self.invalid_reasons.get(reason, 0) + 1
    
    def get_stats(self) -> Dict:
        """Возвращает статистику обработки"""
        efficiency = (self.valid_count / self.processed_count * 100) if self.processed_count > 0 else 0
        
        return {
            "processed_count": self.processed_count,
            "valid_count": self.valid_count,
            "invalid_count": self.processed_count - self.valid_count,
            "efficiency_percent": efficiency,
            "invalid_reasons": self.invalid_reasons
        }
    
    def get_top_invalid_reasons(self, top_n: int = 5) -> List[Tuple[str, int]]:
        """Возвращает топ причин невалидности"""
        sorted_reasons = sorted(self.invalid_reasons.items(), key=lambda x: x[1], reverse=True)
        return sorted_reasons[:top_n]


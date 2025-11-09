"""
Модель базы данных для PlummyScraper
Центральное хранилище товаров с SQLAlchemy
"""
from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, DECIMAL, DateTime, ForeignKey, Enum, JSON, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
from typing import Optional, Dict
import enum
import logging

logger = logging.getLogger(__name__)

Base = declarative_base()


class SizeType(enum.Enum):
    """Тип размера"""
    shoes = "shoes"
    clothing = "clothing"
    accessories = "accessories"


class SyncAction(enum.Enum):
    """Действие синхронизации"""
    create = "create"
    update = "update"
    delete = "delete"


class SyncStatus(enum.Enum):
    """Статус синхронизации"""
    pending = "pending"
    success = "success"
    failed = "failed"


class Product(Base):
    """Основная таблица товаров"""
    __tablename__ = 'products'
    __table_args__ = (
        # Уникальная комбинация SPU + SKU (один SPU может быть с разными SKU)
        # Это позволяет хранить разные цвета одного товара как отдельные записи
        Index('idx_spu_sku', 'spu_id', 'reference_sku_id', unique=True),
    )
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    spu_id = Column(String(20), nullable=False, index=True)  # Убрали unique=True
    reference_sku_id = Column(String(20), nullable=True, index=True)  # Добавили поле для SKU
    title = Column(String(500))
    brand = Column(String(100))
    category = Column(String(100))
    category_id = Column(Integer)  # ID категории Dewu для маппинга
    category_ids = Column(JSON)  # Список ID категорий WooCommerce
    description = Column(Text)
    article_number = Column(String(100))
    main_image_url = Column(Text)
    images = Column(JSON)  # Список URL изображений
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    data_loaded = Column(Boolean, default=False)  # Флаг: загружены ли данные из API
    
    # Связи
    variants = relationship("ProductVariant", back_populates="product", cascade="all, delete-orphan")
    sync_logs = relationship("WpSyncLog", back_populates="product", cascade="all, delete-orphan")
    
    def __repr__(self):
        sku_part = f", sku={self.reference_sku_id}" if self.reference_sku_id else ""
        return f"<Product(id={self.id}, spu_id='{self.spu_id}'{sku_part}, title='{self.title[:30]}...')>"


class ProductVariant(Base):
    """Размеры и цены товаров"""
    __tablename__ = 'product_variants'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey('products.id'), nullable=False)
    sku_id = Column(String(50))  # SKU ID для сопоставления с API
    size_eu = Column(String(10), nullable=False)  # Европейский размер
    size_type = Column(Enum(SizeType), nullable=False)
    price_cny = Column(DECIMAL(10, 2))  # Цена в юанях
    price_rub = Column(DECIMAL(10, 2))  # Цена в рублях
    is_available = Column(Boolean, default=True)
    stock_status = Column(Integer, default=1)  # 1 = в наличии
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Связь с товаром
    product = relationship("Product", back_populates="variants")
    
    def __repr__(self):
        return f"<ProductVariant(id={self.id}, size={self.size_eu}, price_rub={self.price_rub})>"


class Category(Base):
    """Категории сайта"""
    __tablename__ = 'categories'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    wp_category_id = Column(Integer)  # ID категории в WordPress
    parent_id = Column(Integer, ForeignKey('categories.id'), nullable=True)
    
    # Связь для дерева категорий
    children = relationship("Category", backref='parent', remote_side=[id])
    
    def __repr__(self):
        return f"<Category(id={self.id}, name='{self.name}', wp_id={self.wp_category_id})>"


class WpSyncLog(Base):
    """Лог синхронизации с WordPress"""
    __tablename__ = 'wp_sync_log'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey('products.id'), nullable=False)
    wp_product_id = Column(Integer)  # ID товара в WordPress
    action = Column(Enum(SyncAction), nullable=False)
    sync_status = Column(Enum(SyncStatus), default=SyncStatus.pending)
    error_message = Column(Text)
    synced_at = Column(DateTime, default=datetime.utcnow)
    
    # Связь с товаром
    product = relationship("Product", back_populates="sync_logs")
    
    def __repr__(self):
        return f"<WpSyncLog(id={self.id}, product_id={self.product_id}, action={self.action}, status={self.sync_status})>"


class Database:
    """Класс для работы с базой данных"""
    
    def __init__(self, db_url="sqlite:///plummy_scraper.db"):
        """
        Инициализация базы данных
        
        Args:
            db_url: URL базы данных (SQLite по умолчанию)
        """
        self.engine = create_engine(db_url, echo=False)
        self.Session = sessionmaker(bind=self.engine)
        # Автоматически создаем таблицы если их нет
        self.create_tables()
        logger.info(f"База данных инициализирована: {db_url}")
    
    def create_tables(self):
        """Создает все таблицы в базе данных"""
        Base.metadata.create_all(self.engine)
        logger.info("Таблицы базы данных созданы")
    
    def get_session(self):
        """Возвращает новую сессию базы данных"""
        return self.Session()
    
    def get_product_by_spu_id(self, spu_id: str):
        """Получает товар по SPU ID"""
        from sqlalchemy.orm import joinedload
        
        session = self.get_session()
        try:
            product = session.query(Product).options(
                joinedload(Product.variants)
            ).filter_by(spu_id=spu_id).first()
            
            # Принудительно загружаем variants
            if product:
                _ = product.variants
            
            return product
        finally:
            session.close()
    
    def get_product_by_spu_and_sku(self, spu_id: str, reference_sku_id: str = None):
        """
        Получает товар по SPU ID и опционально SKU ID
        
        Args:
            spu_id: SPU ID товара
            reference_sku_id: SKU ID товара (опционально)
            
        Returns:
            Product or None
        """
        from sqlalchemy.orm import joinedload
        
        session = self.get_session()
        try:
            if reference_sku_id:
                product = session.query(Product).options(
                    joinedload(Product.variants)
                ).filter_by(
                    spu_id=spu_id,
                    reference_sku_id=reference_sku_id
                ).first()
            else:
                product = session.query(Product).options(
                    joinedload(Product.variants)
                ).filter_by(
                    spu_id=spu_id,
                    reference_sku_id=None
                ).first()
            
            # Принудительно загружаем variants
            if product:
                _ = product.variants
            
            return product
        finally:
            session.close()
    
    def add_product_stub(self, spu_id: str, reference_sku_id: str = None, category_ids: list = None, link: str = None):
        """
        Создает "заглушку" товара в БД - только SPU, SKU и категории
        Данные будут загружены позже через load_product_data()
        
        Args:
            spu_id: SPU ID товара
            reference_sku_id: SKU ID (опционально)
            category_ids: Список ID категорий WooCommerce
            link: Исходная ссылка на товар
            
        Returns:
            Product or None
        """
        session = self.get_session()
        try:
            # Проверяем дубликаты
            existing = self.get_product_by_spu_and_sku(spu_id, reference_sku_id)
            if existing:
                logger.info(f"Товар {spu_id} (SKU: {reference_sku_id}) уже существует в БД")
                return existing
            
            # Создаем минимальную запись
            product = Product(
                spu_id=spu_id,
                reference_sku_id=reference_sku_id,
                title=f"SPU {spu_id} (данные загружаются...)",  # Временное название
                category_ids=category_ids or [],
                data_loaded=False,  # ВАЖНО: данные еще не загружены!
                is_active=True
            )
            
            session.add(product)
            session.commit()
            session.refresh(product)
            
            # Принудительно загружаем variants
            _ = product.variants
            
            logger.info(f"Создана заглушка для товара {spu_id} (SKU: {reference_sku_id}), link: {link}")
            return product
            
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка создания заглушки товара {spu_id}: {e}")
            return None
        finally:
            session.close()
    
    def get_products_without_data(self):
        """Возвращает товары у которых data_loaded=False"""
        session = self.get_session()
        try:
            products = session.query(Product).filter(
                Product.data_loaded == False,
                Product.is_active == True
            ).all()
            
            # Принудительно загружаем variants
            for product in products:
                _ = product.variants
            
            return products
        finally:
            session.close()
    
    def add_product(self, product_data: dict, reference_sku_id: str = None, category_ids: list = None):
        """
        Добавляет новый товар в базу данных
        
        Args:
            product_data: Данные товара
            reference_sku_id: SKU ID для идентификации конкретного варианта (цвета)
            category_ids: Список ID категорий WooCommerce для фильтрации
        
        Returns:
            Product: Созданный товар
        """
        from category_filter import CategoryFilter
        
        session = self.get_session()
        try:
            # Используем reference_sku_id из параметра или из product_data
            sku_id = reference_sku_id or product_data.get('reference_sku_id')
            
            # Фильтруем категории по размерам (ТОЛЬКО для обуви при первом добавлении!)
            filtered_category_ids = category_ids or []
            if category_ids and product_data.get('variants'):
                # Получаем размеры и тип товара из вариантов
                sizes = [v['size_eu'] for v in product_data['variants']]
                size_type = product_data['variants'][0].get('size_type', 'shoes')
                
                if size_type == 'shoes' and sizes:
                    # Применяем фильтр только для обуви
                    filter = CategoryFilter()
                    filtered_category_ids = filter.filter_categories(category_ids, sizes, size_type)
                    
                    if filtered_category_ids != category_ids:
                        logger.info(f"📂 Категории отфильтрованы по размерам:")
                        logger.info(f"   Было: {category_ids}")
                        logger.info(f"   Стало: {filtered_category_ids}")
            
            # Сохраняем отфильтрованные категории
            final_category_id = filtered_category_ids[0] if filtered_category_ids else product_data.get('category_id')
            final_category_ids = filtered_category_ids if filtered_category_ids else []
            
            product = Product(
                spu_id=product_data['spu_id'],
                reference_sku_id=sku_id,  # Добавляем SKU ID
                title=product_data['title'],
                brand=product_data.get('brand'),
                category=product_data.get('category'),
                category_id=final_category_id,  # Используем отфильтрованную категорию
                category_ids=final_category_ids,  # Список всех категорий WooCommerce
                description=product_data.get('description'),
                article_number=product_data.get('article_number'),
                main_image_url=product_data.get('main_image_url'),
                images=product_data.get('images', []),
                is_active=product_data.get('is_active', True),
                data_loaded=True  # Данные загружены из API
            )
            
            # Добавляем варианты (размеры)
            for variant_data in product_data.get('variants', []):
                variant = ProductVariant(
                    sku_id=variant_data.get('sku_id'),  # Сохраняем SKU ID
                    size_eu=variant_data['size_eu'],
                    size_type=SizeType(variant_data['size_type']),
                    price_cny=variant_data.get('price_cny'),
                    price_rub=variant_data['price_rub'],
                    is_available=variant_data.get('is_available', True),
                    stock_status=variant_data.get('stock_status', 1)
                )
                product.variants.append(variant)
            
            session.add(product)
            session.commit()
            session.refresh(product)
            
            # Принудительно загружаем variants перед возвратом
            _ = product.variants
            
            logger.info(f"Товар добавлен в БД: {product.spu_id} - {product.title[:50]}")
            return product
            
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка добавления товара в БД: {e}")
            raise
        finally:
            session.close()
    
    def load_product_data(self, product_id: int, product_data: dict):
        """
        Загружает данные для товара-заглушки (где data_loaded=False)
        
        Args:
            product_id: ID товара в БД
            product_data: Полные данные товара из API
            
        Returns:
            bool: True если успешно, False если ошибка
        """
        from category_filter import CategoryFilter
        
        session = self.get_session()
        try:
            product = session.query(Product).filter_by(id=product_id).first()
            if not product:
                logger.error(f"Товар с ID {product_id} не найден")
                return False
            
            # Если данные уже загружены - пропускаем
            if product.data_loaded:
                logger.info(f"Данные для товара {product.spu_id} уже загружены")
                return True
            
            # Фильтруем категории по размерам (ТОЛЬКО для обуви!)
            # ВАЖНО: Конвертируем category_ids в int (они могут быть str после десериализации из JSON)
            filtered_category_ids = [int(cid) for cid in (product.category_ids or [])]
            if product.category_ids and product_data.get('variants'):
                sizes = [v['size_eu'] for v in product_data['variants']]
                size_type = product_data['variants'][0].get('size_type', 'shoes')
                
                if size_type == 'shoes' and sizes:
                    filter = CategoryFilter()
                    # Передаем category_ids как int
                    category_ids_int = [int(cid) for cid in product.category_ids]
                    filtered_category_ids = filter.filter_categories(category_ids_int, sizes, size_type)
                    
                    if filtered_category_ids != product.category_ids:
                        logger.info(f"📂 Категории отфильтрованы по размерам для товара {product.spu_id}:")
                        logger.info(f"   Было: {product.category_ids}")
                        logger.info(f"   Стало: {filtered_category_ids}")
            
            # Обновляем данные товара
            product.title = product_data['title']
            product.brand = product_data.get('brand')
            product.category = product_data.get('category')
            product.category_id = filtered_category_ids[0] if filtered_category_ids else product_data.get('category_id')
            product.category_ids = filtered_category_ids if filtered_category_ids else []
            product.description = product_data.get('description')
            product.article_number = product_data.get('article_number')
            product.main_image_url = product_data.get('main_image_url')
            product.images = product_data.get('images', [])
            product.is_active = product_data.get('is_active', True)
            product.data_loaded = True  # ✅ Данные загружены!
            
            # Удаляем старые варианты (если были) и добавляем новые
            session.query(ProductVariant).filter_by(product_id=product.id).delete()
            
            for variant_data in product_data.get('variants', []):
                variant = ProductVariant(
                    product_id=product.id,
                    sku_id=variant_data.get('sku_id'),  # Сохраняем SKU ID
                    size_eu=variant_data['size_eu'],
                    size_type=SizeType(variant_data['size_type']),
                    price_cny=variant_data.get('price_cny'),
                    price_rub=variant_data['price_rub'],
                    is_available=variant_data.get('is_available', True),
                    stock_status=variant_data.get('stock_status', 1)
                )
                session.add(variant)
            
            session.commit()
            logger.info(f"✅ Данные загружены для товара {product.spu_id} (ID: {product.id})")
            return True
            
        except Exception as e:
            session.rollback()
            logger.error(f"❌ Ошибка загрузки данных для товара ID {product_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
        finally:
            session.close()
    
    def update_product(self, spu_id: str, product_data: dict, reference_sku_id: str = None):
        """
        Обновляет существующий товар
        
        Args:
            spu_id: SPU ID товара
            product_data: Новые данные товара
            reference_sku_id: SKU ID для идентификации (если None, берется из product_data)
        """
        session = self.get_session()
        try:
            # Определяем SKU ID
            sku_id = reference_sku_id or product_data.get('reference_sku_id')
            
            # Ищем товар по SPU + SKU
            if sku_id:
                product = session.query(Product).filter_by(
                    spu_id=spu_id,
                    reference_sku_id=sku_id
                ).first()
            else:
                product = session.query(Product).filter_by(
                    spu_id=spu_id,
                    reference_sku_id=None
                ).first()
            
            if not product:
                sku_info = f" (SKU: {sku_id})" if sku_id else ""
                logger.warning(f"Товар {spu_id}{sku_info} не найден в БД")
                return None
            
            # Обновляем поля товара (НЕ обновляем category_ids - они установлены при добавлении!)
            for key, value in product_data.items():
                if key not in ['variants', 'spu_id', 'reference_sku_id', 'category_ids']:
                    setattr(product, key, value)
            
            product.updated_at = datetime.utcnow()
            
            # Удаляем старые варианты и добавляем новые
            if 'variants' in product_data:
                session.query(ProductVariant).filter_by(product_id=product.id).delete()
                
                for variant_data in product_data['variants']:
                    variant = ProductVariant(
                        product_id=product.id,
                        sku_id=variant_data.get('sku_id'),  # Сохраняем SKU ID
                        size_eu=variant_data['size_eu'],
                        size_type=SizeType(variant_data['size_type']),
                        price_cny=variant_data.get('price_cny'),
                        price_rub=variant_data['price_rub'],
                        is_available=variant_data.get('is_available', True),
                        stock_status=variant_data.get('stock_status', 1)
                    )
                    session.add(variant)
            
            session.commit()
            logger.info(f"Товар обновлен в БД: {spu_id}")
            return product
            
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка обновления товара {spu_id}: {e}")
            raise
        finally:
            session.close()
    
    def get_all_active_products(self):
        """Получает все активные товары с вариантами"""
        from sqlalchemy.orm import joinedload
        
        session = self.get_session()
        try:
            # Загружаем товары вместе с вариантами чтобы избежать lazy loading
            products = session.query(Product).options(
                joinedload(Product.variants)
            ).filter_by(is_active=True).all()
            
            # Принудительно загружаем все данные пока сессия открыта
            for product in products:
                _ = product.variants  # Триггерим загрузку
                for variant in product.variants:
                    _ = variant.size_eu  # Гарантируем загрузку данных вариантов
            
            return products
        finally:
            session.close()
    
    def get_products_needing_sync(self):
        """Получает товары, которые нужно синхронизировать"""
        session = self.get_session()
        try:
            # Товары без успешной синхронизации или с обновлениями
            return session.query(Product).filter(
                Product.is_active == True
            ).outerjoin(WpSyncLog).filter(
                (WpSyncLog.id.is_(None)) | 
                (WpSyncLog.sync_status != SyncStatus.success) |
                (Product.updated_at > WpSyncLog.synced_at)
            ).all()
        finally:
            session.close()
    
    def add_sync_log(self, product_id: int, wp_product_id: int, action: SyncAction, 
                     status: SyncStatus, error_message: str = None):
        """Добавляет запись в лог синхронизации"""
        session = self.get_session()
        try:
            sync_log = WpSyncLog(
                product_id=product_id,
                wp_product_id=wp_product_id,
                action=action,
                sync_status=status,
                error_message=error_message
            )
            session.add(sync_log)
            session.commit()
            logger.debug(f"Лог синхронизации добавлен: product_id={product_id}, action={action}, status={status}")
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка добавления лога синхронизации: {e}")
        finally:
            session.close()
    
    def get_stats(self):
        """Возвращает статистику базы данных"""
        session = self.get_session()
        try:
            total_products = session.query(Product).count()
            active_products = session.query(Product).filter_by(is_active=True).count()
            total_variants = session.query(ProductVariant).count()
            
            sync_success = session.query(WpSyncLog).filter_by(sync_status=SyncStatus.success).count()
            sync_failed = session.query(WpSyncLog).filter_by(sync_status=SyncStatus.failed).count()
            sync_pending = session.query(WpSyncLog).filter_by(sync_status=SyncStatus.pending).count()
            
            return {
                "total_products": total_products,
                "active_products": active_products,
                "total_variants": total_variants,
                "sync_success": sync_success,
                "sync_failed": sync_failed,
                "sync_pending": sync_pending
            }
        finally:
            session.close()

    # ==================== НОВЫЕ МЕТОДЫ ДЛЯ CLI ====================
    
    def add_article(self, article_id: int, spu_id: str, sku_id: str, categories: list):
        """Добавляет артикул в БД"""
        # TODO: Реализовать после создания таблицы articles
        pass
    
    def remove_article(self, spu_id: str, reference_sku_id: str = None):
        """
        Удаляет товар из БД по SPU + SKU ID
        
        Args:
            spu_id: SPU ID товара (строка)
            reference_sku_id: SKU ID для идентификации конкретного варианта
            
        Returns:
            dict: Информация об удалении (wp_id, title, images для удаления медиафайлов)
        """
        session = self.Session()
        try:
            # Находим товар по SPU + SKU
            if reference_sku_id:
                product = session.query(Product).filter(
                    Product.spu_id == spu_id,
                    Product.reference_sku_id == reference_sku_id
                ).first()
            else:
                product = session.query(Product).filter(
                    Product.spu_id == spu_id,
                    Product.reference_sku_id == None
                ).first()
            
            if not product:
                sku_info = f" (SKU: {reference_sku_id})" if reference_sku_id else ""
                logger.warning(f"Товар {spu_id}{sku_info} не найден в БД")
                return None
            
            # Сохраняем info для возврата
            info = {
                'wp_id': None,
                'title': product.title,
                'spu_id': spu_id,
                'reference_sku_id': reference_sku_id,
                'images': product.images or []  # Для удаления медиафайлов
            }
            
            # Получаем WP ID если есть
            wp_log = session.query(WpSyncLog).filter(
                WpSyncLog.product_id == product.id,
                WpSyncLog.sync_status == SyncStatus.success
            ).first()
            
            if wp_log:
                info['wp_id'] = wp_log.wp_product_id
            
            # Удаляем товар (каскадное удаление вариантов и логов)
            session.delete(product)
            session.commit()
            
            sku_info = f" (SKU: {reference_sku_id})" if reference_sku_id else ""
            logger.info(f"Товар {spu_id}{sku_info} удален из БД")
            return info
            
        except Exception as e:
            session.rollback()
            sku_info = f" (SKU: {reference_sku_id})" if reference_sku_id else ""
            logger.error(f"Ошибка удаления товара {spu_id}{sku_info}: {e}")
            raise
        finally:
            session.close()
    
    def article_exists(self, article_id: int) -> bool:
        """Проверяет существование артикула в БД"""
        # TODO: Реализовать
        return False
    
    def is_synced_to_wp(self, article_id: int) -> bool:
        """Проверяет синхронизацию с WP"""
        session = self.Session()
        try:
            # Проверяем наличие записи в wp_sync_log со статусом success
            log = session.query(WpSyncLog).filter(
                WpSyncLog.product_id == article_id,
                WpSyncLog.sync_status == SyncStatus.success
            ).first()
            return log is not None
        finally:
            session.close()
    
    def get_articles_not_in_products(self) -> list:
        """Возвращает артикулы без данных в products"""
        # TODO: Реализовать после создания таблицы articles
        return []
    
    def get_article_by_id(self, article_id: int) -> dict:
        """Получает артикул по ID"""
        # TODO: Реализовать
        return None
    
    def get_articles_count(self) -> int:
        """Возвращает количество артикулов"""
        # TODO: Реализовать
        return 0
    
    def get_articles_in_products_count(self) -> int:
        """Возвращает количество артикулов, загруженных в products"""
        session = self.Session()
        try:
            return session.query(Product).count()
        finally:
            session.close()
    
    def get_synced_products_count(self) -> int:
        """Возвращает количество синхронизированных товаров"""
        session = self.Session()
        try:
            return session.query(WpSyncLog).filter(
                WpSyncLog.sync_status == SyncStatus.success
            ).distinct(WpSyncLog.product_id).count()
        finally:
            session.close()
    
    def get_products_without_article(self) -> list:
        """Возвращает товары без артикула в JSON"""
        # TODO: Реализовать
        return []
    
    def get_products_without_wp_id(self) -> list:
        """Возвращает товары без WP ID"""
        from sqlalchemy.orm import joinedload
        
        session = self.Session()
        try:
            # Получаем товары, у которых нет успешной синхронизации
            synced_product_ids = session.query(WpSyncLog.product_id).filter(
                WpSyncLog.sync_status == SyncStatus.success
            ).distinct()
            
            # Используем joinedload для загрузки variants вместе с Product
            # Это предотвращает ошибку lazy loading после закрытия сессии
            products = session.query(Product).options(
                joinedload(Product.variants)
            ).filter(
                Product.is_active == True,
                ~Product.id.in_(synced_product_ids)
            ).all()
            
            # Принудительно загружаем все атрибуты, чтобы они были доступны после закрытия сессии
            for product in products:
                _ = product.variants  # Триггерим загрузку
            
            return products
        finally:
            session.close()
    
    def get_products_with_wp_id(self) -> list:
        """Возвращает товары с WP ID"""
        from sqlalchemy.orm import joinedload
        
        session = self.Session()
        try:
            synced_product_ids = session.query(WpSyncLog.product_id).filter(
                WpSyncLog.sync_status == SyncStatus.success
            ).distinct()
            
            # Используем joinedload для загрузки variants вместе с Product
            products = session.query(Product).options(
                joinedload(Product.variants)
            ).filter(
                Product.is_active == True,
                Product.id.in_(synced_product_ids)
            ).all()
            
            # Принудительно загружаем все атрибуты
            for product in products:
                _ = product.variants
            
            return products
        finally:
            session.close()
    
    def get_wp_id_for_product(self, product_id: int) -> int:
        """Возвращает WP ID для товара"""
        session = self.Session()
        try:
            log = session.query(WpSyncLog).filter(
                WpSyncLog.product_id == product_id,
                WpSyncLog.sync_status == SyncStatus.success
            ).order_by(WpSyncLog.synced_at.desc()).first()
            
            return log.wp_product_id if log else None
        finally:
            session.close()
    
    def get_product_id_by_wp_id(self, wp_id: int) -> int:
        """Возвращает Product ID по WP ID"""
        session = self.Session()
        try:
            log = session.query(WpSyncLog).filter(
                WpSyncLog.wp_product_id == wp_id,
                WpSyncLog.sync_status == SyncStatus.success
            ).order_by(WpSyncLog.synced_at.desc()).first()
            
            return log.product_id if log else None
        finally:
            session.close()
    
    def save_wp_sync(self, product_id: int, wp_id: int, action: str, status: str):
        """Сохраняет лог синхронизации"""
        self.add_sync_log(product_id, wp_id, 
                         SyncAction[action], 
                         SyncStatus[status])
    
    def get_last_sync_log(self, product_id: int) -> dict:
        """Возвращает последнюю запись синхронизации"""
        session = self.Session()
        try:
            log = session.query(WpSyncLog).filter(
                WpSyncLog.product_id == product_id
            ).order_by(WpSyncLog.synced_at.desc()).first()
            
            if log:
                return {
                    'synced_at': log.synced_at,
                    'action': log.action.value,
                    'status': log.sync_status.value
                }
            return None
        finally:
            session.close()
    
    def get_category_distribution(self) -> dict:
        """Возвращает распределение по категориям"""
        session = self.Session()
        try:
            from sqlalchemy import func
            results = session.query(
                Product.category,
                func.count(Product.id)
            ).group_by(Product.category).all()
            
            return {cat: count for cat, count in results}
        finally:
            session.close()
    
    def get_products_without_category(self) -> list:
        """Возвращает товары без категории"""
        session = self.Session()
        try:
            products = session.query(Product).filter(
                (Product.category == None) | (Product.category == '')
            ).all()
            
            return [{'id': p.id, 'spu_id': p.spu_id, 'title': p.title} 
                   for p in products]
        finally:
            session.close()
    
    def update_product_prices(self, spu_id: str, price_skus: dict, price_formula) -> int:
        """
        Обновляет только цены и варианты товара (размеры, наличие).
        НЕ обновляет основные поля (название, описание, изображения).
        
        Args:
            spu_id: ID товара
            price_skus: Данные о ценах из API (структура priceInfo.skus)
            price_formula: Формула для расчета цены в рублях
            
        Returns:
            Количество обновленных вариантов
        """
        from product_processor import ProductProcessor
        
        session = self.Session()
        try:
            product = session.query(Product).filter(Product.spu_id == spu_id).first()
            if not product:
                logger.warning(f"Товар {spu_id} не найден в БД")
                return 0
            
            # Создаем временный product_data для парсинга
            # Используем существующие данные товара + новые цены
            product_data = {
                'detail': {
                    'spuId': spu_id,
                    'title': product.title,
                    'logo': product.image_url
                },
                'priceInfo': {
                    'skus': price_skus
                },
                'skus': []  # Это будет заполнено при повторном запросе
            }
            
            # ВАЖНО: Для правильного обновления вариантов нам нужны полные данные
            # Поэтому просто обновляем варианты из price_skus напрямую
            
            # Удаляем старые варианты
            old_count = session.query(ProductVariant).filter_by(product_id=product.id).count()
            session.query(ProductVariant).filter_by(product_id=product.id).delete()
            
            # Создаем маппинг SKU -> размер из price_skus
            # Структура: {sku_id: {prices: [...], ...}}
            processor = ProductProcessor(price_formula=price_formula)
            new_variants = []
            
            for sku_id_str, sku_data in price_skus.items():
                if not isinstance(sku_data, dict):
                    continue
                
                prices_list = sku_data.get('prices', [])
                if not prices_list:
                    continue
                
                # Берем первую цену
                price_obj = prices_list[0] if isinstance(prices_list, list) and len(prices_list) > 0 else {}
                if not isinstance(price_obj, dict):
                    continue
                
                # Извлекаем цену
                price_raw = price_obj.get('activePrice') or price_obj.get('price', 0)
                if price_raw <= 0:
                    continue
                
                price_cny = price_raw / 100 if price_raw > 10000 else price_raw
                price_rub = processor.calculate_price(price_cny)
                
                # Извлекаем размер из свойств (нужен size_eu)
                # К сожалению, price_skus не содержит свойств...
                # Поэтому мы НЕ можем обновить размеры без полных данных
                
                # ВЫВОД: update_product_prices не может работать только с price_skus
                # Нужны полные данные товара для маппинга propertyValueId -> размер
                
            logger.warning(f"update_product_prices не может работать только с priceInfo - нужны полные данные товара")
            logger.info(f"Используйте update_product для полного обновления")
            
            session.rollback()
            return 0
            
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка обновления цен {spu_id}: {e}")
            return 0
        finally:
            session.close()
    
    def update_product_prices_only(self, spu_id: str, price_info: dict, reference_sku_id: str = None) -> Optional[Dict]:
        """
        ОПТИМИЗИРОВАННОЕ обновление ТОЛЬКО цен
        
        ВАЖНО: Если у вариантов нет sku_id (старые данные), то обновление будет
        работать ТОЛЬКО для товаров, которые уже имеют правильную структуру.
        Для полного обновления используйте update-db.
        
        Args:
            spu_id: ID товара
            price_info: Данные из get_price_info API (только цены)
            reference_sku_id: Reference SKU ID для фильтрации
            
        Returns:
            dict: {'updated': int, 'added': int, 'removed': int} или None при ошибке
        """
        from sqlalchemy.orm import joinedload
        
        session = self.get_session()
        try:
            # Загружаем товар с вариантами
            if reference_sku_id:
                product = session.query(Product).options(
                    joinedload(Product.variants)
                ).filter(
                    Product.spu_id == spu_id,
                    Product.reference_sku_id == reference_sku_id
                ).first()
            else:
                product = session.query(Product).options(
                    joinedload(Product.variants)
                ).filter(
                    Product.spu_id == spu_id,
                    Product.reference_sku_id == None
                ).first()
            
            if not product:
                logger.warning(f"Товар {spu_id} не найден в БД")
                return None
            
            # Принудительно загружаем variants
            _ = product.variants
            
            # Получаем price_info.skus (словарь sku_id -> данные)
            price_skus = price_info.get('skus', {})
            if not price_skus:
                logger.warning(f"Нет данных о ценах для {spu_id}")
                return {'updated': 0, 'added': 0, 'removed': 0}
            
            # Статистика
            updated_count = 0
            added_count = 0
            removed_count = 0
            
            # Проверяем, есть ли sku_id у вариантов
            variants_with_sku = [v for v in product.variants if v.sku_id]
            
            if not variants_with_sku and product.variants:
                # Старые данные без sku_id - невозможно обновить оптимизированно
                logger.warning(f"Товар {spu_id} имеет варианты без sku_id - используйте update-db")
                return {'updated': 0, 'added': 0, 'removed': 0}
            
            # Создаем маппинг текущих вариантов: sku_id -> variant
            current_variants = {str(v.sku_id): v for v in product.variants if v.sku_id}
            
            # Обрабатываем новые цены
            new_sku_ids = set()
            
            for sku_id_str, sku_data in price_skus.items():
                if not isinstance(sku_data, dict):
                    continue
                
                new_sku_ids.add(sku_id_str)
                
                # Извлекаем цену из prices[]
                prices_list = sku_data.get('prices', [])
                if not prices_list:
                    continue
                
                # Берем первую подходящую цену
                price_raw = 0
                for price_obj in prices_list:
                    if isinstance(price_obj, dict):
                        p = price_obj.get('price', 0)
                        if p > 0:
                            price_raw = p
                            break
                
                if price_raw <= 0:
                    continue
                
                # API ВСЕГДА возвращает цены в фенях (1/100 юаня)
                price_cny = price_raw / 100
                
                # Применяем формулу для расчета RUB
                # Используем primary_category товара
                from price_calculator import price_calculator
                primary_category = product.category_ids[0] if product.category_ids else None
                price_rub = price_calculator.calculate_price(price_cny, primary_category, "21-26 дней")
                
                # Если вариант уже существует - обновляем
                if sku_id_str in current_variants:
                    variant = current_variants[sku_id_str]
                    variant.price_cny = price_cny
                    variant.price_rub = price_rub
                    variant.is_available = True
                    updated_count += 1
                else:
                    # Если варианта нет - НЕ добавляем (нет информации о размере!)
                    # Добавление новых вариантов = задача для полного обновления
                    pass
            
            # Удаляем варианты, которых нет в новых ценах
            for sku_id_str in list(current_variants.keys()):
                if sku_id_str not in new_sku_ids:
                    variant = current_variants[sku_id_str]
                    session.delete(variant)
                    removed_count += 1
            
            session.commit()
            
            result = {
                'updated': updated_count,
                'added': added_count,
                'removed': removed_count
            }
            
            return result
            
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка обновления цен {spu_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
        finally:
            session.close()
    
    def update_product_field(self, product_id: int, field: str, value):
        """Обновляет одно поле товара"""
        session = self.Session()
        try:
            product = session.query(Product).filter(Product.id == product_id).first()
            if product:
                setattr(product, field, value)
                session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка обновления поля {field}: {e}")
        finally:
            session.close()
    
    def get_product_by_id(self, product_id: int):
        """Получает товар по ID"""
        from sqlalchemy.orm import joinedload
        
        session = self.Session()
        try:
            product = session.query(Product).options(
                joinedload(Product.variants)
            ).filter(Product.id == product_id).first()
            
            # Принудительно загружаем variants
            if product:
                _ = product.variants
            
            return product
        finally:
            session.close()
    
    def delete_product(self, product_id: int):
        """Удаляет товар из БД"""
        session = self.Session()
        try:
            product = session.query(Product).filter(Product.id == product_id).first()
            if product:
                session.delete(product)
                session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка удаления товара {product_id}: {e}")
        finally:
            session.close()


db = Database()


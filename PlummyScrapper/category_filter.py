"""
Фильтрация категорий на основе размеров товара
"""
import json
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)


class CategoryFilter:
    """Фильтр категорий по размерам товара"""
    
    # Пороговые значения размеров
    WOMEN_MAX_SIZE = 39.0    # Максимальный женский размер
    MEN_MIN_SIZE = 39.5      # Минимальный мужской размер
    
    # ID родительских категорий ОБУВИ (из plummy_categories.json)
    MEN_PARENT_ID = 101      # "Обувь" мужская - для мужских кроссовок (размеры ≥ 39.5)
    WOMEN_PARENT_ID = 102    # "Обувь" женская - для женских кроссовок (размеры ≤ 39)
    
    # Категории, которые ВСЕГДА должны иметь только ONE SIZE
    # Это аксессуары: кепки, шапки, кошельки, рюкзаки, сумки
    ONE_SIZE_CATEGORIES = {
        # Мужские аксессуары
        119,   # Рюкзаки (М)
        123,   # Кепки (М)
        124,   # Шапки (М)
        125,   # Кошельки и картхолдеры (М)
        # Женские аксессуары
        131,   # Кошельки и картхолдеры (Ж)
        132,   # Шапки (Ж)
        133,   # Кепки (Ж)
        1182,  # Рюкзаки (Ж)
        1183,  # Сумки (Ж)
    }
    
    def __init__(self, categories_file: str = 'plummy_categories.json'):
        """
        Инициализация фильтра
        
        Args:
            categories_file: Путь к файлу категорий
        """
        self.categories_file = categories_file
        self.categories_tree = []
        self.categories_flat = {}  # {id: {name, slug, parent, ...}}
        self.load_categories()
    
    def load_categories(self):
        """Загружает категории из файла"""
        try:
            with open(self.categories_file, 'r', encoding='utf-8') as f:
                self.categories_tree = json.load(f)
            
            # Создаем плоский словарь категорий
            self._flatten_categories(self.categories_tree)
            
            logger.info(f"✅ Загружено {len(self.categories_flat)} категорий для фильтрации")
            
        except FileNotFoundError:
            logger.warning(f"⚠️  Файл {self.categories_file} не найден")
            self.categories_tree = []
            self.categories_flat = {}
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки категорий: {e}")
            self.categories_tree = []
            self.categories_flat = {}
    
    def _flatten_categories(self, cats, result=None):
        """Рекурсивно создает плоский словарь категорий"""
        if result is None:
            result = self.categories_flat
        
        for cat in cats:
            result[cat['id']] = {
                'name': cat['name'],
                'slug': cat['slug'],
                'parent': cat['parent']
            }
            if cat.get('children'):
                self._flatten_categories(cat['children'], result)
        
        return result
    
    def is_child_of(self, category_id: int, parent_id: int) -> bool:
        """
        Проверяет является ли категория ребенком указанного родителя
        
        Args:
            category_id: ID категории для проверки
            parent_id: ID родительской категории
            
        Returns:
            bool: True если category_id является ребенком parent_id
        """
        if category_id not in self.categories_flat:
            return False
        
        # Проверяем прямого родителя
        cat = self.categories_flat[category_id]
        if cat['parent'] == parent_id:
            return True
        
        # Проверяем родителя родителя (рекурсивно)
        if cat['parent'] != 0:
            return self.is_child_of(cat['parent'], parent_id)
        
        return False
    
    def is_shoe_category(self, category_id: int) -> bool:
        """
        Проверяет является ли категория обувной
        
        Args:
            category_id: ID категории для проверки
            
        Returns:
            bool: True если это категория обуви (дочерняя для 101 или 102)
        """
        return self.is_child_of(category_id, self.MEN_PARENT_ID) or \
               self.is_child_of(category_id, self.WOMEN_PARENT_ID) or \
               category_id == self.MEN_PARENT_ID or \
               category_id == self.WOMEN_PARENT_ID
    
    def is_one_size_category(self, category_id: int) -> bool:
        """
        Проверяет является ли категория аксессуаром с ONE SIZE
        
        Args:
            category_id: ID категории для проверки
            
        Returns:
            bool: True если эта категория должна иметь только ONE SIZE
        """
        return category_id in self.ONE_SIZE_CATEGORIES
    
    def has_one_size_category(self, category_ids: List[int]) -> bool:
        """
        Проверяет содержит ли список категорий хотя бы одну категорию с ONE SIZE
        
        Args:
            category_ids: Список ID категорий для проверки
            
        Returns:
            bool: True если хотя бы одна категория должна иметь только ONE SIZE
        """
        return any(cat_id in self.ONE_SIZE_CATEGORIES for cat_id in category_ids)
    
    def get_size_attribute_id(self, category_ids: List[int]) -> int:
        """
        Определяет ID атрибута размера (обувь или одежда) на основе категорий
        
        Args:
            category_ids: Список ID категорий товара
            
        Returns:
            int: 4 для обуви (pa_shoe_size), 5 для одежды (pa_clothing_size)
        """
        # Проверяем является ли хотя бы одна категория обувной
        for cat_id in category_ids:
            if self.is_shoe_category(cat_id):
                logger.debug(f"Категория {cat_id} - обувь → атрибут 4 (pa_shoe_size)")
                return 4  # pa_shoe_size (Размер Обуви)
        
        # Если ни одна категория не обувная - это одежда
        logger.debug(f"Категории {category_ids} - одежда → атрибут 5 (pa_clothing_size)")
        return 5  # pa_clothing_size (Размер)
    
    def analyze_sizes(self, sizes: List[str]) -> Tuple[bool, bool]:
        """
        Анализирует размеры товара
        
        Args:
            sizes: Список размеров (например, ['39', '40', '41.5'])
            
        Returns:
            Tuple[bool, bool]: (has_women_sizes, has_men_sizes)
        """
        has_women = False  # Есть ли размеры ≤ 39
        has_men = False    # Есть ли размеры ≥ 39.5
        
        for size in sizes:
            try:
                size_float = float(size)
                
                if size_float <= self.WOMEN_MAX_SIZE:
                    has_women = True
                
                if size_float >= self.MEN_MIN_SIZE:
                    has_men = True
                    
            except (ValueError, TypeError):
                # Если размер не число (например, "S", "M"), игнорируем
                continue
        
        return has_women, has_men
    
    def filter_categories(self, category_ids: List[int], sizes: List[str], size_type: str = 'shoes') -> List[int]:
        """
        Фильтрует категории на основе размеров товара
        
        ВАЖНО: Фильтрация применяется ТОЛЬКО для обуви (size_type='shoes')!
        Для одежды все категории остаются без изменений.
        
        Args:
            category_ids: Список ID категорий, введенных пользователем
            sizes: Список размеров товара
            size_type: Тип размера ('shoes' или 'clothing')
            
        Returns:
            List[int]: Отфильтрованный список ID категорий
        """
        if not category_ids or not sizes:
            return category_ids
        
        # ФИЛЬТРАЦИЯ ТОЛЬКО ДЛЯ ОБУВИ!
        if size_type != 'shoes':
            logger.info(f"ℹ️  Товар не обувь (type={size_type}), фильтрация категорий пропущена")
            return category_ids
        
        # Разделяем категории на группы
        men_categories = []      # Дети категории 101 (Обувь мужская)
        women_categories = []    # Дети категории 102 (Обувь женская)
        other_categories = []    # Остальные
        
        for cat_id in category_ids:
            if self.is_child_of(cat_id, self.MEN_PARENT_ID):
                men_categories.append(cat_id)
            elif self.is_child_of(cat_id, self.WOMEN_PARENT_ID):
                women_categories.append(cat_id)
            else:
                other_categories.append(cat_id)
        
        # Анализируем размеры
        has_women, has_men = self.analyze_sizes(sizes)
        
        logger.info(f"📏 Анализ размеров: женские≤39={has_women}, мужские≥39.5={has_men}")
        logger.info(f"📂 Категории: мужские(101)={len(men_categories)}, женские(102)={len(women_categories)}, остальные={len(other_categories)}")
        
        # Применяем логику фильтрации
        result = other_categories.copy()  # Всегда оставляем "остальные"
        
        if has_women and has_men:
            # Оба условия выполняются → ВСЕ категории остаются
            result.extend(men_categories)
            result.extend(women_categories)
            logger.info(f"✅ Товар унисекс: оставляем все категории ({len(result)})")
        
        elif has_women:
            # Только женские размеры → только категории-дети 102
            result.extend(women_categories)
            if men_categories:
                logger.info(f"🚫 Удалены мужские категории (101): {men_categories}")
            logger.info(f"✅ Товар женский: оставлены категории ({len(result)})")
        
        elif has_men:
            # Только мужские размеры → только категории-дети 101
            result.extend(men_categories)
            if women_categories:
                logger.info(f"🚫 Удалены женские категории (102): {women_categories}")
            logger.info(f"✅ Товар мужской: оставлены категории ({len(result)})")
        
        else:
            # Нет размеров для анализа → все категории
            result.extend(men_categories)
            result.extend(women_categories)
            logger.info(f"⚠️  Нет числовых размеров для анализа, оставляем все категории")
        
        return result


# Глобальный экземпляр фильтра
category_filter = CategoryFilter()


def filter_categories_by_sizes(category_ids: List[int], sizes: List[str], size_type: str = 'shoes') -> List[int]:
    """
    Вспомогательная функция для фильтрации категорий
    
    ВАЖНО: Фильтрация применяется ТОЛЬКО для обуви!
    
    Args:
        category_ids: Список ID категорий
        sizes: Список размеров товара
        size_type: Тип размера ('shoes' или 'clothing')
        
    Returns:
        List[int]: Отфильтрованный список категорий
    """
    return category_filter.filter_categories(category_ids, sizes, size_type)


def get_size_attribute_id_for_categories(category_ids: List[int]) -> int:
    """
    Определяет ID атрибута размера на основе категорий товара
    
    Args:
        category_ids: Список ID категорий WooCommerce
        
    Returns:
        int: 4 для обуви (pa_shoe_size), 5 для одежды (pa_clothing_size)
        
    Example:
        >>> get_size_attribute_id_for_categories([103, 154])  # Кроссовки
        4  # pa_shoe_size
        
        >>> get_size_attribute_id_for_categories([106, 151])  # Футболки
        5  # pa_clothing_size
    """
    return category_filter.get_size_attribute_id(category_ids)


def is_one_size_category_check(category_ids: List[int]) -> bool:
    """
    Проверяет содержит ли список категорий хотя бы одну категорию с ONE SIZE
    
    Args:
        category_ids: Список ID категорий WooCommerce
        
    Returns:
        bool: True если хотя бы одна категория должна иметь только ONE SIZE
        
    Example:
        >>> is_one_size_category_check([123, 125])  # Кепки, Кошельки (М)
        True
        
        >>> is_one_size_category_check([103, 154])  # Кроссовки
        False
    """
    return category_filter.has_one_size_category(category_ids)


"""
Калькулятор цен с поддержкой формул для разных категорий и сроков доставки
"""
import json
import logging
from typing import Dict, Tuple

logger = logging.getLogger(__name__)


class PriceCalculator:
    """Калькулятор цен с формулами по категориям"""
    
    DELIVERY_OPTIONS = ["21-26 дней", "10-14 дней"]
    
    def __init__(self, config_file: str = 'price_formulas.json'):
        """
        Инициализация калькулятора
        
        Args:
            config_file: Путь к файлу конфигурации формул
        """
        self.config_file = config_file
        self.parameters = {}
        self.formulas = {}
        self.default_formula = {}
        self.load_config()
    
    def load_config(self):
        """Загружает конфигурацию формул из файла"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            self.parameters = config.get('parameters', {})
            formulas_config = config.get('formulas', {})
            
            self.default_formula = formulas_config.get('default', {})
            self.formulas = formulas_config.get('categories', {})
            
            logger.info(f"✅ Загружены формулы для {len(self.formulas)} категорий")
            logger.info(f"   Параметры: a={self.parameters.get('a')}, b={self.parameters.get('b')}, c={self.parameters.get('c')}")
            
        except FileNotFoundError:
            logger.warning(f"⚠️  Файл {self.config_file} не найден, используются формулы по умолчанию")
            self._set_defaults()
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки конфигурации: {e}")
            self._set_defaults()
    
    def _set_defaults(self):
        """Устанавливает формулы по умолчанию"""
        self.parameters = {"a": 12, "b": 1.2, "c": 6}
        self.default_formula = {
            "21-26 дней": "(x * a + 400) * b",
            "10-14 дней": "(x * a + 400) * b + 600"
        }
        self.formulas = {}
    
    def get_formula(self, category_id: int, delivery_days: str) -> str:
        """
        Получает формулу для категории и срока доставки
        
        Args:
            category_id: ID категории WooCommerce
            delivery_days: Срок доставки ("21-26 дней" или "10-14 дней")
            
        Returns:
            str: Формула в виде строки
        """
        # Проверяем есть ли формула для конкретной категории
        category_key = str(category_id)
        
        if category_key in self.formulas:
            category_formulas = self.formulas[category_key]
            if delivery_days in category_formulas:
                return category_formulas[delivery_days]
        
        # Возвращаем формулу по умолчанию
        return self.default_formula.get(delivery_days, "(x * a + 400) * b")
    
    def calculate_price(self, price_cny: float, category_id: int, delivery_days: str) -> float:
        """
        Вычисляет цену по формуле
        
        Args:
            price_cny: Цена в CNY
            category_id: ID категории WooCommerce
            delivery_days: Срок доставки
            
        Returns:
            float: Цена в RUB
        """
        formula_str = self.get_formula(category_id, delivery_days)
        
        # Подготавливаем переменные для eval
        # Конвертируем в float на случай если пришел Decimal
        x = float(price_cny)
        a = self.parameters.get('a', 12)
        b = self.parameters.get('b', 1.2)
        c = self.parameters.get('c', 6)
        
        try:
            # Вычисляем формулу
            price_rub = eval(formula_str)
            
            logger.debug(f"💰 Цена: {price_cny} CNY → {price_rub:.0f} RUB")
            logger.debug(f"   Категория: {category_id}, Доставка: {delivery_days}")
            logger.debug(f"   Формула: {formula_str}")
            
            return round(price_rub, 2)
            
        except Exception as e:
            logger.error(f"❌ Ошибка вычисления формулы '{formula_str}': {e}")
            # Fallback на простую формулу
            return round(float(price_cny) * 2.5, 2)
    
    def calculate_prices_for_variant(self, price_cny: float, category_id: int) -> Dict[str, float]:
        """
        Вычисляет цены для всех вариантов доставки
        
        Args:
            price_cny: Цена в CNY
            category_id: ID категории WooCommerce
            
        Returns:
            Dict[str, float]: Словарь {срок_доставки: цена_rub}
        """
        prices = {}
        
        for delivery_days in self.DELIVERY_OPTIONS:
            prices[delivery_days] = self.calculate_price(price_cny, category_id, delivery_days)
        
        return prices
    
    def get_delivery_options(self) -> list:
        """Возвращает список доступных сроков доставки"""
        return self.DELIVERY_OPTIONS.copy()


# Глобальный экземпляр калькулятора
price_calculator = PriceCalculator()


def reload_config():
    """Перезагружает конфигурацию формул"""
    price_calculator.load_config()
    logger.info("🔄 Конфигурация формул перезагружена")


"""
Декоратор для измерения времени выполнения команд
"""
import time
import functools
import click


def timer(func):
    """
    Декоратор для измерения времени выполнения функции
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        
        # Выполняем функцию
        result = func(*args, **kwargs)
        
        # Вычисляем время
        elapsed_time = time.time() - start_time
        
        # Форматируем время
        if elapsed_time < 60:
            time_str = f"{elapsed_time:.2f} сек"
        else:
            minutes = int(elapsed_time // 60)
            seconds = elapsed_time % 60
            time_str = f"{minutes} мин {seconds:.2f} сек"
        
        click.echo(f"\n⏱️  Время выполнения: {time_str}")
        
        return result
    
    return wrapper


def timer_with_count(item_name="товаров"):
    """
    Декоратор для измерения времени с подсчетом среднего времени на элемент
    
    Args:
        item_name: Название элементов для отображения (например, "товаров", "ссылок")
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            
            # Выполняем функцию
            result = func(*args, **kwargs)
            
            # Пытаемся получить количество обработанных элементов из result
            item_count = None
            if isinstance(result, dict):
                # Если функция возвращает словарь, ищем ключи с количеством
                item_count = result.get('count') or result.get('total') or result.get('processed')
            elif isinstance(result, (list, tuple)):
                item_count = len(result)
            elif isinstance(result, int):
                item_count = result
            
            # Вычисляем время
            elapsed_time = time.time() - start_time
            
            # Форматируем общее время
            if elapsed_time < 60:
                time_str = f"{elapsed_time:.2f} сек"
            else:
                minutes = int(elapsed_time // 60)
                seconds = elapsed_time % 60
                time_str = f"{minutes} мин {seconds:.2f} сек"
            
            click.echo(f"\n{'='*60}")
            click.echo(f"⏱️  Время выполнения: {time_str}")
            
            # Если известно количество элементов, показываем среднее время
            if item_count and item_count > 0:
                avg_time = elapsed_time / item_count
                if avg_time < 1:
                    avg_str = f"{avg_time*1000:.0f} мс"
                else:
                    avg_str = f"{avg_time:.2f} сек"
                
                click.echo(f"📊 Среднее время на 1 {item_name[:-2] if item_name.endswith('ов') else item_name}: {avg_str}")
                click.echo(f"📈 Обработано {item_name}: {item_count}")
            
            click.echo(f"{'='*60}\n")
            
            return result
        
        return wrapper
    
    return decorator


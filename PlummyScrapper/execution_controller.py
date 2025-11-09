"""
Система управления выполнением команд с паузой, возобновлением и перезапуском
"""
import asyncio
import json
import os
import sys
import threading
from pathlib import Path
from typing import Optional, Dict, Any, Callable
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class ExecutionController:
    """
    Контроллер выполнения команд с поддержкой:
    - Паузы (p)
    - Возобновления после перезапуска
    - Перезапуска команды (restartthis)
    """
    
    def __init__(self, state_file: str = "execution_state.json"):
        self.state_file = Path(state_file)
        self.paused = False
        self.restart_requested = False
        self.stop_monitoring = False
        self.current_command = None
        self.current_state = {}
        
    def load_state(self, command_name: str) -> Optional[Dict[str, Any]]:
        """Загружает сохраненное состояние команды"""
        if not self.state_file.exists():
            return None
        
        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            if command_name in data:
                state = data[command_name]
                print(f"\n🔄 Найдено сохраненное состояние для команды '{command_name}':")
                print(f"   📅 Дата: {state.get('timestamp', 'N/A')}")
                print(f"   📊 Прогресс: {state.get('current_index', 0)}/{state.get('total_items', 0)}")
                
                resume = input("\n❓ Продолжить с этого места? (y/n, Enter=y): ").strip().lower()
                if resume in ['', 'y', 'yes', 'д', 'да']:
                    print("✅ Продолжаем с сохраненного места!\n")
                    return state
                else:
                    print("🔄 Начинаем заново!\n")
                    self._clear_state(command_name)
                    return None
            
            return None
        except Exception as e:
            logger.error(f"Ошибка загрузки состояния: {e}")
            return None
    
    def save_state(self, command_name: str, state: Dict[str, Any]):
        """Сохраняет текущее состояние команды"""
        try:
            # Загружаем существующие состояния
            data = {}
            if self.state_file.exists():
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            
            # Обновляем состояние команды
            state['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            data[command_name] = state
            
            # Сохраняем
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
        except Exception as e:
            logger.error(f"Ошибка сохранения состояния: {e}")
    
    def _clear_state(self, command_name: str):
        """Удаляет сохраненное состояние команды"""
        try:
            if self.state_file.exists():
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if command_name in data:
                    del data[command_name]
                    
                with open(self.state_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Ошибка очистки состояния: {e}")
    
    def clear_state_on_completion(self, command_name: str):
        """Удаляет состояние после успешного завершения команды"""
        self._clear_state(command_name)
        print(f"\n✅ Состояние команды '{command_name}' очищено")
    
    def monitor_input(self):
        """
        Мониторит ввод пользователя в отдельном потоке
        Команды:
        - 'p' или 'pause' - пауза
        - 'restartthis' - перезапуск команды
        """
        def input_thread():
            while not self.stop_monitoring:
                try:
                    # Используем select для неблокирующего ввода (только Unix)
                    if sys.platform != 'win32':
                        import select
                        if select.select([sys.stdin], [], [], 0.1)[0]:
                            line = sys.stdin.readline().strip().lower()
                            self._process_command(line)
                    else:
                        # Для Windows используем простой input (блокирующий)
                        # В реальности нужно использовать msvcrt, но для простоты оставляем так
                        pass
                except Exception as e:
                    logger.error(f"Ошибка мониторинга ввода: {e}")
        
        # Запускаем в отдельном потоке
        thread = threading.Thread(target=input_thread, daemon=True)
        thread.start()
    
    def _process_command(self, command: str):
        """Обрабатывает команду от пользователя"""
        if command in ['p', 'pause', 'пауза']:
            self.paused = True
            print("\n" + "="*60)
            print("⏸️  ПАУЗА")
            print("="*60)
            print("Команды:")
            print("  'c' или 'continue' - продолжить")
            print("  'restartthis' - перезапустить команду с начала")
            print("  'q' или 'quit' - выйти (состояние сохранится)")
            print("="*60)
            
        elif command in ['restartthis', 'restart']:
            self.restart_requested = True
            self.paused = False
            print("\n🔄 Команда будет перезапущена с начала!")
            
        elif command in ['c', 'continue', 'продолжить']:
            if self.paused:
                self.paused = False
                print("\n▶️  Продолжаем выполнение...\n")
        
        elif command in ['q', 'quit', 'выход']:
            print("\n👋 Выход... Состояние сохранено!")
            self.stop_monitoring = True
            sys.exit(0)
    
    async def check_pause(self, command_name: str, current_index: int, total_items: int):
        """
        Проверяет, нужно ли приостановить выполнение
        Сохраняет состояние при паузе
        
        Returns:
            bool: True если нужно продолжить, False если нужно перезапустить
        """
        if self.restart_requested:
            print("\n🔄 ПЕРЕЗАПУСК КОМАНДЫ...\n")
            self._clear_state(command_name)
            self.restart_requested = False
            return False
        
        if self.paused:
            # Сохраняем текущее состояние
            state = {
                'current_index': current_index,
                'total_items': total_items,
                'command': command_name
            }
            self.save_state(command_name, state)
            print(f"💾 Состояние сохранено: {current_index}/{total_items}")
            
            # Ждем продолжения
            while self.paused and not self.restart_requested:
                await asyncio.sleep(0.5)
            
            if self.restart_requested:
                print("\n🔄 ПЕРЕЗАПУСК КОМАНДЫ...\n")
                self._clear_state(command_name)
                self.restart_requested = False
                return False
        
        return True
    
    def start_monitoring(self, command_name: str):
        """Запускает мониторинг для команды"""
        self.current_command = command_name
        self.paused = False
        self.restart_requested = False
        self.stop_monitoring = False
        
        print("\n" + "="*60)
        print("⌨️  УПРАВЛЕНИЕ КОМАНДОЙ:")
        print("="*60)
        print("  'p' или 'pause'      - поставить на паузу")
        print("  'restartthis'        - перезапустить с начала")
        print("="*60 + "\n")
        
        # Запускаем мониторинг (для Unix систем)
        if sys.platform != 'win32':
            self.monitor_input()
    
    def stop_monitoring_cmd(self):
        """Останавливает мониторинг"""
        self.stop_monitoring = True


# Глобальный экземпляр
execution_controller = ExecutionController()


def with_execution_control(command_name: str):
    """
    Декоратор для команд с поддержкой управления выполнением
    
    Использование:
        @with_execution_control("update-db")
        async def update_db():
            ...
    """
    def decorator(func: Callable):
        async def wrapper(*args, **kwargs):
            # Загружаем сохраненное состояние
            saved_state = execution_controller.load_state(command_name)
            
            # Запускаем мониторинг
            execution_controller.start_monitoring(command_name)
            
            try:
                # Выполняем команду с передачей состояния
                result = await func(*args, saved_state=saved_state, **kwargs)
                
                # Очищаем состояние после успешного завершения
                execution_controller.clear_state_on_completion(command_name)
                
                return result
            finally:
                # Останавливаем мониторинг
                execution_controller.stop_monitoring_cmd()
        
        return wrapper
    return decorator


async def pausable_loop(items: list, command_name: str, process_func: Callable, 
                       start_index: int = 0):
    """
    Вспомогательная функция для создания циклов с поддержкой паузы
    
    Args:
        items: Список элементов для обработки
        command_name: Имя команды (для сохранения состояния)
        process_func: Асинхронная функция обработки (item, index) -> result
        start_index: Индекс начала (для возобновления)
    
    Returns:
        tuple: (успешно_обработано, провалено, результаты)
    """
    results = []
    success_count = 0
    failed_count = 0
    
    i = start_index
    while i < len(items):
        item = items[i]
        
        # Проверяем паузу и перезапуск
        should_continue = await execution_controller.check_pause(
            command_name, i, len(items)
        )
        
        if not should_continue:
            # Перезапуск - начинаем с начала
            i = 0
            results = []
            success_count = 0
            failed_count = 0
            continue
        
        # Обрабатываем элемент
        try:
            result = await process_func(item, i)
            if result:
                success_count += 1
                results.append(result)
            else:
                failed_count += 1
        except Exception as e:
            logger.error(f"Ошибка обработки элемента {i}: {e}")
            failed_count += 1
        
        i += 1
    
    return success_count, failed_count, results


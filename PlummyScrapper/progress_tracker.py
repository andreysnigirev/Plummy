"""
Progress Tracker для сохранения и восстановления прогресса выполнения
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)


class ProgressTracker:
    """
    Отслеживает и сохраняет прогресс выполнения команд
    Позволяет продолжить выполнение после сбоя
    """
    
    def __init__(self, progress_file: str = 'progress.json'):
        """
        Args:
            progress_file: Путь к файлу прогресса
        """
        self.progress_file = Path(progress_file)
        self.current_task: Optional[Dict] = None
        self.load_progress()
    
    def load_progress(self):
        """Загружает прогресс из файла"""
        if self.progress_file.exists():
            try:
                with open(self.progress_file, 'r', encoding='utf-8') as f:
                    self.current_task = json.load(f)
                    logger.info(f"📂 Загружен прогресс: {self.current_task.get('command')} "
                               f"({self.current_task.get('processed')}/{self.current_task.get('total')} выполнено)")
            except Exception as e:
                logger.error(f"❌ Ошибка загрузки прогресса: {e}")
                self.current_task = None
        else:
            self.current_task = None
    
    def start_task(self, command: str, total_items: int, items: List):
        """
        Начинает новую задачу
        
        Args:
            command: Название команды (update-db, sync-new и т.д.)
            total_items: Общее количество элементов
            items: Список элементов для обработки
        """
        self.current_task = {
            'command': command,
            'total': total_items,
            'processed': 0,
            'failed': 0,
            'skipped': 0,
            'items': items,
            'processed_ids': [],
            'failed_ids': [],
            'started_at': datetime.now().isoformat(),
            'last_update': datetime.now().isoformat()
        }
        self.save_progress()
        logger.info(f"🚀 Начата задача '{command}': {total_items} элементов")
    
    def mark_processed(self, item_id: str, success: bool = True):
        """
        Отмечает элемент как обработанный
        
        Args:
            item_id: ID обработанного элемента
            success: Успешно ли обработан элемент
        """
        if not self.current_task:
            return
        
        self.current_task['processed'] += 1
        self.current_task['last_update'] = datetime.now().isoformat()
        
        if success:
            self.current_task['processed_ids'].append(item_id)
        else:
            self.current_task['failed'] += 1
            self.current_task['failed_ids'].append(item_id)
        
        # Автосохранение каждые 10 элементов
        if self.current_task['processed'] % 10 == 0:
            self.save_progress()
            logger.debug(f"💾 Прогресс сохранен: {self.current_task['processed']}/{self.current_task['total']}")
    
    def mark_skipped(self, item_id: str):
        """Отмечает элемент как пропущенный"""
        if not self.current_task:
            return
        
        self.current_task['skipped'] += 1
        self.current_task['last_update'] = datetime.now().isoformat()
    
    def save_progress(self):
        """Сохраняет прогресс в файл"""
        if not self.current_task:
            return
        
        try:
            with open(self.progress_file, 'w', encoding='utf-8') as f:
                json.dump(self.current_task, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения прогресса: {e}")
    
    def finish_task(self):
        """Завершает текущую задачу"""
        if not self.current_task:
            return
        
        self.current_task['finished_at'] = datetime.now().isoformat()
        self.current_task['status'] = 'completed'
        self.save_progress()
        
        logger.info(f"✅ Задача '{self.current_task['command']}' завершена:")
        logger.info(f"   ✅ Обработано: {self.current_task['processed']}/{self.current_task['total']}")
        logger.info(f"   ❌ Ошибок: {self.current_task['failed']}")
        logger.info(f"   ⏭️  Пропущено: {self.current_task['skipped']}")
        
        # Очищаем файл прогресса
        if self.progress_file.exists():
            self.progress_file.unlink()
        
        self.current_task = None
    
    def can_resume(self) -> bool:
        """Проверяет, можно ли продолжить выполнение"""
        if not self.current_task:
            return False
        
        return (self.current_task.get('status') != 'completed' and
                self.current_task.get('processed', 0) < self.current_task.get('total', 0))
    
    def get_remaining_items(self) -> List:
        """Возвращает список необработанных элементов"""
        if not self.current_task:
            return []
        
        all_items = self.current_task.get('items', [])
        processed_ids = set(self.current_task.get('processed_ids', []))
        
        # Возвращаем элементы, которые еще не обработаны
        return [item for item in all_items if str(item.get('spu_id')) not in processed_ids]
    
    def get_stats(self) -> Dict:
        """Возвращает статистику текущей задачи"""
        if not self.current_task:
            return {}
        
        total = self.current_task.get('total', 0)
        processed = self.current_task.get('processed', 0)
        failed = self.current_task.get('failed', 0)
        
        progress_percent = (processed / total * 100) if total > 0 else 0
        
        return {
            'command': self.current_task.get('command'),
            'total': total,
            'processed': processed,
            'failed': failed,
            'skipped': self.current_task.get('skipped', 0),
            'progress_percent': round(progress_percent, 1),
            'remaining': total - processed
        }
    
    def print_progress_bar(self, prefix: str = "Progress"):
        """Выводит progress bar в консоль"""
        if not self.current_task:
            return
        
        stats = self.get_stats()
        total = stats['total']
        processed = stats['processed']
        percent = stats['progress_percent']
        
        # Progress bar длиной 40 символов
        bar_length = 40
        filled = int(bar_length * percent / 100)
        bar = '█' * filled + '░' * (bar_length - filled)
        
        print(f"\r{prefix}: |{bar}| {percent:.1f}% ({processed}/{total})", end='', flush=True)


# Глобальный экземпляр progress tracker
progress_tracker = ProgressTracker()


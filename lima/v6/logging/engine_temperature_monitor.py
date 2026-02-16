import time
import threading
from .logger import logger

class EngineTemperatureMonitor:
    def __init__(self, read_temperature_func, interval_ms=200):
        self.read_temperature_func = read_temperature_func
        self.interval = interval_ms / 1000.0
        self._running = False
        self._thread = None

    def _monitor(self):
        logger.info('Engine temperature monitoring started')
        while self._running:
            temp = self.read_temperature_func()
            logger.info(f'Engine temperature: {temp}°C')
            time.sleep(self.interval)

    def start(self):
        if not self._running:
            self._running = True
            self._thread = threading.Thread(target=self._monitor)
            self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join()
            logger.info('Engine temperature monitoring stopped')

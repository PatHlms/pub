from .logging.logger import logger

class OilTemperatureFaultCodeReader:
    def read_fault_code(self):
        logger.info('Reading oil temperature fault code from engine management system')
        # Placeholder: Simulate reading oil temperature fault code
        return {'code': 'P5678', 'description': 'Oil temperature too high'}

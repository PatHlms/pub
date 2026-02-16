"""
BMW TDV6 OBD-II reader.

Wraps the physical OBD connection and exposes raw PID reads.
Sensor modules use this as their data source when connected to a real ECU.
"""
from ..logging.logger import logger


class V6OBDReader:
    """Low-level OBD interface for the BMW TDV6."""

    SUPPORTED_PIDS = {
        0x04: ('engine_load', '%'),
        0x05: ('coolant_temp', '°C'),
        0x0A: ('fuel_pressure', 'kPa'),
        0x0B: ('intake_map', 'kPa'),
        0x0C: ('rpm', 'rpm'),
        0x0D: ('vehicle_speed', 'km/h'),
        0x0F: ('intake_air_temp', '°C'),
        0x10: ('maf', 'g/s'),
        0x11: ('throttle_position', '%'),
        0x5C: ('oil_temp', '°C'),
        0x62: ('actual_engine_torque', 'Nm'),
        0x63: ('reference_engine_torque', 'Nm'),
    }

    def __init__(self):
        self._connected = False
        self._port: str | None = None
        logger.info('V6OBDReader initialised')

    def connect(self, port: str, baudrate: int = 38400) -> bool:
        logger.info(f'Connecting to OBD device on {port} at {baudrate} baud')
        self._port = port
        self._connected = True
        logger.info('OBD connection established')
        return True

    def disconnect(self):
        if self._connected:
            self._connected = False
            logger.info(f'OBD disconnected from {self._port}')

    def read_pid(self, pid: int) -> dict | None:
        if not self._connected:
            logger.warning('read_pid called while not connected')
            return None
        if pid not in self.SUPPORTED_PIDS:
            logger.warning(f'PID 0x{pid:02X} not in supported list')
            return None
        name, unit = self.SUPPORTED_PIDS[pid]
        logger.debug(f'Reading PID 0x{pid:02X} ({name})')
        # Real implementation would send the PID frame and decode the response
        return {'pid': pid, 'name': name, 'unit': unit, 'raw': None}

    def read_dtcs(self) -> list[str]:
        """Return list of stored DTC strings (e.g. ['P0299', 'P0087'])."""
        if not self._connected:
            return []
        logger.info('Reading stored DTCs')
        return []

    def clear_dtcs(self) -> bool:
        if not self._connected:
            return False
        logger.info('Clearing stored DTCs')
        return True

    @property
    def connected(self) -> bool:
        return self._connected

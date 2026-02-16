"""
lima.v6 — BMW TDV6 engine diagnostics package.

Quick start:
    from lima.v6 import BMWTDV6Engine

    with BMWTDV6Engine(vehicle_id='E60-530d') as engine:
        report = engine.print_report()
"""
from .engine import BMWTDV6Engine
from .sensors import (
    TurbochargerSensor, OilTemperatureSensor, CoolantTemperatureSensor,
    DPFSensor, EGRSensor, FuelPressureSensor, MAFSensor,
    BoostPressureSensor, GlowPlugSensor, SwirlFlapSensor,
    InjectorSensor, NOxSensor,
)
from .events import EventBus, EventFeed, Event, EventType, Severity
from .reporting import DiagnosticReport, ReportGenerator
from .obd import V6OBDReader, VAGCommIntegration

__all__ = [
    'BMWTDV6Engine',
    'TurbochargerSensor', 'OilTemperatureSensor', 'CoolantTemperatureSensor',
    'DPFSensor', 'EGRSensor', 'FuelPressureSensor', 'MAFSensor',
    'BoostPressureSensor', 'GlowPlugSensor', 'SwirlFlapSensor',
    'InjectorSensor', 'NOxSensor',
    'EventBus', 'EventFeed', 'Event', 'EventType', 'Severity',
    'DiagnosticReport', 'ReportGenerator',
    'V6OBDReader', 'VAGCommIntegration',
]

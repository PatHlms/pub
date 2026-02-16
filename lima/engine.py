"""
BMW TDV6 Engine Diagnostic Orchestrator.

Wires together all sensor modules, the event feed, event bus,
and reporting output into a single coherent diagnostic session.

Usage (minimal):
    from lima.v6.engine import BMWTDV6Engine

    engine = BMWTDV6Engine(vehicle_id='E60-530d')
    engine.start()                   # starts continuous event feed
    report = engine.snapshot()       # one-shot diagnostic report
    engine.stop()
"""
import signal
import sys
from typing import Optional

from .logging.logger import logger
from .obd.reader import V6OBDReader
from .obd.vagcomm import VAGCommIntegration
from .sensors import (
    TurbochargerSensor, OilTemperatureSensor, CoolantTemperatureSensor,
    DPFSensor, EGRSensor, FuelPressureSensor, MAFSensor,
    BoostPressureSensor, GlowPlugSensor, SwirlFlapSensor,
    InjectorSensor, NOxSensor,
)
from .events import EventBus, EventFeed, Event, EventType, Severity
from .reporting import ReportGenerator
from .reporting import console as console_reporter
from .reporting import json_reporter
from .reporting import html_reporter


class BMWTDV6Engine:
    """
    Top-level orchestrator for BMW TDV6 diagnostics.

    Parameters
    ----------
    vehicle_id      : Identifier for the vehicle (used in reports)
    poll_interval_ms: How often the event feed polls sensors (default 500 ms)
    obd_port        : Serial port for OBD connection (None = simulation mode)
    """

    def __init__(
        self,
        vehicle_id: str = 'BMW-TDV6',
        poll_interval_ms: int = 500,
        obd_port: Optional[str] = None,
        tls_cert_path: Optional[str] = None,
        tls_key_path: Optional[str] = None,
    ):
        self.vehicle_id = vehicle_id
        self._poll_interval_ms = poll_interval_ms

        # OBD / VAGComm adapters
        self.obd = V6OBDReader()
        self.vagcomm = VAGCommIntegration(tls_cert_path=tls_cert_path, tls_key_path=tls_key_path)

        if obd_port:
            self.obd.connect(obd_port)

        # All BMW TDV6 sensor modules
        self.sensors = [
            TurbochargerSensor(),
            BoostPressureSensor(),
            MAFSensor(),
            FuelPressureSensor(),
            OilTemperatureSensor(),
            CoolantTemperatureSensor(),
            DPFSensor(),
            EGRSensor(),
            NOxSensor(),
            GlowPlugSensor(),
            SwirlFlapSensor(),
            InjectorSensor(),
        ]

        # Event infrastructure
        self.bus = EventBus(async_dispatch=True)
        self.feed = EventFeed(self.bus, self.sensors, interval_ms=poll_interval_ms)

        # Reporting
        self._report_gen = ReportGenerator(self.sensors, vehicle_id=vehicle_id)

        # Wire up default console logging for critical/warning events
        self.bus.subscribe(self._log_fault_event, EventType.FAULT_CODE_RAISED)
        self.bus.subscribe(self._log_threshold_event, EventType.THRESHOLD_BREACH)

        logger.info(f'BMWTDV6Engine initialised — vehicle: {vehicle_id}, '
                    f'{len(self.sensors)} sensors, poll interval: {poll_interval_ms} ms')

    # ------------------------------------------------------------------ #
    #  Event handlers                                                      #
    # ------------------------------------------------------------------ #

    def _log_fault_event(self, event: Event):
        if event.severity == Severity.CRITICAL:
            logger.critical(f'[FAULT] {event.source} — {event.data.get("code")} {event.data.get("description")}')
        elif event.severity == Severity.WARNING:
            logger.warning(f'[FAULT] {event.source} — {event.data.get("code")} {event.data.get("description")}')

    def _log_threshold_event(self, event: Event):
        sensor = event.data.get('sensor', event.source)
        value = event.data.get('value')
        unit = event.data.get('unit', '')
        status = event.data.get('status', '')
        if event.severity == Severity.CRITICAL:
            logger.critical(f'[THRESHOLD] {sensor}: {value} {unit} [{status.upper()}]')
        else:
            logger.warning(f'[THRESHOLD] {sensor}: {value} {unit} [{status.upper()}]')

    # ------------------------------------------------------------------ #
    #  Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    def start(self):
        """Start the continuous sensor polling event feed."""
        logger.info('BMW TDV6 diagnostic feed starting')
        self.bus.publish(Event(
            event_type=EventType.ENGINE_START,
            source='engine',
            severity=Severity.INFO,
            data={'vehicle_id': self.vehicle_id},
        ))
        self.feed.start()
        logger.info('BMW TDV6 diagnostic feed running')

    def stop(self):
        """Stop the feed and clean up."""
        logger.info('BMW TDV6 diagnostic feed stopping')
        self.feed.stop()
        self.bus.publish(Event(
            event_type=EventType.ENGINE_STOP,
            source='engine',
            severity=Severity.INFO,
            data={'vehicle_id': self.vehicle_id, 'ticks': self.feed.tick_count},
        ))
        self.bus.stop()
        if self.obd.connected:
            self.obd.disconnect()
        if self.vagcomm.connected:
            self.vagcomm.disconnect()
        logger.info(f'BMW TDV6 diagnostic session ended after {self.feed.tick_count} poll cycles')

    # ------------------------------------------------------------------ #
    #  Reporting                                                           #
    # ------------------------------------------------------------------ #

    def snapshot(self, notes: str = ''):
        """Generate a one-shot diagnostic report from all sensors."""
        return self._report_gen.generate(notes=notes)

    def print_report(self, notes: str = ''):
        """Generate and immediately print a console report."""
        report = self.snapshot(notes=notes)
        console_reporter.render(report)
        return report

    def save_json_report(self, path: str, notes: str = ''):
        """Generate and save a JSON report to `path`."""
        report = self.snapshot(notes=notes)
        json_reporter.write_json(report, path)
        logger.info(f'JSON report saved to {path}')
        return report

    def save_html_report(self, path: str, notes: str = ''):
        """Generate and save an HTML report to `path`."""
        report = self.snapshot(notes=notes)
        html_reporter.write_html(report, path)
        logger.info(f'HTML report saved to {path}')
        return report

    # ------------------------------------------------------------------ #
    #  Context manager support                                             #
    # ------------------------------------------------------------------ #

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.stop()

    # ------------------------------------------------------------------ #
    #  Interactive run loop                                                #
    # ------------------------------------------------------------------ #

    def run_forever(self, report_interval_s: int = 30, output_dir: str = 'reports'):
        """
        Run the diagnostic feed indefinitely, saving periodic reports.
        Exits cleanly on SIGINT (Ctrl-C).
        """
        import time
        from pathlib import Path

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        def _handle_sigint(sig, frame):
            logger.info('Interrupted — stopping diagnostic session')
            self.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, _handle_sigint)

        self.start()
        logger.info(f'Running diagnostic loop — report every {report_interval_s}s, output: {output_dir}/')

        cycle = 0
        try:
            while True:
                time.sleep(report_interval_s)
                cycle += 1
                ts = __import__('datetime').datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                base = output_path / f'{self.vehicle_id}_{ts}'
                report = self.snapshot()
                console_reporter.render(report)
                json_reporter.write_json(report, f'{base}.json')
                html_reporter.write_html(report, f'{base}.html')
                logger.info(f'Cycle {cycle}: report saved to {base}.[json|html]')
        finally:
            self.stop()

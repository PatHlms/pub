# Lima — BMW TDV6 Engine Diagnostics

Real-time OBD/VAG-COM diagnostic system for the BMW TDV6 diesel engine (M57/N57 family).

## Package Structure

```
v6/
├── engine.py                  # BMWTDV6Engine orchestrator — entry point
├── obd/
│   ├── reader.py              # OBD-II PID reader
│   └── vagcomm.py             # VAG-COM/VCDS adapter with TLS
├── sensors/
│   ├── base.py                # BaseSensor, SensorReading, FaultCode
│   ├── turbocharger.py        # VGT boost pressure, vane position
│   ├── boost_pressure.py      # Intake MAP vs. target deviation
│   ├── maf.py                 # Mass air flow + intake air temp
│   ├── fuel_pressure.py       # Common-rail pressure, HP pump health
│   ├── oil_temperature.py     # Oil temp with threshold alerting
│   ├── coolant.py             # Coolant temp, thermostat monitoring
│   ├── dpf.py                 # DPF soot %, backpressure, regen state
│   ├── egr.py                 # EGR flow rate, valve position
│   ├── nox.py                 # NOx ppm (upstream/downstream), lambda
│   ├── glow_plugs.py          # Per-cylinder resistance (6 cylinders)
│   ├── swirl_flaps.py         # Bank 1/2 position, spindle torque
│   └── injectors.py           # Per-cylinder balance rates (piezo)
├── events/
│   ├── types.py               # Event, EventType, Severity dataclasses
│   ├── bus.py                 # Pub/sub EventBus (async threaded)
│   └── feed.py                # EventFeed — continuous sensor polling
├── reporting/
│   ├── report.py              # DiagnosticReport, ReportGenerator
│   ├── console.py             # Formatted text table output
│   ├── json_reporter.py       # JSON / NDJSON serialisation
│   └── html_reporter.py       # Self-contained HTML report
└── logging/
    └── logger.py              # Shared logger
```

## Quick Start

```python
from lima.v6 import BMWTDV6Engine

# One-shot snapshot (simulation mode — no physical OBD port required)
with BMWTDV6Engine(vehicle_id='E60-530d') as engine:
    engine.print_report()
    engine.save_json_report('reports/latest.json')
    engine.save_html_report('reports/latest.html')
```

## Continuous Event Feed

```python
from lima.v6 import BMWTDV6Engine, EventType

engine = BMWTDV6Engine(vehicle_id='E60-530d', poll_interval_ms=500)

# Subscribe to all fault code events
engine.bus.subscribe(
    lambda event: print(f'FAULT: {event.data}'),
    EventType.FAULT_CODE_RAISED
)

# Subscribe to all events
engine.bus.subscribe(lambda event: print(event.to_dict()))

engine.run_forever(report_interval_s=60, output_dir='reports/')
```

## Report Outputs

| Format  | Function                           |
|---------|------------------------------------|
| Console | `engine.print_report()`            |
| JSON    | `engine.save_json_report(path)`    |
| HTML    | `engine.save_html_report(path)`    |
| NDJSON  | `json_reporter.stream_ndjson(report, stream)` |

## BMW TDV6 Sensors

| Sensor          | Key Fault Codes            | Notable Issue                     |
|-----------------|----------------------------|-----------------------------------|
| Turbocharger    | P0299, P0234, P2563        | VGT vane sticking                 |
| Boost Pressure  | P0236, P0106, P0108        | MAP vs. target deviation          |
| MAF             | P0101, P0102, P0103        | Dirty/failed sensor               |
| Fuel Pressure   | P0087, P0088               | CP4 HP pump failure               |
| Oil Temperature | P0196, P0197, P0198        | Thermal management                |
| Coolant Temp    | P0128, P0116, P0118        | Thermostat failure                |
| DPF             | P2002, P2452, P2453, P244A | Soot load, backpressure, ash      |
| EGR             | P0401, P0402, P0404        | Coked/stuck valve                 |
| NOx / Lambda    | P2200, P2201, P0130        | Emissions compliance              |
| Glow Plugs      | P0671–P0676                | Per-cylinder resistance           |
| Swirl Flaps     | P2004–P2007, P1529         | **Spindle failure — engine risk** |
| Injectors       | P1141–P1146                | Piezo balance rates               |

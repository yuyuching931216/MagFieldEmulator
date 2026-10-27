# Magnetic Field Controller

A controller used to read magnetic field data from text files, convert it into DAQ output, and collect analog readings for logging and monitoring with NI-DAQmx.

## Features

- Reads magnetic field data from CSV/text files
- Converts magnetic field values to DAQ output voltages
- Supports real-time control via command interface
- Supports pause/resume behavior
- Supports configurable output interval and analog sampling interval
- Logs DAQ input rows and analog measurements into CSV
- Maintains daily log output via Loguru for timer and runtime status

## Requirements

- Python 3.9+
- NI-DAQmx installed and a compatible DAQ device
- Python packages listed in `requirements.txt`

## Installation

1. Clone the repository

```bash
git clone https://github.com/yuyuching931216/MegFieldEmulator.git
cd MegFieldEmulator
```

2. Install Python dependencies

```bash
pip install -r requirements.txt
```

## Project Structure

```text
MagFieldEmulator/
│── app_config.py             # configuration dataclass
│── app_logger.py             # console + daily log setup
│── app_state.py              # runtime state lock/values
│── command_interface.py      # interactive CLI commands
│── daq_controller.py         # NI-DAQmx control and analog read helpers
│── data_loader.py            # data import logic
│── log_manager.py            # CSV log writer
│── main.py                   # main program entry
│── precise_interval_timer.py # timer with summary logging
│── config.json              # runtime configuration
│── requirements.txt         # Python dependencies
│── data/                    # magnetic field source data
│── logs/                    # runtime and daily log output
└── README.md
```

## Configuration

The program reads its configuration from `config.json`. A default configuration is created automatically on first run if the file is missing. The current runtime configuration fields are:

| Parameter | Description | Default Value |
|-----------|-------------|---------------|
| `csv_input` | Input magnetic field data filename | `"None"` |
| `csv_folder` | Data directory for magnetic field files | `"data"` |
| `csv_log_folder` | Directory for generated CSV logs | `"logs"` |
| `device_name` | DAQ device name | `"Dev1"` |
| `nt_to_volt` | NanoTesla to voltage conversion scale | `1e-05` |
| `daq_output_interval` | DAQ output interval in seconds | `60.0` |
| `analog_interval` | Analog sample aggregation interval in seconds | `60.0` |
| `analog_batch_interval` | DAQ batch read interval in seconds | `1.0` |
| `log_flush_interval` | Number of log entries before flush to CSV | `10` |

Notes:
- `daq_output_interval` is the magnetic-field output update interval.
- `analog_interval` is the interval used to aggregate analog samples before producing one analog measurement.
- `analog_batch_interval` controls how often the program reads all available AI samples from the DAQ buffer.
- Older configuration files containing `interval` are migrated to `daq_output_interval` on startup.

## Usage

1. Prepare a magnetic field file under the configured `csv_folder`
2. Connect the DAQ device and ensure the correct device name is set in `config.json`
3. Run:

```bash
python main.py
```

4. The program initializes the DAQ device, warms up analog input, then starts output and sampling loops.

## Available Commands

The interactive command interface supports the following commands:

- `pause`: pause output
- `resume`: resume output
- `set daq output interval <seconds>`: set DAQ output interval
- `set analog interval <seconds>`: set analog aggregation interval
- `set analog batch interval <seconds>`: set AI batch read interval
- `status`: show current runtime status
- `save config`: save current config to `config.json`
- `jump <row>`: jump to a target row in the loaded data file
- `stop`: stop the program safely
- `help`: show available commands

## Log Output

The program records:

- `daq_output` rows for each output row written to the DAQ buffer
- `analog_measurement` rows for aggregated analog readings
- daily runtime text logs for timer, warnings, and operational state

The CSV log contains fields such as:

- UTC/local timestamps
- `daq_output_interval` for each DAQ output record
- magnetic field values (`bx_nt`, `by_nt`, `bz_nt`)
- DAQ output voltages (`vx`, `vy`, `vz`)
- analog raw and calibrated values (`analog_raw_x/y/z`, `analog_calibrated_x/y/z`)
- success/error status and sample count

The `utc_time` and `local_time` fields use ISO 8601 timestamps with
microseconds. The UTC value includes the `+00:00` offset, and the local value
includes the local timezone offset. `daq_output_interval` records the output
interval used for the corresponding `daq_output` row.

## Important Notes

- `config.json` is the runtime config and may differ from the default dataclass values depending on the current test setup.
- The default values in `AppConfig` are the baseline defaults if the config file is missing or newly generated.
- Timer, skip, and lag summaries are kept in the daily `.log` file to avoid excessive console spam during high-frequency execution.

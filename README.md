# MagFieldEmulator

A real-time magnetic field emulation system that reads magnetic field data from CSV files and outputs corresponding analog voltages through National Instruments DAQ hardware. The system provides precise control over magnetic field simulation with comprehensive logging and interactive command interface.

## Features

- **Real-time Magnetic Field Simulation**: Convert magnetic field data (Bx, By, Bz in nT) to analog voltage outputs
- **DAQ Hardware Integration**: Full support for National Instruments DAQ devices with analog/digital I/O
- **Interactive Command Interface**: Real-time control with pause/resume, interval adjustment, and status monitoring
- **Comprehensive Logging**: Automatic CSV logging with UTC/local timestamps and measurement data
- **Data Format Support**: Multiple CSV input formats with automatic detection
- **Safety Features**: Voltage limiting, graceful shutdown, and error handling
- **Calibration System**: Built-in voltage offset correction and gain adjustment
- **Thread-safe Operations**: Concurrent data processing and user interaction

## System Requirements

### Hardware
- National Instruments DAQ device (tested with Dev1)
- Analog output channels: ao0, ao1, ao2, ao3
- Digital output channels: port0/line8-31
- Analog input channels: ai19, ai20, ai21

### Software
- Python 3.8+
- Windows/Linux compatible
- NI-DAQmx drivers installed

## Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd MagFieldEmulator
   ```

2. **Install Python dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Install NI-DAQmx drivers**
   - Download and install NI-DAQmx from National Instruments website
   - Ensure your DAQ device is properly connected and recognized

4. **Prepare data directory**
   ```bash
   mkdir data
   mkdir logs
   ```

## Usage

### Basic Operation

1. **Start the application**
   ```bash
   python main.py
   ```

2. **Select input data file**
   - The system will display available CSV files in the `data/` directory
   - Enter the file number to select your magnetic field data

3. **Interactive commands**
   Once running, you can use these commands:
   - `pause` - Pause the output
   - `resume` - Resume the output
   - `set interval <seconds>` - Change output interval (e.g., `set interval 30`)
   - `status` - Show current system status
   - `jump <row>` - Jump to specific data row
   - `save config` - Save current configuration
   - `stop` - Stop the system safely
   - `help` - Show all available commands

### Data Format

The system supports CSV files with magnetic field data in the following format:

```
YYYY MM DD HH Bx By Bz
2024 01 15 12 25000.5 -15000.2 45000.8
2024 01 15 12 25001.1 -15001.3 45001.2
...
```

Where:
- First 4 columns: Year, Month, Day, Hour (timestamp)
- Bx, By, Bz: Magnetic field components in nanotesla (nT)

### Configuration

The system uses `config.json` for configuration:

```json
{
  "csv_input": "None",
  "csv_folder": "data",
  "csv_log_folder": "log",
  "device_name": "Dev1",
  "nt_to_volt": 1e-05,
  "interval": 60.0,
  "log_flush_interval": 10
}
```

**Configuration Parameters:**
- `device_name`: DAQ device identifier
- `nt_to_volt`: Conversion factor from nanotesla to volts
- `interval`: Output interval in seconds
- `log_flush_interval`: Number of records before flushing log to disk

## Architecture

### Core Components

- **`main.py`**: Main application controller and command handling
- **`daq_controller.py`**: DAQ hardware interface and voltage output
- **`data_loader.py`**: CSV data loading and parsing
- **`app_config.py`**: Configuration management
- **`app_state.py`**: Thread-safe application state management
- **`log_manager.py`**: Logging system with automatic file management
- **`command_interface.py`**: Interactive command line interface

### Data Flow

1. CSV data is loaded and parsed by `DataLoader`
2. Magnetic field values are converted to voltages with gain/offset correction
3. Voltages are output through DAQ analog channels
4. Analog inputs are read for feedback/monitoring
5. All operations are logged with timestamps

### Safety Features

- **Voltage Limiting**: Automatic ±10V output limiting
- **Graceful Shutdown**: Safe cleanup on exit signals
- **Error Handling**: Comprehensive error catching and reporting
- **Thread Safety**: Protected shared state with locks

## Calibration

The system includes automatic voltage offset correction:

```python
# Voltage calculation with calibration
vx = Bx * nt_to_volt * voltage_gain[0] + voltage_offset[0]
vy = By * nt_to_volt * voltage_gain[1] + voltage_offset[1]
vz = Bz * nt_to_volt * voltage_gain[2] + voltage_offset[2]
```

Calibration data is defined in `testing_data.py` with various field combinations for system characterization.

## Logging

The system automatically generates detailed CSV logs in the `log/` directory:

**Log Format:**
- `index`: Data row index
- `utc_time`: UTC timestamp
- `local_time`: Local timestamp
- `bx_nt`, `by_nt`, `bz_nt`: Magnetic field inputs (nT)
- `vx`, `vy`, `vz`: Output voltages (V)
- `analog_x`, `analog_y`, `analog_z`: Measured analog inputs
- `success`: Operation success flag

## Troubleshooting

### Common Issues

1. **DAQ Device Not Found**
   - Verify device connection and NI-DAQmx installation
   - Check device name in configuration matches actual device

2. **Permission Errors**
   - Run as administrator if accessing hardware
   - Ensure DAQ device is not in use by other applications

3. **Data Loading Errors**
   - Verify CSV format matches expected structure
   - Check file encoding (UTF-8 recommended)

4. **Voltage Output Issues**
   - Verify channel mapping in configuration
   - Check voltage limits and gain settings

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes with appropriate tests
4. Submit a pull request

---

**Note**: This system is designed for scientific/research applications involving magnetic field simulation. Ensure proper safety protocols when working with high-precision measurement equipment.
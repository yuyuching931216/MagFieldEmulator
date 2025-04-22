# Magnetic Field Controller

A versatile controller that reads magnetic field data from text files and outputs corresponding analog voltage signals through a DAQ (Data Acquisition) device. This program supports real-time control, status monitoring, and comprehensive logging.

## Features

- Reads magnetic field data (nT) from text files
- Converts magnetic field values to voltage signals (V)
- Real-time control through a command-line interface
- Pause/resume functionality
- Adjustable output interval and voltage limits
- Detailed status monitoring
- Comprehensive logging

## Requirements

- Python 3.6+
- DAQ device with NI-DAQmx drivers installed

## Installation

1. Clone this repository

```bash
git clone https://github.com/yuyuching931216/MegFieldEmulator.git
cd MegFieldEmulator
```

2. Install dependencies

```bash
pip install -r requirements.txt
```

## Project Structure

```
magnetic_field_controller/
│── app_config.py     # AppConfig class
├── app_state.py      # AppState class
│── log_manager.py    # LogManager class
│── data_loader.py    # DataLoader class
|── daq_controller.py # DAQController class
│── command_interface.py # Command processing
├── main.py               # Main entry point
|── requirements.txt      # Project dependencies
└──data
    └──inputdata.csv    #input megnet data
```

## Configuration

The program uses a `config.json` file for configuration. A default configuration file will be automatically generated on first run, which you can modify as needed.

Configuration parameters:

| Parameter | Description | Default Value |
|-----------|-------------|---------------|
| `csv_input` | Input magnetic field data filename | `"None"` |
| `csv_folder` | Data file directory | `"data"` |
| `csv_log` | Output log file | `"output_log.csv"` |
| `device_name` | DAQ device name | `"Dev1"` |
| `nt_to_volt` | Conversion ratio from nanoTesla to Volts | `0.0001` |
| `interval` | Output interval (seconds) | `60.0` |
| `log_flush_interval` | Log buffer write interval (entries) | `10` |

## Usage

1. Make sure your magnetic field data file is placed in the configured data directory
2. Connect your DAQ device
3. Run the program:

```bash
python main.py
```

4. The program will initialize the DAQ device and start outputting voltage signals according to the data file

## Available Commands

While the program is running, you can use the following commands:

- `pause`: Pause the output
- `resume`: Resume the output
- `set interval <seconds>`: Set the output interval
- `jump <row>`: Jump to the row you want
- `status`: Display current status
- `save config`: Save current settings to config file
- `stop`: Stop the program
- `help`: Display available commands

## Log Output

The program records detailed logs in CSV format including:

- UTC and local timestamps
- Magnetic field values (Bx, By, Bz in nT)
- Output voltage values (Vx, Vy, Vz)
- Success status of voltage output

## Error Handling

The program includes comprehensive error handling for:
- DAQ device connection issues
- Data file loading problems
- Invalid command inputs
- Voltage output failures

## Future Improvements

- Graphical user interface
- Remote control capability
- Real-time visualization of magnetic field data
- Support for additional data formats
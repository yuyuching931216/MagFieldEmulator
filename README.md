# MegFieldEmulator

A real-time magnetic field emulator that uses STK-exported geomagnetic data to drive a 3-axis magnetic simulation platform via NI DAQ + CU1 + Helmholtz coils.

## 🔧 Features

- Load ASCII magnetic field data from STK (nT)
- Real-time voltage output using NI USB-6383 AO
- CLI-based live control: pause, resume, change output interval, limit voltage
- Safe logging of output process
- Tab auto-completion for commands

## 📦 Requirements

- Windows
- NI DAQmx driver installed
- Python 3.8+
- Dependencies:

```bash
pip install pandas nidaqmx
```

## 🚀 Usage

```bash
python real_time_controller.py
```

Then use CLI commands like:

```
pause
resume
set interval 30
set voltage limit 5
status
stop
```

## 📁 File Structure

- `real_time_controller.py`: Main logic
- `600 Meg.txt`: STK magnetic field data input
- `output_log.csv`: Simulation output record

## 📌 License

For internal research use in magnetics and satellite field simulation.

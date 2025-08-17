# Python 32-bit (win-32) Environment — Setup Guide

This document describes how to create and use a **32‑bit Python environment on Windows** with Conda. It assumes you already have Miniconda/Anaconda (64‑bit) installed; that is fine. The key is to pass `--platform win-32` when creating the environment, then install your requirements.

---

## 1) Create the 32‑bit environment

> Works with **conda** (or **mamba** if available). Replace `conda` with `mamba` for faster solves.

```bat
:: Create 32-bit env named py32 with Python 3.8
conda create -n py32 python=3.8 --platform win-32 -y

:: (Optional) if you have mamba
mamba create -n py32 python=3.8 --platform win-32 -y
```

### Verify architecture
```bat
conda run -n py32 python -c "import platform; print(platform.architecture())"
```
Expected output contains: `('32bit', 'WindowsPE')`.

> If it prints `64bit`, your conda may ignore `--platform`. In that case install **Miniconda 32‑bit** and re‑run these steps from that installation.

---

## 2) Install requirements into the 32‑bit env

After the environment exists, install packages directly into it:

```bat
conda install -n py32 -y ^
  numpy pandas matplotlib scipy scikit-learn websocket-client pyserial pyqt pyqtgraph
```

> You can also do it in one line at creation time by appending the list after `python=3.8 --platform win-32`.

### Optional: use pip for extras
```bat
conda run -n py32 pip install --upgrade pip
conda run -n py32 pip install <extra-package-if-needed>
```

---

## 3) (Alternative) Create from `environment.yml`

> `environment.yml` **cannot** force architecture. Use it only if you are already in a 32‑bit conda install **or** your conda respects `--platform` at create time.

`environment.yml`:
```yaml
name: py32
channels:
  - defaults
dependencies:
  - python=3.8
  - numpy
  - pandas
  - matplotlib
  - scipy
  - scikit-learn
  - websocket-client
  - pyserial
  - pyqt
  - pyqtgraph
```

Create the env:
```bat
conda env create -f environment.yml --platform win-32
```

Verify:
```bat
conda run -n py32 python -c "import platform; print(platform.architecture())"
```

---

## 4) Activate and use
```bat
conda activate py32
python -V
```

Register a Jupyter kernel (optional):
```bat
python -m ipykernel install --user --name py32 --display-name "Python (py32)"
```

---

## 5) VS Code setup (optional)
1. Open Command Palette → **Python: Select Interpreter**.
2. Pick the interpreter labeled `py32` (path ends with `envs\py32\python.exe`).
3. Confirm in the terminal: `python -c "import platform; print(platform.architecture())"`.

---

## 6) Troubleshooting
- **`--platform win-32` ignored / still gets 64‑bit**: Install **Miniconda 32‑bit** and rerun. Some conda builds no longer honor cross‑platform env creation.
- **Package not found for 32‑bit**: Some recent wheels/conda pkgs do not ship 32‑bit binaries. Try older versions, e.g., `numpy=1.19`/`1.20`, or install from `pip` if available.
- **PyQt on 32‑bit**: Prefer installing via conda (`pyqt`) to avoid missing Qt DLLs.

---

## 7) One‑shot script (.bat)
Save as `make_py32_env.bat` and run from *Anaconda Prompt*:
```bat
@echo off
setlocal enableextensions enabledelayedexpansion

set ENV_NAME=py32
set PY_VER=3.8

:: Create 32-bit env
conda create -n %ENV_NAME% python=%PY_VER% --platform win-32 -y || goto :err

:: Install deps
conda install -n %ENV_NAME% -y ^
  numpy pandas matplotlib scipy scikit-learn websocket-client pyserial pyqt pyqtgraph || goto :err

:: Verify arch
conda run -n %ENV_NAME% python -c "import platform; print(platform.architecture())" || goto :err

echo.
echo Done. Activate with: conda activate %ENV_NAME%
exit /b 0

:err
echo Failed. If architecture is 64bit, install Miniconda 32-bit and retry.
exit /b 1
```

---

### Summary
- Miniconda **64‑bit** installed is okay.
- **Always** pass `--platform win-32` when creating the env.
- Then install the listed requirements and verify the Python reports **32‑bit**.

@echo off
REM ===== Crear entorno Conda 32 bits para EMG+IMU =====

REM 1. Nombre del entorno
set ENV_NAME=emg32

REM 2. Versión de Python 32 bits (3.8 es estable con la mayoría de librerías)
REM    Nota: En Conda, usar python=3.8 y la opción --platform win-32 fuerza 32 bits
REM    Para Conda >= 4.12 hay que usar CONDA_SUBDIR
set CONDA_SUBDIR=win-32

REM 3. Crear el entorno
echo.
echo === Creando entorno %ENV_NAME% con Python 3.8 de 32 bits ===
conda create -n %ENV_NAME% python=3.8 -y

REM 4. Activar el entorno
echo.
echo === Activando entorno %ENV_NAME% ===
conda activate %ENV_NAME%

REM 5. Instalar librerías necesarias
echo.
echo === Instalando dependencias ===
conda install pandas numpy pyserial -y
pip install websocket-client

REM 6. Mostrar información final
echo.
echo === Entorno %ENV_NAME% listo ===
echo Para usarlo:
echo     conda activate %ENV_NAME%
echo y luego:
echo     python c:\ruta\a\Device.py
pause

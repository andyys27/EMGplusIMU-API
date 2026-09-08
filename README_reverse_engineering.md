# Reconstrucción de drivers GSensor / FREEEMG para Linux

## Por qué esto es un esqueleto y no un driver terminado

`GSensorLinux.py` y `FREEEMGLinux.py` implementan la interfaz `Device`
completa (lifecycle, buffers, `get_emg_df`/`get_imu_df`) y quedan
registrados en `DeviceFactory` como `"gsensor_linux"` / `"freeemg_linux"`,
pero **el framing y los comandos que contienen son placeholders**
(marcados con `# TODO(protocolo)`), tomados prestados del formato del
Unicorn Hybrid Black solo como ejemplo de la *forma* que debe tener el
código. El protocolo real de BTS (sync bytes, comandos de arranque,
layout exacto del payload) está cerrado dentro de `Core.dll`/`BioDAQ.dll`
y no lo tengo — hay que obtenerlo por captura empírica.

Escribir esos valores "a ojo" habría producido un driver que parece
completo pero nunca funcionaría contra el hardware real, así que en vez
de eso te dejo el flujo completo para que tú (con el hardware en mano)
los determines y los pegues en el lugar correcto.

## Flujo de trabajo

### 1. Captura
```bash
# GSensor (Bluetooth SPP)
sudo rfcomm bind 0 XX:XX:XX:XX:XX:XX
python sniff_gsensor.py --port /dev/rfcomm0 --baud 115200

# FREEEMG (FTDI D2XX)
python sniff_freeemg.py --list
python sniff_freeemg.py --device 0
```
Corre esto mientras operas el sensor con el software oficial de BTS
(Windows), o mientras pruebas comandos manuales con `--send`. Detén con
Ctrl+C. Genera un `.bin` (bytes crudos) y un `.log` (hex con timestamp).

Repite varias veces:
- una captura en reposo (sensor quieto),
- una con movimiento conocido en un solo eje (ej. giro de 90° en X),
- una del handshake de arranque completo (desde que conectas hasta que
  empiezan a llegar datos periódicos).

### 2. Análisis de framing
```bash
python protocol_analyzer.py gsensor_capture_YYYYMMDD_HHMMSS.bin
```
Esto sugiere candidatos a sync bytes y longitud de paquete. Una vez
tengas un candidato razonable, confírmalo:
```bash
python protocol_analyzer.py captura.bin --assume-sync "c0 00" --assume-len 45
```
e inspecciona los paquetes alineados en hex.

### 3. Identificar comandos de control
Compara el `.log` de una captura "solo conectar, sin iniciar adquisición"
contra una donde sí mandaste el comando de arranque (o donde el software
oficial lo mandó). Los primeros bytes que se **escriben** justo antes de
que el flujo de datos periódico comience son tu candidato a comando de
arranque (`CMD_START_ACQ` / `CMD_ARM` / etc.).

### 4. Identificar los campos de datos
Con capturas de movimientos conocidos, compara qué bytes cambian de
forma consistente y correlacionable (ej. un valor que sube linealmente
al girar en un eje). Así identificas offsets de accel/gyro/quat, y su
formato (`<h` int16 little-endian, `>i` int32 big-endian, etc. — revisa
varias combinaciones con `struct.unpack`).

### 5. Completar los esqueletos
Reemplaza cada `# TODO(protocolo)` en `_devices/GSensorLinux.py` y
`_devices/FREEEMGLinux.py` con los valores reales que determinaste.
Ajusta `_parse_packet` con los offsets/formatos correctos.

### 6. Probar end-to-end
```python
from DeviceFactory import DeviceFactory
dev = DeviceFactory.create("gsensor_linux", port="/dev/rfcomm0")
dev.connect()
dev.start()
import time; time.sleep(3)
print(dev.get_imu_df())
dev.stop()
dev.disconnect()
```
Una vez validado, es 100% compatible con `LivePlot`, `LivePlotActivity`,
`get_all_data()`, etc. — es un `Device` más.

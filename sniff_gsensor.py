#!/usr/bin/env python3
"""Captura pasiva de bytes crudos desde el puerto serie del GSensor (BT SPP).

Objetivo: registrar TODO lo que llega (y opcionalmente lo que se envía) por
el puerto serie mientras el software oficial de BTS está operando el sensor
en otra máquina/VM Windows conectada al mismo hardware, o mientras pruebas
comandos manuales. NO decodifica nada — solo vuelca bytes con timestamp para
analizarlos después con protocol_analyzer.py.

Uso típico:
    1) Empareja el sensor por Bluetooth y crea el puerto serie:
         bluetoothctl
           > pair XX:XX:XX:XX:XX:XX
           > trust XX:XX:XX:XX:XX:XX
         sudo rfcomm bind 0 XX:XX:XX:XX:XX:XX
       (queda disponible en /dev/rfcomm0)

    2) Corre este script apuntando a ese puerto:
         python sniff_gsensor.py --port /dev/rfcomm0 --baud 115200

    3) En paralelo, opera el sensor con el software oficial (Windows) o,
       si ya sospechas el comando de arranque, pruébalo con --send.

    4) Detén con Ctrl+C. Se genera un archivo .bin (bytes crudos) y un
       archivo .log (bytes + timestamp relativo, en hex, uno por línea)
       listos para protocol_analyzer.py.
"""
from __future__ import annotations

import argparse
import binascii
import datetime
import sys
import time

import serial


def parse_hex_bytes(s: str) -> bytes:
    """Convierte 'C0 00' o '0xC0,0x00' o 'C000' en bytes."""
    s = s.strip()
    s = s.replace("0x", "").replace(",", " ").replace("-", " ")
    parts = s.split()
    if len(parts) == 1 and len(parts[0]) % 2 == 0:
        return bytes.fromhex(parts[0])
    return bytes(int(p, 16) for p in parts)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", required=True, help="Ej: /dev/rfcomm0 o /dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=115200, help="Baudrate (prueba 115200, 57600, 9600 si falla)")
    ap.add_argument("--timeout", type=float, default=1.0, help="Timeout de lectura por chunk (s)")
    ap.add_argument("--send", type=str, default=None,
                     help="Bytes en hex a enviar al abrir el puerto, ej: 'C0 00 61 7C 87' (opcional)")
    ap.add_argument("--send-delay", type=float, default=1.0,
                     help="Segundos a esperar tras enviar --send antes de empezar a leer (default 1.0)")
    ap.add_argument("--send-repeat", type=int, default=1,
                     help="Cuántas veces reenviar --send si no llega respuesta (default 1, sin reintento)")
    ap.add_argument("--out-prefix", type=str, default="gsensor_capture",
                     help="Prefijo de los archivos de salida")
    args = ap.parse_args()

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bin_path = f"{args.out_prefix}_{stamp}.bin"
    log_path = f"{args.out_prefix}_{stamp}.log"

    print(f"[sniff_gsensor] Abriendo {args.port} @ {args.baud} baudios...")
    ser = serial.Serial(args.port, baudrate=args.baud, timeout=args.timeout)

    if args.send:
        payload = parse_hex_bytes(args.send)
        for attempt in range(1, args.send_repeat + 1):
            n = ser.write(payload)
            ser.flush()
            in_waiting_before = ser.in_waiting
            print(f"[sniff_gsensor] Intento {attempt}/{args.send_repeat}: "
                  f"enviado {n}/{len(payload)} bytes = {binascii.hexlify(payload, ' ').decode()}  "
                  f"(bytes ya esperando en buffer: {in_waiting_before})")
            if n != len(payload):
                print("[sniff_gsensor] AVISO: write() no envió todos los bytes solicitados.")
            time.sleep(args.send_delay)
            if ser.in_waiting > 0:
                print(f"[sniff_gsensor] Hubo respuesta tras el envío ({ser.in_waiting} bytes en buffer).")
                break
        else:
            print("[sniff_gsensor] Sin respuesta tras todos los intentos de --send.")

    t0 = time.perf_counter()
    total = 0

    print(f"[sniff_gsensor] Grabando en {bin_path} / {log_path}. Ctrl+C para detener.")
    try:
        with open(bin_path, "wb") as fbin, open(log_path, "w") as flog:
            while True:
                chunk = ser.read(256)
                if not chunk:
                    continue
                t = time.perf_counter() - t0
                fbin.write(chunk)
                fbin.flush()
                hex_str = binascii.hexlify(chunk, " ").decode()
                flog.write(f"{t:10.4f}  len={len(chunk):3d}  {hex_str}\n")
                flog.flush()
                total += len(chunk)
                sys.stdout.write(f"\r[sniff_gsensor] {total} bytes capturados (t={t:.1f}s)")
                sys.stdout.flush()
    except KeyboardInterrupt:
        print(f"\n[sniff_gsensor] Detenido. Total: {total} bytes en {bin_path}")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
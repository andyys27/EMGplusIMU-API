#!/usr/bin/env python3
"""Captura pasiva de bytes crudos desde el dongle USB del FREEEMG.

FREEEMG usa FTD2XX_NET.dll, un wrapper de .NET sobre el driver D2XX
propietario de FTDI (no el modo VCP/puerto-serie estándar). Por eso este
script usa el binding Python del D2XX (`pip install ftd2xx`), que requiere
tener instalada la librería nativa `libftd2xx` de FTDI para Linux
(descarga oficial: https://ftdichip.com/drivers/d2xx-drivers/).

Si al final resulta que el dongle SÍ opera en modo VCP (puerto serie
estándar), usa sniff_gsensor.py apuntando a /dev/ttyUSBx en su lugar — el
framing de captura es idéntico, solo cambia la capa de transporte.

Uso:
    python sniff_freeemg.py --list                  # ver dispositivos FTDI
    python sniff_freeemg.py --device 0               # capturar por índice
    python sniff_freeemg.py --serial FT1234AB        # capturar por número de serie
"""
from __future__ import annotations

import argparse
import binascii
import datetime
import sys
import time

try:
    import ftd2xx as ftd
except ImportError:
    ftd = None


def require_ftd2xx() -> None:
    if ftd is None:
        raise SystemExit(
            "El paquete 'ftd2xx' no está instalado o no encuentra libftd2xx.\n"
            "  pip install ftd2xx\n"
            "  # y coloca libftd2xx.so (descargado de ftdichip.com) donde el\n"
            "  # linker lo encuentre, ej. /usr/local/lib + ldconfig.\n"
            "Si tu dongle en realidad opera como puerto COM/VCP estándar,\n"
            "usa sniff_gsensor.py sobre /dev/ttyUSBx en vez de este script."
        )


def list_devices() -> None:
    require_ftd2xx()
    n = ftd.createDeviceInfoList()
    print(f"[sniff_freeemg] {n} dispositivo(s) FTDI detectados:")
    for i in range(n):
        info = ftd.getDeviceInfoDetail(i)
        print(f"  [{i}] serial={info.get('serial')} desc={info.get('description')}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="Listar dispositivos FTDI y salir")
    ap.add_argument("--device", type=int, default=None, help="Índice del dispositivo (ver --list)")
    ap.add_argument("--serial", type=str, default=None, help="Número de serie del dispositivo")
    ap.add_argument("--baud", type=int, default=115200, help="Baudrate a configurar")
    ap.add_argument("--send", type=str, default=None, help="Bytes en hex a enviar al abrir, ej: '61 7C 87'")
    ap.add_argument("--out-prefix", type=str, default="freeemg_capture")
    args = ap.parse_args()

    if args.list:
        list_devices()
        return

    require_ftd2xx()

    if args.serial:
        dev = ftd.openEx(args.serial.encode())
    elif args.device is not None:
        dev = ftd.open(args.device)
    else:
        raise SystemExit("Especifica --device <idx> o --serial <SN>, o usa --list primero.")

    dev.setBaudRate(args.baud)
    dev.setDataCharacteristics(8, 0, 0)  # 8N1, ajustar si el sniffing sugiere otra cosa
    dev.setTimeouts(1000, 1000)

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bin_path = f"{args.out_prefix}_{stamp}.bin"
    log_path = f"{args.out_prefix}_{stamp}.log"

    if args.send:
        payload = bytes(int(p, 16) for p in args.send.replace("0x", "").split())
        print(f"[sniff_freeemg] Enviando comando de prueba: {binascii.hexlify(payload, ' ')}")
        dev.write(payload)

    t0 = time.perf_counter()
    total = 0
    print(f"[sniff_freeemg] Grabando en {bin_path} / {log_path}. Ctrl+C para detener.")
    try:
        with open(bin_path, "wb") as fbin, open(log_path, "w") as flog:
            while True:
                n_wait = dev.getQueueStatus()
                if n_wait == 0:
                    time.sleep(0.01)
                    continue
                chunk = dev.read(n_wait)
                if not chunk:
                    continue
                t = time.perf_counter() - t0
                fbin.write(chunk)
                fbin.flush()
                hex_str = binascii.hexlify(chunk, " ").decode()
                flog.write(f"{t:10.4f}  len={len(chunk):3d}  {hex_str}\n")
                flog.flush()
                total += len(chunk)
                sys.stdout.write(f"\r[sniff_freeemg] {total} bytes capturados (t={t:.1f}s)")
                sys.stdout.flush()
    except KeyboardInterrupt:
        print(f"\n[sniff_freeemg] Detenido. Total: {total} bytes en {bin_path}")
    finally:
        dev.close()


if __name__ == "__main__":
    main()
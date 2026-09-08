#!/usr/bin/env python3
"""Analiza un archivo .bin capturado con sniff_gsensor.py / sniff_freeemg.py
para ayudar a inferir el framing del protocolo (bytes de sincronización,
longitud de paquete, periodicidad) — el mismo tipo de análisis que hace
falta para reconstruir el formato usado en el ejemplo de Unicorn2LSL
(sync 0xC0 0x00 ... 0x0D 0x0A, tamaño fijo 45 bytes).

Uso:
    python protocol_analyzer.py captura.bin

Qué hace:
  1) Busca la pareja de bytes que se repite con más frecuencia al inicio
     de posiciones espaciadas regularmente -> candidato a "sync bytes".
  2) Si encuentra un candidato, mide la distancia entre ocurrencias
     consecutivas -> candidato a "longitud de paquete".
  3) Imprime un histograma de longitudes entre sync bytes candidatos,
     y vuelca los primeros N paquetes alineados en hex para inspección
     manual (columnas fijas ayudan a ver a ojo qué bytes cambian y
     cuáles son constantes -> ahí suelen estar contador/batería/ejes).

Esto NO reemplaza el análisis manual/comparación con movimientos
conocidos del sensor, pero acelera muchísimo encontrar el framing inicial.
"""
from __future__ import annotations

import argparse
import collections
import sys


def find_sync_candidates(data: bytes, min_count: int = 5, top_n: int = 8):
    """Cuenta pares de bytes consecutivos más frecuentes como candidatos a sync."""
    counts = collections.Counter()
    for i in range(len(data) - 1):
        counts[data[i:i + 2]] += 1
    candidates = [(pair, c) for pair, c in counts.most_common(top_n * 3) if c >= min_count]
    return candidates[:top_n]


def positions_of(data: bytes, needle: bytes):
    pos = []
    start = 0
    while True:
        idx = data.find(needle, start)
        if idx == -1:
            break
        pos.append(idx)
        start = idx + 1
    return pos


def gaps_histogram(positions):
    gaps = [b - a for a, b in zip(positions, positions[1:])]
    return collections.Counter(gaps)


def dump_aligned_packets(data: bytes, sync: bytes, pkt_len: int, n: int = 8):
    positions = positions_of(data, sync)
    print(f"\n--- Primeros {n} paquetes alineados a sync={sync.hex()} , len={pkt_len} ---")
    for p in positions[:n]:
        chunk = data[p:p + pkt_len]
        hex_str = " ".join(f"{b:02x}" for b in chunk)
        print(f"@{p:6d}  {hex_str}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("binfile", help="Archivo .bin generado por los scripts de sniffing")
    ap.add_argument("--min-count", type=int, default=5, help="Mínimo de repeticiones para considerar un candidato")
    ap.add_argument("--assume-sync", type=str, default=None,
                     help="Si ya sospechas los sync bytes en hex, ej. 'c0 00', sáltate la búsqueda automática")
    ap.add_argument("--assume-len", type=int, default=None,
                     help="Si ya sospechas la longitud de paquete, úsala directamente con --assume-sync")
    args = ap.parse_args()

    with open(args.binfile, "rb") as f:
        data = f.read()
    print(f"[protocol_analyzer] {len(data)} bytes cargados de {args.binfile}")

    if args.assume_sync:
        sync = bytes.fromhex(args.assume_sync.replace("0x", "").replace(" ", ""))
        positions = positions_of(data, sync)
        print(f"[protocol_analyzer] Sync {sync.hex()} aparece {len(positions)} veces")
        hist = gaps_histogram(positions)
        print("[protocol_analyzer] Distancias entre ocurrencias consecutivas (candidatos a longitud de paquete):")
        for gap, c in hist.most_common(10):
            print(f"    gap={gap:5d} bytes  -> {c} veces")
        pkt_len = args.assume_len or (hist.most_common(1)[0][0] if hist else 0)
        if pkt_len:
            dump_aligned_packets(data, sync, pkt_len)
        return

    print("\n[protocol_analyzer] Buscando candidatos a 'sync bytes' (pares más frecuentes)...")
    candidates = find_sync_candidates(data, min_count=args.min_count)
    if not candidates:
        print("No se encontraron candidatos claros. Prueba bajar --min-count o revisa la captura.")
        return

    for pair, count in candidates:
        positions = positions_of(data, pair)
        hist = gaps_histogram(positions)
        top_gap = hist.most_common(1)[0] if hist else (None, 0)
        print(f"  sync={pair.hex()}  ocurrencias={count:5d}  gap_mas_comun={top_gap[0]} ({top_gap[1]} veces)")

    best_pair, _ = candidates[0]
    positions = positions_of(data, best_pair)
    hist = gaps_histogram(positions)
    if hist:
        best_len = hist.most_common(1)[0][0]
        print(f"\n[protocol_analyzer] Usando mejor candidato sync={best_pair.hex()} len={best_len}")
        dump_aligned_packets(data, best_pair, best_len)

    print(
        "\nSugerencia: compara varios volcados alineados moviendo el sensor de "
        "formas conocidas (quieto, giro 90° en un eje, etc.) y observa qué "
        "bytes cambian de forma consistente -> ahí están accel/gyro/quat. "
        "Prueba también --assume-sync con distintos candidatos para confirmar."
    )


if __name__ == "__main__":
    main()
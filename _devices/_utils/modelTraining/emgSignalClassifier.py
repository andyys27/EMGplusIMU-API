#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
emg_synthetic_activity_pipeline.py
----------------------------------
Genera un dataset sintético de EMG (actividad=1, reposo=0) con variaciones de amplitud
y entrena una CNN1D binaria. Incluye:
 - Pre-procesamiento (band-pass, notch opcional, z-score por canal)
 - DataLoader con recorte aleatorio de parches entre 0.1 y 1.0 segundos (solo en train)
 - Modelo CNN 1D ligero
 - Métricas ACC, F1, AUROC
 - Guardado de checkpoints y métricas

Uso rápido:
    python emg_synthetic_activity_pipeline.py --epochs 10 --n 3000 --channels 8 --fs 1000

Requisitos:
    python>=3.9, numpy, scipy, scikit-learn, torch, tqdm
"""
import os
import math
import json
import random
import argparse
from typing import Tuple

import numpy as np
from scipy.signal import butter, filtfilt, iirnotch
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score

import torch
from torch import nn
from torch.utils.data import Dataset, DataLoader
from tqdm import tqdm


# ===============================
# Filtros y normalización
# ===============================
def bandpass(signal: np.ndarray, fs: int, low: float = 20.0, high: float = 450.0, order: int = 4) -> np.ndarray:
    """Filtro pasabanda por canal (shape esperada: (..., T) en último eje)."""
    b, a = butter(order, [low/(fs/2), high/(fs/2)], btype='band')
    return filtfilt(b, a, signal, axis=-1)

def notch(signal: np.ndarray, fs: int, f0: float = 50.0, Q: float = 30.0) -> np.ndarray:
    """Filtro notch para 50 Hz (o 60 Hz cambiando f0)."""
    b, a = iirnotch(f0/(fs/2), Q)
    return filtfilt(b, a, signal, axis=-1)

def zscore_per_channel(x: np.ndarray) -> np.ndarray:
    """Estandariza por canal: (x - mu) / sd, con sd estabilizado."""
    mu = x.mean(axis=-1, keepdims=True)
    sd = x.std(axis=-1, keepdims=True) + 1e-8
    return (x - mu) / sd


# ===============================
# Síntesis de dataset EMG
# ===============================
def synth_emg_activity_dataset(
    n: int = 3000,
    C: int = 8,
    fs: int = 1000,
    base_window_s: float = 2.0,
    p_activity: float = 0.5,
    amp_jitter_range: Tuple[float, float] = (0.8, 1.2),
    channel_gain_jitter: float = 0.15,
    baseline_wander_prob: float = 0.3,
    baseline_wander_amp: float = 0.05,
    noise_std_rest: float = 0.05,
    noise_std_activity: float = 0.08,
    seed: int = 0
) -> Tuple[np.ndarray, np.ndarray, int]:
    """
    Genera X (N,C,T), y (N,), fs para un problema binario actividad vs reposo.
    Robustez: variación de amplitud global, jitter por canal, paseos de base (baseline wander),
    y distintas varianzas de ruido para reposo/actividad.
    """
    rng = np.random.RandomState(seed)
    T = int(base_window_s * fs)
    X = np.zeros((n, C, T), dtype=np.float32)
    y = (rng.rand(n) < p_activity).astype(np.int64)

    # Ganancias por canal (constantes por muestra pero aleatorias entre canales)
    # Simula electrodos con distinta impedancia/sensibilidad
    for i in range(n):
        # Ruido base por clase
        std_noise = noise_std_activity if y[i] == 1 else noise_std_rest
        xi = rng.randn(C, T).astype(np.float32) * std_noise

        # Paseo de base opcional (baja frecuencia)
        if rng.rand() < baseline_wander_prob:
            f0 = rng.uniform(0.2, 0.6)  # Hz
            t = np.arange(T) / fs
            wander = baseline_wander_amp * np.sin(2*np.pi*f0*t).astype(np.float32)
            xi += wander[None, :]

        # Bursts de actividad (si y=1)
        if y[i] == 1:
            n_bursts = rng.randint(2, 6)
            for _ in range(n_bursts):
                b_center = rng.randint(T//10, 9*T//10)
                b_len = rng.randint(int(0.02*fs), int(0.15*fs))  # 20–150 ms
                ch = rng.randint(0, C)
                start = max(0, b_center - b_len//2)
                end = min(T, b_center + b_len//2)
                # Pulso ruidoso
                xi[ch, start:end] += rng.randn(end-start).astype(np.float32) * rng.uniform(0.6, 1.0)

        # Jitter de ganancia por canal (multiplicativo, simétrico)
        gains = 1.0 + rng.uniform(-channel_gain_jitter, channel_gain_jitter, size=(C, 1)).astype(np.float32)
        xi *= gains

        # Variación de amplitud global por muestra (para robustez a escala)
        global_scale = rng.uniform(amp_jitter_range[0], amp_jitter_range[1])
        xi *= global_scale

        X[i] = xi

    return X, y, fs


# ===============================
# Dataset con recorte aleatorio
# ===============================
class EMGBinaryRandomCrop(Dataset):
    """
    X: (N,C,T), y: (N,)
    En entrenamiento: recorte aleatorio de longitud U[0.1, 1.0] s.
    En eval: se centra a 1.0 s con recorte o zero-pad.
    """
    def __init__(self, X: np.ndarray, y: np.ndarray, fs: int, train: bool = True,
                 apply_notch: bool = False, notch_freq: float = 50.0):
        assert X.ndim == 3 and y.ndim == 1
        self.fs = fs
        self.train = train
        self.apply_notch = apply_notch
        self.notch_freq = notch_freq

        # Filtro + normalización por ventana
        Xp = []
        for i in range(X.shape[0]):
            xi = bandpass(X[i], fs)
            if self.apply_notch:
                xi = notch(xi, fs, f0=self.notch_freq)
            xi = zscore_per_channel(xi)
            Xp.append(xi.astype(np.float32))
        self.X = np.stack(Xp, axis=0)
        self.y = y.astype(np.int64)

        self.min_len = max(1, int(0.1 * fs))
        self.max_len = int(1.0 * fs)

    def __len__(self):
        return self.X.shape[0]

    def _random_crop(self, xi: np.ndarray) -> np.ndarray:
        C, T = xi.shape
        tgt_len = random.randint(self.min_len, min(self.max_len, T))
        if T == tgt_len:
            start = 0
        else:
            start = random.randint(0, T - tgt_len)
        return xi[:, start:start+tgt_len]

    def _center_crop_or_pad(self, xi: np.ndarray, target_len: int) -> np.ndarray:
        C, T = xi.shape
        if T == target_len:
            return xi
        if T > target_len:
            start = (T - target_len) // 2
            return xi[:, start:start+target_len]
        out = np.zeros((C, target_len), dtype=xi.dtype)
        start = (target_len - T) // 2
        out[:, start:start+T] = xi
        return out

    def __getitem__(self, idx: int):
        xi = self.X[idx]
        yi = self.y[idx]
        if self.train:
            patch = self._random_crop(xi)
        else:
            patch = self._center_crop_or_pad(xi, self.max_len)
        return torch.from_numpy(patch), torch.tensor(yi, dtype=torch.long)


# ===============================
# Modelo CNN 1D ligero
# ===============================
class SmallEMG1DCNN(nn.Module):
    def __init__(self, in_channels: int, n_classes: int = 1):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv1d(in_channels, 32, kernel_size=7, padding=3),
            nn.BatchNorm1d(32), nn.ReLU(), nn.MaxPool1d(2),
            nn.Conv1d(32, 64, kernel_size=5, padding=2),
            nn.BatchNorm1d(64), nn.ReLU(), nn.MaxPool1d(2),
            nn.Conv1d(64, 128, kernel_size=3, padding=1),
            nn.BatchNorm1d(128), nn.ReLU(), nn.AdaptiveAvgPool1d(1),
        )
        self.fc = nn.Linear(128, n_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = self.net(x)         # (B, 128, 1)
        h = h.squeeze(-1)       # (B, 128)
        logit = self.fc(h)      # (B, 1)
        return logit.squeeze(-1)


# ===============================
# Entrenamiento y evaluación
# ===============================
def train_epoch(model, loader, opt, loss_fn, device) -> float:
    model.train()
    losses = []
    for x, y in loader:
        x = x.to(device).float()
        y = y.to(device).float()  # BCEWithLogits
        opt.zero_grad()
        logits = model(x)
        loss = loss_fn(logits, y)
        loss.backward()
        opt.step()
        losses.append(loss.item())
    return float(np.mean(losses)) if len(losses) else 0.0

@torch.no_grad()
def eval_epoch(model, loader, device):
    model.eval()
    all_logits, all_y = [], []
    for x, y in loader:
        x = x.to(device).float()
        logits = model(x)
        all_logits.append(logits.cpu().numpy())
        all_y.append(y.numpy())
    y_true = np.concatenate(all_y) if all_y else np.array([])
    y_prob = 1/(1+np.exp(-np.concatenate(all_logits))) if all_logits else np.array([])
    if y_true.size == 0:
        return {"acc": float("nan"), "f1": float("nan"), "auroc": float("nan")}
    y_pred = (y_prob >= 0.5).astype(int)
    metrics = {
        "acc": accuracy_score(y_true, y_pred),
        "f1": f1_score(y_true, y_pred, zero_division=0),
        "auroc": roc_auc_score(y_true, y_prob) if len(np.unique(y_true))==2 else float("nan")
    }
    return metrics


# ===============================
# Utilidades de split y loaders
# ===============================
def build_loaders_from_arrays(
    X: np.ndarray, y: np.ndarray, fs: int,
    batch_size: int = 64, apply_notch: bool = False,
    notch_freq: float = 50.0, seed: int = 42
):
    rng = np.random.RandomState(seed)
    idx = np.arange(len(y))
    rng.shuffle(idx)
    n = len(idx)
    n_tr = int(0.7*n); n_va = int(0.15*n); n_te = n - n_tr - n_va
    id_tr, id_va, id_te = idx[:n_tr], idx[n_tr:n_tr+n_va], idx[n_tr+n_va:]

    ds_tr = EMGBinaryRandomCrop(X[id_tr], y[id_tr], fs, train=True, apply_notch=apply_notch, notch_freq=notch_freq)
    ds_va = EMGBinaryRandomCrop(X[id_va], y[id_va], fs, train=False, apply_notch=apply_notch, notch_freq=notch_freq)
    ds_te = EMGBinaryRandomCrop(X[id_te], y[id_te], fs, train=False, apply_notch=apply_notch, notch_freq=notch_freq)

    dl_tr = DataLoader(ds_tr, batch_size=batch_size, shuffle=True, num_workers=0, pin_memory=True)
    dl_va = DataLoader(ds_va, batch_size=batch_size, shuffle=False, num_workers=0, pin_memory=True)
    dl_te = DataLoader(ds_te, batch_size=batch_size, shuffle=False, num_workers=0, pin_memory=True)
    return dl_tr, dl_va, dl_te, ds_tr.X.shape[1]  # in_channels


# ===============================
# Main
# ===============================
def main():
    ap = argparse.ArgumentParser(description="Síntesis EMG y entrenamiento binario actividad vs reposo con recorte aleatorio 0.1–1.0 s.")
    # Síntesis
    ap.add_argument("--n", type=int, default=3000, help="Número de ventanas base (muestras).")
    ap.add_argument("--channels", type=int, default=8, help="Número de canales EMG (C).")
    ap.add_argument("--fs", type=int, default=1000, help="Frecuencia de muestreo Hz.")
    ap.add_argument("--win", type=float, default=2.0, help="Duración de ventana base (s).")
    ap.add_argument("--p_activity", type=float, default=0.5, help="Proporción esperada de actividad (1).")
    ap.add_argument("--amp_jitter_min", type=float, default=0.8, help="Escala mínima global por muestra.")
    ap.add_argument("--amp_jitter_max", type=float, default=1.2, help="Escala máxima global por muestra.")
    ap.add_argument("--chan_gain_jitter", type=float, default=0.15, help="Jitter de ganancia por canal (±frac).")
    ap.add_argument("--baseline_prob", type=float, default=0.3, help="Prob. de paseo de base.")
    ap.add_argument("--baseline_amp", type=float, default=0.05, help="Amplitud del paseo de base.")
    ap.add_argument("--noise_rest", type=float, default=0.05, help="STD del ruido en reposo.")
    ap.add_argument("--noise_activity", type=float, default=0.08, help="STD del ruido en actividad.")
    ap.add_argument("--seed", type=int, default=0, help="Semilla de aleatoriedad.")

    # Entrenamiento
    ap.add_argument("--epochs", type=int, default=15)
    ap.add_argument("--batch", type=int, default=128)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--notch", action="store_true", help="Aplicar notch (50 Hz por defecto).")
    ap.add_argument("--notch_freq", type=float, default=50.0)
    ap.add_argument("--pos_weight", type=float, default=0.0, help="Peso para clase positiva en BCE (0=desactivado).")

    args = ap.parse_args()

    # 1) Sintetizar dataset con robustez de amplitud
    X, y, fs = synth_emg_activity_dataset(
        n=args.n, C=args.channels, fs=args.fs, base_window_s=args.win, p_activity=args.p_activity,
        amp_jitter_range=(args.amp_jitter_min, args.amp_jitter_max),
        channel_gain_jitter=args.chan_gain_jitter,
        baseline_wander_prob=args.baseline_prob,
        baseline_wander_amp=args.baseline_amp,
        noise_std_rest=args.noise_rest, noise_std_activity=args.noise_activity,
        seed=args.seed
    )

    # 2) Crear dataloaders con recorte aleatorio (train) y crop/zero-pad a 1 s (val/test)
    dl_tr, dl_va, dl_te, in_channels = build_loaders_from_arrays(
        X, y, fs,
        batch_size=args.batch, apply_notch=args.notch, notch_freq=args.notch_freq, seed=args.seed
    )

    # 3) Modelo + optimizador + pérdida
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SmallEMG1DCNN(in_channels=in_channels).to(device)
    pos_weight = torch.tensor([args.pos_weight], dtype=torch.float32, device=device) if args.pos_weight > 0 else None
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)

    # 4) Entrenar con selección por AUROC en validación
    best = {"auroc": -1.0, "state": None, "epoch": 0}
    for ep in range(1, args.epochs+1):
        tr_loss = train_epoch(model, dl_tr, opt, loss_fn, device)
        va_metrics = eval_epoch(model, dl_va, device)
        print(f"[Epoch {ep:02d}] loss={tr_loss:.4f} | val acc={va_metrics['acc']:.3f} f1={va_metrics['f1']:.3f} auroc={va_metrics['auroc']:.3f}")
        if va_metrics["auroc"] > best["auroc"]:
            best.update(auroc=va_metrics["auroc"], state=model.state_dict(), epoch=ep)

    # 5) Test con mejor estado
    if best["state"] is not None:
        model.load_state_dict(best["state"])
    te_metrics = eval_epoch(model, dl_te, device)
    print(f"[TEST] acc={te_metrics['acc']:.3f} f1={te_metrics['f1']:.3f} auroc={te_metrics['auroc']:.3f} (best epoch={best['epoch']})")

    # 6) Guardar artefactos
    os.makedirs("checkpoints", exist_ok=True)
    torch.save(model.state_dict(), "checkpoints/emg_binary_cnn.pt")
    with open("checkpoints/emg_test_metrics.json", "w") as f:
        json.dump(te_metrics, f, indent=2)

    # 7) Exportar también el dataset sintético para reproducibilidad
    os.makedirs("data_synth", exist_ok=True)
    np.save("data_synth/X.npy", X)
    np.save("data_synth/y.npy", y)
    meta = dict(fs=fs, channels=in_channels, base_window_s=args.win)
    with open("data_synth/meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    print("✔ Listo. Modelo en ./checkpoints/ y datos en ./data_synth/")

if __name__ == "__main__":
    main()

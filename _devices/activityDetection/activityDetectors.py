# activity_detectors.py
"""
Pluggable activity detectors for EMG/IMU streams.

All detectors implement:
    detect(df: pd.DataFrame) -> np.ndarray[int]
and return a 0/1 vector aligned with df.index length.

Detectors:
- FixedThresholdDetector: simple fixed threshold (per-column or scalar), windowed RMS.
- AdaptiveMADDetector: robust adaptive threshold using rolling/EMA median + MAD.
- ModelDetector: wrapper for ML/DL models (sklearn/torch/etc.) with a featurizer.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Optional, Dict, Sequence, Union
import numpy as np
import pandas as pd

# ---------- helpers ----------
def _ensure_2d_numeric(df: pd.DataFrame) -> np.ndarray:
    X = df.select_dtypes(include=[np.number]).to_numpy(dtype=float)
    if X.ndim == 1:
        X = X[:, None]
    return X

def _rolling_rms(X: np.ndarray, win: int) -> np.ndarray:
    # windowed RMS per-sample across channels:
    # 1) per-sample across channels -> mean of squares across columns
    # 2) rolling mean over time, then sqrt
    s2 = (X ** 2).mean(axis=1)  # shape: (T,)
    if win <= 1:
        return np.sqrt(s2)
    s = pd.Series(s2)
    return np.sqrt(s.rolling(win, min_periods=1).mean().to_numpy())

def _contiguous_regions(mask: np.ndarray) -> Sequence[tuple[int, int]]:
    """
    Returns start,end index (inclusive, exclusive) for each contiguous True run.
    """
    if mask.size == 0:
        return []
    m = mask.astype(np.int8)
    diff = np.diff(np.concatenate(([0], m, [0])))
    starts = np.where(diff == 1)[0]
    ends   = np.where(diff == -1)[0]
    return list(zip(starts, ends))

# ---------- base interface ----------
@dataclass
class BaseActivityDetector:
    fs: float                # sampling rate (Hz)
    window_sec: float = 0.25 # seconds

    def detect(self, df: pd.DataFrame) -> np.ndarray:
        raise NotImplementedError

# ---------- fixed threshold ----------
@dataclass
class FixedThresholdDetector(BaseActivityDetector):
    """
    Fixed threshold on windowed RMS. If thresholds is:
      - float -> same threshold for the RMS (after channel-mean)
      - dict  -> per-column threshold (take max across columns to trigger)
    """
    thresholds: Union[float, Dict[str, float]] = 20.0  # tune to your signal units

    def detect(self, df: pd.DataFrame) -> np.ndarray:
        if df is None or df.empty:
            return np.array([], dtype=int)

        X = _ensure_2d_numeric(df)
        win = max(1, int(self.window_sec * self.fs))

        # RMS per column over rolling window, then combine
        # Option 1: compute per-column rolling RMS then OR across columns
        cols = df.select_dtypes(include=[np.number]).columns.tolist()
        act = np.zeros(len(df), dtype=int)

        for j, col in enumerate(cols):
            rms_j = _rolling_rms(X[:, [j]], win)
            thr_j = 15
            act = np.maximum(act, (rms_j > thr_j).astype(int))

        return act

# ---------- adaptive MAD ----------
@dataclass
class AdaptiveMADDetector(BaseActivityDetector):
    """
    Adaptive threshold using median + k * MAD on a rolling window.
    We compute a rolling RMS (over time) and compare to baseline.
    If update_alpha is provided, we apply an EMA to baseline for long-term drift.
    """
    k: float = 5.0                    # multiplier for MAD
    baseline_sec: float = 3.0         # window (s) to estimate baseline initially
    update_alpha: Optional[float] = 0.05  # EMA update rate; None disables EMA
    _median: Optional[float] = None
    _mad: Optional[float] = None

    def detect(self, df: pd.DataFrame) -> np.ndarray:
        if df is None or df.empty:
            return np.array([], dtype=int)

        X = _ensure_2d_numeric(df)
        win = max(1, int(self.window_sec * self.fs))
        rms = _rolling_rms(X, win)  # single RMS curve combining channels

        # initialize baseline if needed using the earliest baseline window
        if self._median is None or self._mad is None:
            base_n = min(len(rms), max(1, int(self.baseline_sec * self.fs)))
            base_slice = rms[:base_n]
            med = float(np.median(base_slice))
            mad = float(np.median(np.abs(base_slice - med)))
            self._median = med
            self._mad = mad if mad > 1e-12 else 1e-12

        # compute threshold
        thr = self._median + self.k * self._mad
        activity = (rms > thr).astype(int)

        # optional EMA update of baseline, robust to outliers by updating only when not active
        if self.update_alpha is not None and len(rms) > 0:
            alpha = float(self.update_alpha)
            not_act = (activity == 0)
            if np.any(not_act):
                r = rms[not_act]
                med_new = float(np.median(r))
                mad_new = float(np.median(np.abs(r - med_new))) or 1e-12
                # EMA
                self._median = (1 - alpha) * self._median + alpha * med_new
                self._mad = (1 - alpha) * self._mad + alpha * mad_new

        return activity

# ---------- model-based detector ----------
@dataclass
class ModelDetector(BaseActivityDetector):
    """
    Generic wrapper for ML/DL models. Provide:
      - model: object with predict_proba(X)->[:,1] or predict(X)->{0,1}
      - featurizer: callable(df_window)->1D or 2D feature array
      - proba_threshold: if using predict_proba
    The detector slides over time using window_sec, generating a per-sample label
    by assigning each sample in the window the predicted label (simple approach).
    """
    model: object = None
    featurizer: Optional[Callable[[pd.DataFrame], np.ndarray]] = None
    proba_threshold: float = 0.5

    def _default_featurizer(self, dfw: pd.DataFrame) -> np.ndarray:
        X = dfw.select_dtypes(include=[np.number])
        if X.empty:
            return np.zeros(6, dtype=float)
        # Simple features per column, then mean across columns:
        rms = np.sqrt((X ** 2).mean(axis=0))
        mav = X.abs().mean(axis=0)
        std = X.std(axis=0)
        feats = np.concatenate([rms.to_numpy(), mav.to_numpy(), std.to_numpy()])
        return feats

    def detect(self, df: pd.DataFrame) -> np.ndarray:
        if df is None or df.empty:
            return np.array([], dtype=int)

        win = max(1, int(self.window_sec * self.fs))
        n = len(df)
        if n < win:
            win = n

        preds = np.zeros(n, dtype=int)
        cols = df.select_dtypes(include=[np.number]).columns
        if len(cols) == 0:
            return preds

        # Slide a window and label that window for simplicity
        for end in range(win, n + 1):
            dfw = df.iloc[end - win:end]
            featurizer = self.featurizer or self._default_featurizer
            f = featurizer(dfw).reshape(1, -1)

            y = None
            if hasattr(self.model, "predict_proba"):
                proba = float(self.model.predict_proba(f)[0, -1])
                y = 1 if proba >= self.proba_threshold else 0
            elif hasattr(self.model, "predict"):
                y = int(self.model.predict(f)[0])
            else:
                raise ValueError("Model must implement predict_proba or predict.")

            # assign the label to the current sample (end-1); you could also fill the whole window
            preds[end - 1] = y

        # backfill early samples with first label
        if n > 0:
            preds[:win - 1] = preds[win - 1]
        return preds

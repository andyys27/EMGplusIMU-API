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
    def __init__(self,fs=500, window_sec=0.03, threshold=0.01):
        super().__init__(fs=fs, window_sec=window_sec)
        self.threshold = threshold

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
            thr_j = self.threshold
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



import onnxruntime as ort

def _ensure_2d_numeric(df: pd.DataFrame) -> np.ndarray:
    X = df.select_dtypes(include=[np.number]).to_numpy(dtype=np.float32)
    if X.ndim == 1:
        X = X[:, None]
    return X

def _bandpass_fir_scipy(x: np.ndarray, fs: float, low=20.0, high=450.0, order=4):
    # Optional: if you used filtering in training, replicate here.
    # For simplicity, no-op by default to avoid SciPy dependency on 32-bit.
    return x

def _zscore_per_channel(x: np.ndarray) -> np.ndarray:
    mu = x.mean(axis=-1, keepdims=True)
    sd = x.std(axis=-1, keepdims=True) + 1e-8
    return (x - mu) / sd

@dataclass
class ModelDetectorONNX(BaseActivityDetector):
    """
    ONNX-based sliding-window detector for EMG.

    Assumes the ONNX model expects input of shape (B, C, T) with float32 and
    outputs either:
      - logits (apply sigmoid), or
      - probabilities in [0,1].

    Parameters
    ----------
    fs : float
        Sampling rate (Hz).
    window_sec : float
        Sliding window length in seconds.
    onnx_path : str
        Path to the exported .onnx model.
    input_name : Optional[str]
        Name of the ONNX input node. If None, the first input name is used.
    output_name : Optional[str]
        Name of the ONNX output node. If None, the first output name is used.
    post_sigmoid : bool
        If True, apply sigmoid to model outputs (logits -> prob).
        If False, assume model already returns probabilities.
    use_filter : bool
        If True, apply a basic band-pass (implement as needed).
    """
    fs: float
    window_sec: float = 1.0
    onnx_path: str = "model.onnx"
    input_name: Optional[str] = None
    output_name: Optional[str] = None
    post_sigmoid: bool = True
    use_filter: bool = False

    def __post_init__(self):
        import os
        base_path = os.path.dirname(os.path.abspath(__file__))
        self.onnx_path = os.path.join(base_path, self.onnx_path)
        self._sess = ort.InferenceSession(self.onnx_path, providers=["CPUExecutionProvider"])
        if self.input_name is None:
            self.input_name = self._sess.get_inputs()[0].name
        if self.output_name is None:
            self.output_name = self._sess.get_outputs()[0].name
        self._win = max(1, int(self.window_sec * self.fs))

    @staticmethod
    def _sigmoid(x: np.ndarray) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-x))

    def _preprocess(self, Xi: np.ndarray) -> np.ndarray:
        """
        Xi: (C, T) float32 EMG window.
        Apply the same preprocessing used at training time.
        """
        x = Xi
        if self.use_filter:
            x = _bandpass_fir_scipy(x, self.fs)
        x = _zscore_per_channel(x)
        return x.astype(np.float32, copy=False)

    def _run_model(self, Xi: np.ndarray) -> float:
        """
        Xi: (C, T) preprocessed
        Returns prob(actividad) in [0,1]
        """
        x_in = Xi[None, ...]  # (1, C, T)
        out = self._sess.run([self.output_name], {self.input_name: x_in})[0]
        # out shape could be (1,) or (1,1) — squeeze to scalar
        y = float(np.array(out).squeeze())
        return float(self._sigmoid(y) if self.post_sigmoid else y)

    def detect(self, df: pd.DataFrame) -> np.ndarray:
        """
        Slide over df with step=1 sample.
        For each window, run ONNX and assign label to the window end sample.
        Returns a vector of 0/1 with len(df).
        """
        if df is None or df.empty:
            return np.array([], dtype=int)

        X = _ensure_2d_numeric(df)         # (T, C)
        X = X.T                             # -> (C, T)
        C, T = X.shape
        win = min(self._win, T)

        preds = np.zeros(T, dtype=int)
        if T < win:
            # use the whole sequence once
            prob = self._run_model(self._preprocess(X[:, :T]))
            preds[:] = 1 if prob >= 0.5 else 0
            return preds

        # main sliding loop
        for end in range(win, T + 1):
            Xi = X[:, end - win:end]               # (C, win)
            Xi = self._preprocess(Xi)
            prob = self._run_model(Xi)
            preds[end - 1] = 1 if prob >= 0.5 else 0

        # backfill the initial (win-1) samples
        preds[:win - 1] = preds[win - 1]
        return preds
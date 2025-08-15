# activity_train_test.py
# Train & test a binary activity detector on a 1-D labeled signal.
# x: list/np.array of samples, y: list/np.array of {0,1}

from __future__ import annotations
import numpy as np
from typing import Tuple, Optional, Dict
from dataclasses import dataclass

from sklearn.model_selection import train_test_split, StratifiedKFold, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score, precision_recall_fscore_support,
    roc_auc_score, confusion_matrix, classification_report
)
# You can swap LogisticRegression for RandomForest/SVM if you prefer.

# -------------------------- feature engineering --------------------------

def _zero_crossings(x: np.ndarray, thr: float = 0.0) -> int:
    """Count sign changes around threshold thr."""
    s = np.sign(x - thr)
    return int(np.sum(np.abs(np.diff(s)) > 0))

def _slope_sign_changes(x: np.ndarray) -> int:
    """Count slope sign changes."""
    dx1 = np.diff(x)
    return int(np.sum((dx1[:-1] * dx1[1:]) < 0))

def _waveform_length(x: np.ndarray) -> float:
    """Sum of absolute successive differences."""
    return float(np.sum(np.abs(np.diff(x))))

def window_features(x: np.ndarray) -> np.ndarray:
    """
    Compute a compact feature vector for one window.
    Features: mean, std, RMS, MAV, WL, ZC, SSC.
    """
    x = np.asarray(x, dtype=float)
    if x.size == 0:
        return np.zeros(7, dtype=float)
    mean = np.mean(x)
    std  = np.std(x)
    rms  = np.sqrt(np.mean(x**2))
    mav  = np.mean(np.abs(x))
    wl   = _waveform_length(x)
    zc   = _zero_crossings(x, thr=np.median(x))
    ssc  = _slope_sign_changes(x)
    return np.array([mean, std, rms, mav, wl, zc, ssc], dtype=float)

def make_windows(
    x: np.ndarray,
    y: np.ndarray,
    fs: float,
    win_sec: float = 0.200,
    step_sec: float = 0.050,
    label_mode: str = "any",   # "any" | "majority" | "ratio"
    pos_ratio: float = 0.5
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Slice (x,y) into overlapping windows and build feature matrix Xw and labels Yw.

    label_mode:
      - "any": 1 if ANY sample in the window is 1 (sensitive)
      - "majority": 1 if more than half are 1
      - "ratio": 1 if mean(y_window) >= pos_ratio
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=int)
    assert x.shape == y.shape, "x and y must be same length"

    w = max(1, int(round(win_sec * fs)))
    s = max(1, int(round(step_sec * fs)))
    if len(x) < w:
        # Single window fallback
        Xw = window_features(x)[None, :]
        yw = np.array([1 if (y.mean() >= (pos_ratio if label_mode == "ratio" else 0.5)) else 0], dtype=int)
        return Xw, yw

    feats = []
    labs  = []
    for start in range(0, len(x) - w + 1, s):
        end = start + w
        xw = x[start:end]
        yw = y[start:end]
        feats.append(window_features(xw))
        if label_mode == "any":
            labs.append(1 if np.any(yw == 1) else 0)
        elif label_mode == "majority":
            labs.append(1 if (np.mean(yw) > 0.5) else 0)
        elif label_mode == "ratio":
            labs.append(1 if (np.mean(yw) >= pos_ratio) else 0)
        else:
            raise ValueError("label_mode must be 'any' | 'majority' | 'ratio'")

    return np.vstack(feats), np.asarray(labs, dtype=int)

# ------------------------------- training -------------------------------

@dataclass
class TrainResult:
    pipeline: Pipeline
    metrics: Dict[str, float]
    report: str
    conf_mat: np.ndarray
    cv_auc_mean: Optional[float] = None
    cv_auc_std: Optional[float] = None

def train_activity_detector(
    x: np.ndarray,
    y: np.ndarray,
    fs: float,
    win_sec: float = 0.200,
    step_sec: float = 0.050,
    label_mode: str = "any",
    pos_ratio: float = 0.5,
    test_size: float = 0.2,
    random_state: int = 42,
    do_cv: bool = True
) -> TrainResult:
    """
    Window the series, extract features, train a classifier (LogReg by default),
    and return metrics + trained pipeline (scaler + model).
    """
    Xw, Yw = make_windows(x, y, fs, win_sec, step_sec, label_mode, pos_ratio)

    # Split (stratified)
    Xtr, Xte, ytr, yte = train_test_split(
        Xw, Yw, test_size=test_size, random_state=random_state, stratify=Yw
    )

    # Model: StandardScaler + LogisticRegression (balanced classes)
    pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(class_weight="balanced", max_iter=200, random_state=random_state)),
    ])
    pipe.fit(Xtr, ytr)

    # Evaluation
    ypred = pipe.predict(Xte)
    try:
        yproba = pipe.predict_proba(Xte)[:, 1]
        auc = roc_auc_score(yte, yproba)
    except Exception:
        yproba = None
        auc = np.nan

    acc = accuracy_score(yte, ypred)
    prec, rec, f1, _ = precision_recall_fscore_support(yte, ypred, average="binary", zero_division=0)
    cm = confusion_matrix(yte, ypred)
    rep = classification_report(yte, ypred, digits=3)

    cv_mean = cv_std = None
    if do_cv:
        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=random_state)
        try:
            cv_scores = cross_val_score(pipe, Xw, Yw, cv=cv, scoring="roc_auc")
            cv_mean, cv_std = float(cv_scores.mean()), float(cv_scores.std())
        except Exception:
            cv_mean = cv_std = None

    metrics = {
        "accuracy": float(acc),
        "precision": float(prec),
        "recall": float(rec),
        "f1": float(f1),
        "auc": float(auc) if not np.isnan(auc) else None,
    }

    return TrainResult(
        pipeline=pipe,
        metrics=metrics,
        report=rep,
        conf_mat=cm,
        cv_auc_mean=cv_mean,
        cv_auc_std=cv_std
    )

# ------------------------------ inference ------------------------------

def infer_activity_vector(
    x: np.ndarray,
    fs: float,
    pipeline: Pipeline,
    win_sec: float = 0.200,
    step_sec: float = 0.050,
    threshold: float = 0.5
) -> np.ndarray:
    """
    Produce a per-sample 0/1 vector from raw x using the trained pipeline.
    Strategy: label each window, then expand labels to cover the window span.
    """
    # Dummy labels just to window (not used)
    y_dummy = np.zeros_like(x, dtype=int)
    Xw, _ = make_windows(x, y_dummy, fs, win_sec, step_sec, label_mode="any")

    # Predict probas/labels per window
    if hasattr(pipeline, "predict_proba"):
        pw = pipeline.predict_proba(Xw)[:, 1]
        lw = (pw >= threshold).astype(int)
    else:
        lw = pipeline.predict(Xw).astype(int)

    # Expand window labels back to sample domain
    w = max(1, int(round(win_sec * fs)))
    s = max(1, int(round(step_sec * fs)))
    out = np.zeros(len(x), dtype=int)
    idx = 0
    for start in range(0, len(x) - w + 1, s):
        end = start + w
        out[start:end] = np.maximum(out[start:end], lw[idx])
        idx += 1
    # If tail remains (when len(x) < w handled above)
    if idx == 0 and len(x) > 0:
        out[:] = lw[0] if lw.size else 0
    return out

# ------------------------------ quick demo ------------------------------
if __name__ == "__main__":
    # Synthetic example
    fs = 1000.0
    t = np.arange(0, 10, 1/fs)                 # 10 seconds
    x = 10*np.random.randn(t.size)             # baseline noise
    # Inject activity bursts
    x[2000:2300] += 80*np.sin(2*np.pi*50*t[2000:2300])
    x[6000:6500] += 60*np.sin(2*np.pi*70*t[6000:6500])

    # Build labels y (1 inside bursts)
    y = np.zeros_like(x, dtype=int)
    y[2000:2300] = 1
    y[6000:6500] = 1

    res = train_activity_detector(
        x, y, fs,
        win_sec=0.200, step_sec=0.050,
        label_mode="any", test_size=0.2, do_cv=True
    )
    print("Metrics:", res.metrics)
    print("Confusion matrix:\n", res.conf_mat)
    print(res.report)

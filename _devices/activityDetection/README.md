# Activity Detection

Algorithms for detecting muscle activity from EMG or IMU data.

## Detectors
- `FixedThresholdDetector` – RMS-based detector with a fixed threshold.
- `AdaptiveMADDetector` – adaptive threshold using median and MAD.
- `ModelDetector` – wraps machine learning models with a custom featurizer.

See `activityDetectors.py` for implementation details and `activity_train.py`
for an example training pipeline.

"""Utility for displaying live plots using PyQt5 and pyqtgraph."""

import sys
from typing import Callable, Dict, List, Optional
import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt5 import QtWidgets, QtCore


class LivePlot:
    """
    Multi-subplot live plotter (PyQt5 + pyqtgraph) with DYNAMIC columns.
    Each subplot receives a get_df() -> pd.DataFrame with a DatetimeIndex.
    All numeric columns present at each refresh are plotted automatically.

    Usage:
        plotter = LivePlot(
            plots=[
                {"get_df": lambda: dev.get_emg_df(), "title": "EMG"},
                {"get_df": lambda: dev.get_imu_df(), "title": "IMU Acceleration"},
            ],
            window_sec=60,
            refresh_hz=30,
            title="EMG + IMU Live",
        )
        plotter.start()
    """

    def __init__(
        self,
        plots: List[Dict],
        window_sec: float = 5.0,
        refresh_hz: float = 30.0,
        title: str = "Live Data",
    ):
        self.plots_cfg = plots
        self.window_sec = float(window_sec)
        self.refresh_ms = int(1000.0 / float(refresh_hz))
        self.title = title

        self._app_created = False
        self.app: Optional[QtWidgets.QApplication] = None
        self.win: Optional[pg.GraphicsLayoutWidget] = None
        self.timer: Optional[QtCore.QTimer] = None

        # For each subplot: {"plot": PlotItem, "curves": {col: PlotDataItem}, "color_idx": int}
        self._subplots: List[Dict[str, object]] = []

        self._ensure_app()
        self._build_ui()

    # ---------- Qt lifecycle ----------
    def _ensure_app(self):
        self.app = QtWidgets.QApplication.instance()
        if self.app is None:
            self.app = QtWidgets.QApplication(sys.argv)
            self._app_created = True

    def _build_ui(self):
        self.win = pg.GraphicsLayoutWidget(show=True, title=self.title)
        self.win.resize(1000, 700)
        self.win.ci.setSpacing(10)

        for i, cfg in enumerate(self.plots_cfg):
            title = cfg.get("title", f"Plot {i+1}")
            p = self.win.addPlot(title=title)
            p.showGrid(x=True, y=True)
            p.addLegend()
            self._subplots.append({"plot": p, "curves": {}, "color_idx": 0})
            self.win.nextRow()

        # Clean close
        def _on_close(evt):
            try:
                if self.timer:
                    self.timer.stop()
            except Exception:
                pass
            evt.accept()

        self.win.closeEvent = _on_close

        # QTimer without widget parent (robusto en PyQt5 también)
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self._update_once)
        self.timer.start(self.refresh_ms)

    # ---------- helpers ----------
    @staticmethod
    def _coerce_datetime_index(df: pd.DataFrame) -> Optional[pd.DataFrame]:
        if isinstance(df.index, pd.DatetimeIndex):
            return df
        if "Timestamp" in df.columns:
            idx = pd.to_datetime(df["Timestamp"], errors="coerce")
            df = df.drop(columns=["Timestamp"], errors="ignore")
            df.index = idx
            return df if isinstance(df.index, pd.DatetimeIndex) else None
        return None

    def _next_pen(self, subplot_idx: int):
        color_idx = self._subplots[subplot_idx]["color_idx"]  # type: ignore
        pen = pg.mkPen(pg.intColor(color_idx, hues=16), width=2)
        self._subplots[subplot_idx]["color_idx"] = color_idx + 1  # type: ignore
        return pen

    def _ensure_curve(self, subplot_idx: int, col: str):
        curves: Dict[str, pg.PlotDataItem] = self._subplots[subplot_idx]["curves"]  # type: ignore
        if col not in curves:
            plot_item: pg.PlotItem = self._subplots[subplot_idx]["plot"]  # type: ignore
            curves[col] = plot_item.plot(name=col, pen=self._next_pen(subplot_idx))

    # ---------- update ----------
    def _update_once(self):
        for i, cfg in enumerate(self.plots_cfg):
            get_df: Callable[[], Optional[pd.DataFrame]] = cfg["get_df"]
            df = get_df()
            if df is None or df.empty:
                continue

            df = self._coerce_datetime_index(df)
            if df is None or df.empty:
                continue

            df = df.sort_index()
            tmax = df.index.max()
            df = df[df.index >= tmax - pd.Timedelta(seconds=self.window_sec)]
            if df.empty:
                continue

            # Convert potential object dtypes to numeric where possible
            #df = df.infer_objects(copy=False)
            df_num = df.select_dtypes(include=[np.number])
            if df_num.empty:
                continue

            x = (df_num.index - df_num.index[0]).total_seconds().to_numpy()

            # Ensure curves for all current numeric columns; drop vanished ones
            existing = set(self._subplots[i]["curves"].keys())  # type: ignore
            current = set(df_num.columns)

            # Add new columns
            for col in sorted(current - existing):
                self._ensure_curve(i, col)

            # Remove columns no longer present
            for col in sorted(existing - current):
                item = self._subplots[i]["curves"].pop(col, None)  # type: ignore
                if item:
                    try:
                        plot_item: pg.PlotItem = self._subplots[i]["plot"]  # type: ignore
                        plot_item.removeItem(item)
                    except Exception:
                        pass

            # Update data
            for col, curve in self._subplots[i]["curves"].items():  # type: ignore
                if col not in df_num.columns:
                    continue
                y = df_num[col].to_numpy(dtype=float)
                curve.setData(x, y)

    # ---------- public API ----------
    def start(self):
        self.win.show()
        if self._app_created:
            self.app.exec_()

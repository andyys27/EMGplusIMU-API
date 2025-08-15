# live_plot_activity.py
"""
LivePlotActivity: live plotting with activity overlays.
- Accepts any detector from activity_detectors (or your own with the same interface).
- Overlays: "band" (highlight active segments) or "line" (show a horizontal line when active).
"""

from __future__ import annotations
from typing import Callable, Dict, List, Optional
import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt5 import QtCore

from typing import Sequence, Union

class LivePlotActivity:
    def __init__(
        self,
        plots: List[Dict],
        window_sec: float = 5.0,
        refresh_hz: float = 30.0,
        title: str = "Live Data + Activity",
    ):
        """
        Each plot config dict supports:
          {
            "get_df": Callable[[], pd.DataFrame],
            "title": "EMG",
            "detector": <BaseActivityDetector instance> or None,
            "overlay": "band" | "line",
            "band_alpha": 60,            # transparency for band
            "band_color": (255, 100, 0), # RGB
            "band_min_len": 3,           # minimum samples to draw a band
            "line_y": 0.0,               # y-level for line overlay
          }
        """
        self.plots_cfg = plots
        self.window_sec = float(window_sec)
        self.refresh_ms = max(1, int(1000.0 / float(refresh_hz)))
        self.title = title

        self.app = pg.mkQApp(self.title)
        self.win: Optional[pg.GraphicsLayoutWidget] = None
        self.timer: Optional[QtCore.QTimer] = None

        # Per subplot state
        self._subplots: List[Dict[str, object]] = []
        self._build_ui()
    @staticmethod
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
    def _build_ui(self):
        self.win = pg.GraphicsLayoutWidget(show=True, title=self.title)
        self.win.resize(1100, 750)
        self.win.ci.setSpacing(10)

        for i, cfg in enumerate(self.plots_cfg):
            title = cfg.get("title", f"Plot {i+1}")
            p = self.win.addPlot(title=title)
            p.showGrid(x=True, y=True)
            p.addLegend()
            p.enableAutoRange(x=True, y=True)
            self._subplots.append({
                "plot": p,
                "curves": {},
                "color_idx": 0,
                "bands": [],     # active pg.LinearRegionItem
                "line": None,    # pg.InfiniteLine
                "overlay": cfg.get("overlay", "band"),
                "detector": cfg.get("detector", None),  # BaseActivityDetector or None
                "band_alpha": int(cfg.get("band_alpha", 60)),
                "band_color": tuple(cfg.get("band_color", (255, 100, 0))),
                "band_min_len": int(cfg.get("band_min_len", 3)),
                "line_y": float(cfg.get("line_y", 0.0)),
            })
            self.win.nextRow()

        def _on_close(evt):
            try:
                if self.timer:
                    self.timer.stop()
            except Exception:
                pass
            evt.accept()

        self.win.closeEvent = _on_close
        self.timer = QtCore.QTimer(self.win)
        self.timer.timeout.connect(self._update_once)
        self.timer.start(self.refresh_ms)

    def _next_pen(self, subplot_idx: int):
        color_idx = self._subplots[subplot_idx]["color_idx"]  # type: ignore
        pen = pg.mkPen(pg.intColor(color_idx, hues=16), width=2)
        self._subplots[subplot_idx]["color_idx"] = color_idx + 1  # type: ignore
        return pen

    @staticmethod
    def _coerce_datetime_index(df: pd.DataFrame) -> Optional[pd.DataFrame]:
        if isinstance(df.index, pd.DatetimeIndex):
            return df
        if "Timestamp" in df.columns:
            df = df.copy()
            df.index = pd.to_datetime(df["Timestamp"], errors="coerce")
            df.drop(columns=["Timestamp"], inplace=True, errors="ignore")
            return df if isinstance(df.index, pd.DatetimeIndex) else None
        # accept numeric seconds as index
        if np.issubdtype(df.index.dtype, np.number):
            base = pd.Timestamp.utcnow()
            df = df.copy()
            df.index = base + pd.to_timedelta(df.index, unit="s")
            return df
        return None

    def _ensure_curve(self, subplot_idx: int, col: str):
        curves: Dict[str, pg.PlotDataItem] = self._subplots[subplot_idx]["curves"]  # type: ignore
        if col not in curves:
            plot_item: pg.PlotItem = self._subplots[subplot_idx]["plot"]  # type: ignore
            curves[col] = plot_item.plot(name=col, pen=self._next_pen(subplot_idx))

    def _clear_bands(self, i: int):
        sp = self._subplots[i]
        plot_item: pg.PlotItem = sp["plot"]  # type: ignore
        for band in sp["bands"]:  # type: ignore
            try:
                plot_item.removeItem(band)
            except Exception:
                pass
        sp["bands"] = []

    def _set_line_visible(self, i: int, visible: bool, y: float):
        sp = self._subplots[i]
        plot_item: pg.PlotItem = sp["plot"]  # type: ignore
        ln = sp["line"]
        if ln is None:
            ln = pg.InfiniteLine(pos=y, angle=0, pen=pg.mkPen((255, 0, 0, 150), width=2))
            plot_item.addItem(ln)
            sp["line"] = ln
        ln.setPos(y)
        ln.setVisible(visible)

    def _update_once(self):
        for i, cfg in enumerate(self.plots_cfg):
            get_df: Callable[[], Optional[pd.DataFrame]] = cfg["get_df"]
            df = get_df()
            if df is None or df.empty:
                self._clear_bands(i)
                self._set_line_visible(i, False, self._subplots[i]["line_y"])  # type: ignore
                continue

            df = self._coerce_datetime_index(df)
            if df is None or df.empty:
                self._clear_bands(i)
                self._set_line_visible(i, False, self._subplots[i]["line_y"])  # type: ignore
                continue

            df = df.sort_index()
            tmax = df.index.max()
            df = df[df.index >= tmax - pd.Timedelta(seconds=self.window_sec)]
            if df.empty:
                self._clear_bands(i)
                self._set_line_visible(i, False, self._subplots[i]["line_y"])  # type: ignore
                continue

            df_num = df.select_dtypes(include=[np.number])
            if df_num.empty:
                self._clear_bands(i)
                self._set_line_visible(i, False, self._subplots[i]["line_y"])  # type: ignore
                continue

            # x (seconds from start of the slice)
            x = (df_num.index - df_num.index[0]).total_seconds().to_numpy()

            # update curves
            existing = set(self._subplots[i]["curves"].keys())  # type: ignore
            current = set(df_num.columns)
            for col in sorted(current - existing):
                self._ensure_curve(i, col)
            for col in sorted(existing - current):
                item = self._subplots[i]["curves"].pop(col, None)  # type: ignore
                if item:
                    try:
                        plot_item: pg.PlotItem = self._subplots[i]["plot"]  # type: ignore
                        plot_item.removeItem(item)
                    except Exception:
                        pass
            for col, curve in self._subplots[i]["curves"].items():  # type: ignore
                if col not in df_num.columns:
                    continue
                curve.setData(x, df_num[col].to_numpy(dtype=float))

            # overlays via detector
            detector: Optional[BaseActivityDetector] = self._subplots[i]["detector"]  # type: ignore
            overlay = self._subplots[i]["overlay"]  # type: ignore
            if detector is None:
                self._clear_bands(i)
                self._set_line_visible(i, False, self._subplots[i]["line_y"])  # type: ignore
                continue

            # run detector on the numeric slice (aligned with x)

            act = detector.detect(df_num)

            if act.size != len(df_num):
                # align length if needed
                if act.size == 0:
                    self._clear_bands(i)
                    self._set_line_visible(i, False, self._subplots[i]["line_y"])  # type: ignore
                    continue
                n = min(len(df_num), act.size)
                act = act[-n:]
                x = x[-n:]

            # draw overlays
            if overlay == "band":
                self._clear_bands(i)
                band_color = self._subplots[i]["band_color"]  # type: ignore
                alpha = int(self._subplots[i]["band_alpha"])  # type: ignore
                min_len = int(self._subplots[i]["band_min_len"])  # type: ignore

                plot_item: pg.PlotItem = self._subplots[i]["plot"]  # type: ignore
                for s, e in self._contiguous_regions(act.astype(bool)):
                    if (e - s) < min_len:
                        continue
                    region = pg.LinearRegionItem(
                        values=(x[s], x[e - 1]),
                        brush=pg.mkBrush(*band_color, alpha),
                        movable=False,
                    )
                    region.setZValue(-10)
                    plot_item.addItem(region)
                    self._subplots[i]["bands"].append(region)  # type: ignore
                # hide line when using band
                self._set_line_visible(i, False, self._subplots[i]["line_y"])  # type: ignore

            elif overlay == "line":
                is_active_now = bool(act[-1] == 1)
                self._clear_bands(i)
                self._set_line_visible(i, is_active_now, float(self._subplots[i]["line_y"]))  # type: ignore

            # keep autorange responsive
            plot_item: pg.PlotItem = self._subplots[i]["plot"]  # type: ignore
            plot_item.enableAutoRange(x=True, y=True)

    def start(self):
        self.win.show()

        from PyQt5 import QtWidgets  # o PySide
        import sys

        app = QtWidgets.QApplication.instance()
        if app is None:  # si no existe, créala
            app = QtWidgets.QApplication(sys.argv)

        sys.exit(app.exec_())  # si es PyQt5 o PySide2

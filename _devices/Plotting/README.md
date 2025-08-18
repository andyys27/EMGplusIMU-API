# Plotting Utilities

Interactive visualization tools built with PyQt5 and pyqtgraph.

## Modules
- `LivePlot.py` – multi-subplot live data viewer for arbitrary streams.
- `LivePlotActivity.py` – extension of `LivePlot` with activity overlays and
  optional activity detectors.

These utilities expect callables returning `pandas.DataFrame` objects with a
`DatetimeIndex` and numeric columns to plot.

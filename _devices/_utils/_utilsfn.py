import serial.tools.list_ports as portList
import pandas as pd


def list_serial_devices():
    """List serial ports similarly to the GUI's scan button."""
    ports = list(portList.comports())
    devices = []
    for p in ports:
        print(p.device, p.name, p.description)
        devices.append(
            {
                "device": p.device,
                "name": p.name,
                "description": p.description,
                "manufacturer": getattr(p, "manufacturer", None),
                "vid": getattr(p, "vid", None),
                "pid": getattr(p, "pid", None),
                "serial_number": getattr(p, "serial_number", None),
            }
        )
    return devices


def exportCSV(df: pd.DataFrame, name: str):
    """Export the DataFrame to two CSV files, with and without timestamps."""
    if isinstance(df.index, pd.DatetimeIndex):
        df_with_ts = df.copy()
        df_with_ts.to_csv(f"{name}_with_timestamp.csv", index_label="Timestamp")
    else:
        df.to_csv(f"{name}_with_timestamp.csv", index=False)

    if "Timestamp" in df.columns:
        df_no_ts = df.drop(columns=["Timestamp"])
    elif isinstance(df.index, pd.DatetimeIndex):
        df_no_ts = df.reset_index(drop=True)
    else:
        df_no_ts = df.copy()
    df_no_ts.to_csv(f"{name}_no_timestamp.csv", index=False)


if __name__ == "__main__":
    print("Available serial devices:")
    for device in list_serial_devices():
        print(f" - {device['name']} ({device['device']})")

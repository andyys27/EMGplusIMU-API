    
import serial.tools.list_ports as portList

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

if __name__ == "__main__":
    print("Available serial devices:")
    for device in list_serial_devices():
        print(f" - {device['name']} ({device['device']})")
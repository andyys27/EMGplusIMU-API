import asyncio
from bleak import BleakClient, BleakScanner

async def main():
    print("1. Escaneando red BLE buscando 'BAIOBIT'...")
    
    # Buscar dispositivos en rango
    devices = await BleakScanner.discover(timeout=7.0)
    sensor_device = None

    for d in devices:
        if d.name and "BAIOBIT" in d.name.upper():
            sensor_device = d
            break

    if not sensor_device:
        print("❌ No se encontró el sensor. Revisa que esté encendido y sin conectar al teléfono.")
        return

    print(f"✅ ¡Sensor encontrado! Nombre: {sensor_device.name} | MAC: {sensor_device.address}")
    print("\n2. Estableciendo conexión GATT...")

    # Conectarse al dispositivo encontrado
    async with BleakClient(sensor_device) as client:
        print(f"🔗 Conexión establecida: {client.is_connected}")
        print("\n3. Inspeccionando servicios y características disponibles:")
        
        for service in client.services:
            print(f"\n📦 Servicio UUID: {service.uuid}")
            print(f"   Descripción: {service.description}")
            for char in service.characteristics:
                propiedades = ", ".join(char.properties)
                print(f"   └── 🔹 Característica UUID: {char.uuid} [{propiedades}]")

        print("\n✨ Inspección completada exitosamente.")

if __name__ == "__main__":
    asyncio.run(main())
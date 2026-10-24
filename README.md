# Asistencia QR (Python)
Tkinter + OpenCV + SQLite. Estructura: main.py (interfaz), qr_config.py (TUS QR y ajustes), camaras.py (detección y apertura de cámaras), db.py (SQLite), qr_utils.py (lectura/parseo), generar_qr.py (QR de prueba), requirements.txt.

## Instalación
    python -m venv venv
    venv\Scripts\activate          (Windows)   |   source venv/bin/activate   (Linux/Mac)
    pip install -r requirements.txt
Linux: sudo apt install python3-tk

## Ejecución
    python generar_qr.py     # crea qr_alumnos/*.png (uno por cada QR de qr_config.py)
    python main.py

## pyzbar (opcional)
    Windows: pip install pyzbar (incluye las DLL; si falla instala "Visual C++ Redistributable 2013")
    Linux:   sudo apt install libzbar0 && pip install pyzbar
    macOS:   brew install zbar && pip install pyzbar
    Si Apple Silicon no lo encuentra: export DYLD_LIBRARY_PATH=$(brew --prefix zbar)/lib

## Cámaras externas (USB)
- Al abrir la app se buscan todas las cámaras y aparecen en el selector con nombre, tipo (integrada / externa / virtual) y resolución.
- Si conectas una cámara con la app abierta, se detecta sola (Linux al instante; Windows/macOS cuando no hay cámara activa, o con el botón "Buscar cámaras").
- Si se desconecta el cable, la app avisa y vuelve a buscar sola; al reconectar, retoma la cámara.
- Al arrancar usa la cámara que elegiste la última vez (se guarda en config.json). Si nunca elegiste, prefiere una externa sobre la integrada, y ignora las virtuales (OBS, etc.) salvo que sean la única.
- Se prueban varios perfiles (1280x720 -> 640x480 -> MJPG 1280x720) sin forzar formato al inicio (evita imagen corrupta en cámaras virtuales como Camo/DroidCam), así que cámaras externas que rechazan la configuración de la webcam de la laptop funcionan igual.
- Windows: `pip install pygrabber` (opcional) para ver el nombre real de cada cámara; sin él se muestran como "Cámara 0", "Cámara 1"...
- Si una cámara no abre: puede estar en uso por otra app (Zoom, Teams, navegador) o sin permisos de cámara del sistema.
- Si una cámara (típico: cámaras virtuales como Camo, DroidCam o la cámara de un teléfono) muestra la imagen con franjas de colores o a medias, la app lo detecta y prueba otro motor de video (Windows: DirectShow y luego Media Foundation). El motor usado se ve en el mensaje de estado, p. ej. "Camo (1280x720 · MSMF)".

## Agregar tus QR (qr_config.py)
Abre `qr_config.py` y agrega una línea por persona en `QR_REGISTRADOS`:

    ("EMP-100", "Luis Pérez"),

- El código es el texto que contiene el QR. Puedes usar QR que ya tengas impresos (con cualquier contenido) o crear los tuyos con `python generar_qr.py`.
- Para quitar a alguien, pon su código en `QR_ELIMINAR` (sus asistencias anteriores se conservan).
- Un QR que no esté en la lista se rechaza con el aviso "no está registrado".
- Los cambios se aplican al volver a abrir la app. El botón "Agregar alumno" sigue funcionando.

## Entrada y salida
- 1.er escaneo del día = ENTRADA (mensaje verde); 2.º escaneo = SALIDA (mensaje azul); a partir del 3.º se avisa que ya está completo y no cambia nada.
- Hay una sola fila por persona y día, con columnas Entrada y Salida (también en el CSV).
- `SEGUNDOS_ENTRE_ENTRADA_Y_SALIDA` (en qr_config.py, 60 por defecto) evita que un QR sostenido frente a la cámara marque la salida por accidente. Ponlo en 0 para pruebas.
- Tu base de datos anterior se actualiza sola: los registros viejos quedan como entradas sin salida.
- El día cambia a medianoche: un turno que cruce las 00:00 contaría como dos días distintos.

## Si la cámara muestra la imagen con franjas de colores (Windows)
Pasa con cámaras virtuales o de teléfono (Camo, DroidCam, iVCam, OBS...): el motor DirectShow entrega la imagen mal interpretada.
- La app lo detecta sola: descarta esa imagen y prueba otros formatos y el motor Media Foundation. Las cámaras con nombre Camo/DroidCam/iVCam/OBS... empiezan directamente por Media Foundation.
- El mensaje bajo el video muestra el motor en uso, p. ej. "Camo (1280x720 · MSMF)".
- Si aun así se ve mal, usa el selector **Motor** (junto a "Buscar cámaras"): prueba "Media Foundation" y luego "DirectShow". La elección se recuerda en config.json y la cámara se reabre al cambiarla.
- Si ningún motor entrega una imagen válida, la cámara se abre igual con un aviso amarillo ("puede verse distorsionada").
- Con Media Foundation el número de cámara podría no coincidir con el de DirectShow si tienes varias; con una sola no hay problema.

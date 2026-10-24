"""Genera un PNG con el QR de cada persona en la carpeta qr_alumnos/ (para pruebas o impresión).
La lista sale de qr_config.py (y de los alumnos agregados desde la app)."""
import json
import re
from pathlib import Path

import qrcode

import db

db.init_db()  # también aplica qr_config.py a la base de datos
salida = Path(__file__).parent / "qr_alumnos"
salida.mkdir(exist_ok=True)
lista = db.alumnos()
for a in lista:
    # json.dumps escapa los acentos (\u00f3): el QR queda en ASCII y se lee sin errores de codificación
    payload = json.dumps({"n": a["nombre"], "m": a["matricula"]})
    archivo = re.sub(r"[^\w.-]", "_", a["matricula"])[:60] or "qr"   # nombre de archivo seguro
    qrcode.make(payload).save(salida / f"{archivo}.png")
    print("Generado:", a["matricula"], "-", a["nombre"])
print(f"{len(lista)} QR en {salida}")

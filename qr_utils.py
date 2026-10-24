"""Lectura y análisis de códigos QR."""
import json

import cv2
import numpy as np

# pyzbar es opcional: si falta la librería nativa zbar, se usa OpenCV.
try:
    from pyzbar import pyzbar
except Exception:  # ImportError o "Unable to find zbar shared library"
    pyzbar = None

_detector = None


def leer_qr(frame):
    """Devuelve (texto, puntos) del primer QR del frame, o (None, None)."""
    global _detector
    if pyzbar:
        for o in pyzbar.decode(frame, symbols=[pyzbar.ZBarSymbol.QRCODE]):
            pts = np.array([[p.x, p.y] for p in o.polygon]) if o.polygon else None
            return o.data.decode("utf-8", "replace"), pts
        return None, None
    if _detector is None:
        _detector = cv2.QRCodeDetector()
    texto, pts, _ = _detector.detectAndDecode(frame)
    pts = pts.reshape(-1, 2) if pts is not None else None
    if texto:
        try:  # OpenCV a veces entrega UTF-8 interpretado como latin-1
            texto = texto.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return (texto or None), pts


def parse_qr(texto):
    """Interpreta el contenido de un QR. Acepta:
      {"n": "Nombre", "m": "Código"}   (los que genera generar_qr.py)
      "Nombre|Código"
      cualquier otro texto: se toma completo como el código (QR propios, impresos antes).
    Devuelve {'nombre', 'matricula'} (matricula = código) o None si el QR está vacío."""
    texto = (texto or "").strip()
    if not texto:
        return None
    try:
        d = json.loads(texto)
        m = d.get("m") or d.get("matricula")
        if m:
            return {"matricula": str(m).strip(), "nombre": str(d.get("n") or d.get("nombre") or "").strip()}
    except (ValueError, AttributeError):
        pass
    partes = texto.split("|")
    if len(partes) == 2 and partes[1].strip():
        return {"nombre": partes[0].strip(), "matricula": partes[1].strip()}
    return {"nombre": "", "matricula": texto}

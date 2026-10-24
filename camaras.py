"""Detección y apertura de cámaras (integradas y externas).

- buscar_camaras(): encuentra las cámaras que REALMENTE entregan imagen, con su nombre cuando el
  sistema lo permite (Linux: sysfs; Windows: pygrabber opcional; macOS: system_profiler).
- elegir(): decide cuál abrir (la última que el usuario eligió; si no, prefiere una externa).
- abrir(): abre la cámara probando varios perfiles (1280x720 -> 640x480 -> MJPG 1280x720), porque
  muchas cámaras externas no aceptan la configuración que sí acepta la webcam de la laptop.
  No se fuerza ningún formato (fourcc) al principio: las cámaras virtuales (Camo, DroidCam, OBS...)
  aceptan el pedido pero entregan otro formato, y la imagen sale corrupta (franjas de colores).
"""
import glob
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

WIN = sys.platform.startswith("win")
MAC = sys.platform == "darwin"
LINUX = sys.platform.startswith("linux")

# Windows: DirectShow primero (índices compatibles con los nombres de pygrabber) y Media Foundation como
# respaldo: algunas cámaras virtuales (Camo, etc.) salen corruptas con DirectShow y bien con Media Foundation.
BACKENDS = (cv2.CAP_DSHOW, cv2.CAP_MSMF) if WIN else (cv2.CAP_ANY,)
BACKEND = BACKENDS[0]
CONFIG = Path(__file__).parent / "config.json"

# (fourcc, ancho, alto): se prueban en orden hasta que la cámara entregue imagen.
# MJPG va al final: solo ayuda a algunas cámaras USB y corrompe la imagen en las virtuales.
PERFILES = ((None, 1280, 720), (None, 640, 480), ("MJPG", 1280, 720), ("YUY2", 1280, 720))
MOTORES_VALIDOS = ("auto", "dshow", "msmf")

_VIRTUAL = re.compile(r"virtual|\bobs\b|snap camera|manycam|xsplit|streamlabs|nvidia broadcast", re.I)
# Cámaras virtuales / de teléfono: con DirectShow suelen entregar imagen corrupta (franjas), así que en
# Windows se prueba primero Media Foundation.
_MSMF_PRIMERO = re.compile(r"camo|droidcam|iriun|ivcam|epoccam|virtual|\bobs\b|snap camera|manycam|xsplit"
                           r"|streamlabs|nvidia broadcast", re.I)
_INTEGRADA = re.compile(r"integrated|built-?in|facetime|internal|integrada|interna", re.I)
_EXTERNA = re.compile(r"logitech|brio|\bc9[2-3]\d\b|\bc270\b|kiyo|elgato|razer|lifecam|external|externa"
                      r"|obsbot|insta360|avermedia|jabra|anker|hikvision|a4tech", re.I)
_PUNTAJE = {"virtual": 0, "integrada": 1, "": 2, "externa": 3}

try:  # silencia los avisos de OpenCV al probar índices que no existen
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
except Exception:
    pass


# ---------------------------------------------------------------- nombres de dispositivo
def _tipo(nombre):
    if not nombre:
        return ""
    if _VIRTUAL.search(nombre):
        return "virtual"
    if _INTEGRADA.search(nombre):
        return "integrada"
    if _EXTERNA.search(nombre):
        return "externa"
    return ""


def _nombres_linux():
    """{indice: nombre} solo de nodos de captura (index 0); los demás nodos /dev/videoN suelen ser metadatos."""
    res = {}
    for ruta in glob.glob("/sys/class/video4linux/video*"):
        m = re.search(r"video(\d+)$", ruta)
        try:
            if (Path(ruta) / "index").read_text().strip() == "0":
                res[int(m.group(1))] = (Path(ruta) / "name").read_text().strip()
        except (OSError, AttributeError):
            continue
    return res


def _nombres_windows():
    """Nombres en el mismo orden que los índices de DirectShow. Requiere `pip install pygrabber` (opcional)."""
    try:
        import comtypes
        from pygrabber.dshow_graph import FilterGraph
    except Exception:
        return {}
    try:
        comtypes.CoInitialize()  # este código corre en un hilo secundario
    except Exception:
        pass
    try:
        return dict(enumerate(FilterGraph().get_input_devices()))
    except Exception:
        return {}


def _nombres_mac():
    """Lista de nombres de cámara (el orden suele coincidir con los índices de OpenCV)."""
    try:
        out = subprocess.run(["system_profiler", "SPCameraDataType", "-json"],
                             capture_output=True, text=True, timeout=8).stdout
        return [d["_name"] for d in json.loads(out).get("SPCameraDataType", [])]
    except Exception:
        return []


def _nombres():
    if LINUX:
        return _nombres_linux()
    if WIN:
        return _nombres_windows()
    return {}


def firma_dispositivos():
    """Huella barata de los dispositivos de video (solo Linux): permite detectar que se conectó o
    desconectó una cámara sin abrir ninguna. En otros sistemas devuelve None (usar 'Buscar cámaras')."""
    if not LINUX:
        return None
    return tuple(sorted(glob.glob("/dev/video*")))


# ---------------------------------------------------------------- apertura / prueba
def _abrir_cap(indice, motor=None):
    cap = cv2.VideoCapture(indice, BACKEND if motor is None else motor)
    if cap.isOpened():
        return cap
    cap.release()
    return None


def _leer_frame(cap, intentos=8, pausa=0.08):
    """Las cámaras USB suelen tardar unos frames en arrancar: reintenta antes de rendirse."""
    for _ in range(intentos):
        ok, frame = cap.read()
        if ok and frame is not None and frame.size:
            return frame
        time.sleep(pausa)
    return None


def _frame_valido(frame):
    """False si la imagen parece corrupta por un formato de video mal interpretado:
    1) contenido arriba y negro absoluto en la parte baja;
    2) bandas negras intercaladas con bandas de contenido (una imagen real, como mucho, tiene barras
       negras arriba y abajo = 2 cambios);
    3) ruido de columnas alternadas (diferencia enorme entre píxeles vecinos).
    Una imagen totalmente negra (cámara tapada o sin señal) NO se considera corrupta."""
    if frame is None or frame.size == 0:
        return False
    gris = frame.max(axis=2) if frame.ndim == 3 else frame
    alto = gris.shape[0]
    con_contenido = gris.max(axis=1) > 0           # una fila es "negra" solo si TODOS sus píxeles valen 0
    if not con_contenido.any():
        return True
    if not con_contenido[int(alto * 0.6):].any() and con_contenido[:int(alto * 0.3)].any():
        return False
    if np.count_nonzero(con_contenido[1:] != con_contenido[:-1]) > 4:
        return False
    filas = gris[con_contenido].astype(np.int16)
    return float(np.abs(np.diff(filas, axis=1)).mean()) <= 100


def _leer_valido(cap, intentos=10, pausa=0.08):
    """(frame_valido_o_None, hubo_algun_frame). Descarta frames corruptos."""
    hubo = False
    for _ in range(intentos):
        ok, frame = cap.read()
        if ok and frame is not None and frame.size:
            hubo = True
            if _frame_valido(frame):
                return frame, True
        time.sleep(pausa)
    return None, hubo


def _probar(indice):
    """(ancho, alto) si el índice es una cámara que entrega imagen; None si no."""
    cap = _abrir_cap(indice)
    if cap is None:
        return None
    try:
        frame = _leer_frame(cap)
        return (frame.shape[1], frame.shape[0]) if frame is not None else None
    finally:
        cap.release()


def _motores(nombre, preferido):
    """Motores de video a probar, en orden. Solo Windows tiene varios (DirectShow y Media Foundation)."""
    if not WIN:
        return (cv2.CAP_ANY,)
    if preferido == "dshow":
        return (cv2.CAP_DSHOW,)
    if preferido == "msmf":
        return (cv2.CAP_MSMF,)
    if _MSMF_PRIMERO.search(nombre or ""):
        return tuple(reversed(BACKENDS))
    return BACKENDS


def _abrir_perfil(indice, motor, perfil):
    cap = _abrir_cap(indice, motor)
    if cap is None:
        return None
    fourcc, ancho, alto = perfil
    if fourcc:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, ancho)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, alto)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # menos retraso entre la imagen real y la pantalla
    return cap


def abrir(indice, nombre="", motor="auto"):
    """Abre la cámara y la deja lista. Devuelve (cap, ancho, alto, formato_ok) o (None, 0, 0, False).
    Prueba cada motor de video con cada perfil y se queda con la primera combinación que entrega una
    imagen NO corrupta. Si ninguna lo logra pero alguna entregó imagen, abre esa con formato_ok=False
    (para no dejar sin cámara a quien tenga una imagen válida que el detector juzgó mal)."""
    primero = None
    for m in _motores(nombre, motor):
        for perfil in PERFILES:
            cap = _abrir_perfil(indice, m, perfil)
            if cap is None:
                break  # este motor no ve la cámara: pasa al siguiente motor
            frame, hubo = _leer_valido(cap)
            if frame is not None:
                return cap, frame.shape[1], frame.shape[0], True
            cap.release()
            if hubo and primero is None:
                primero = (m, perfil)
    if primero:
        cap = _abrir_perfil(indice, *primero)
        if cap is not None:
            frame = _leer_frame(cap, intentos=15)
            if frame is not None:
                return cap, frame.shape[1], frame.shape[0], False
            cap.release()
    return None, 0, 0, False


def buscar_camaras(activa=None, maximo=8):
    """Lista de dicts {indice, nombre, tipo, ancho, alto}.
    `activa` es la cámara que la app ya tiene abierta: no se vuelve a abrir (en Windows fallaría
    porque está en uso) y se conserva en la lista."""
    nombres = _nombres()
    por_sysfs = LINUX and bool(nombres)
    candidatos = sorted(nombres) if por_sysfs else range(maximo)

    encontradas, fallos = [], 0
    for i in candidatos:
        if activa and i == activa["indice"]:
            encontradas.append(dict(activa))
            fallos = 0
            continue
        dim = _probar(i)
        if dim:
            encontradas.append({"indice": i, "ancho": dim[0], "alto": dim[1]})
            fallos = 0
        else:
            fallos += 1
            if not por_sysfs and fallos >= 3:  # 3 índices vacíos seguidos: no hay más cámaras
                break
    if activa and not any(c["indice"] == activa["indice"] for c in encontradas):
        encontradas.append(dict(activa))
        encontradas.sort(key=lambda c: c["indice"])

    if MAC:
        lista = _nombres_mac()
        if len(lista) == len(encontradas):  # solo si el conteo coincide; si no, mejor sin nombre que uno falso
            nombres = {c["indice"]: n for c, n in zip(encontradas, lista)}
    for c in encontradas:
        c["nombre"] = nombres.get(c["indice"], "")
        c["tipo"] = _tipo(c["nombre"])
    return encontradas


# ---------------------------------------------------------------- selección y preferencia
def etiqueta(cam):
    nombre = f"{cam['nombre']} [{cam['indice']}]" if cam.get("nombre") else f"Cámara {cam['indice']}"
    extra = {"externa": " · externa", "integrada": " · integrada", "virtual": " · virtual"}.get(cam.get("tipo"), "")
    return f"{nombre}{extra} ({cam['ancho']}x{cam['alto']})"


def nombre_corto(cam):
    return cam.get("nombre") or f"Cámara {cam['indice']}"


def _leer_config():
    try:
        datos = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return datos if isinstance(datos, dict) else {}


def _escribir_config(datos):
    try:
        CONFIG.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass  # carpeta de solo lectura: la app sigue funcionando, solo no recuerda la elección


def cargar_preferencia():
    pref = _leer_config().get("camara")
    return pref if isinstance(pref, dict) else {}


def guardar_preferencia(cam):
    datos = _leer_config()
    datos["camara"] = {"nombre": cam.get("nombre", ""), "indice": cam["indice"]}
    _escribir_config(datos)


def cargar_motor():
    """'auto' | 'dshow' | 'msmf' (motor de video elegido por el usuario; solo tiene efecto en Windows)."""
    motor = _leer_config().get("motor")
    return motor if motor in MOTORES_VALIDOS else "auto"


def guardar_motor(motor):
    datos = _leer_config()
    datos["motor"] = motor if motor in MOTORES_VALIDOS else "auto"
    _escribir_config(datos)


def buscar_preferida(camaras, pref):
    """La cámara guardada por el usuario si está conectada: mismo nombre e índice > mismo nombre >
    mismo índice (solo si no hay nombres). None si no está."""
    if not pref:
        return None
    nombre, indice = pref.get("nombre", ""), pref.get("indice")
    if nombre:
        iguales = [c for c in camaras if c.get("nombre") == nombre]
        for c in iguales:
            if c["indice"] == indice:
                return c
        if iguales:
            return iguales[0]
        return None
    for c in camaras:
        if not c.get("nombre") and c["indice"] == indice:
            return c
    return None


def elegir(camaras, pref):
    """1) la que el usuario eligió la última vez; 2) la de mayor puntaje (externa > desconocida >
    integrada > virtual); en empate, la de menor índice. `camaras` no debe estar vacía."""
    return buscar_preferida(camaras, pref) or max(
        camaras, key=lambda c: (_PUNTAJE[c.get("tipo", "")], -c["indice"]))

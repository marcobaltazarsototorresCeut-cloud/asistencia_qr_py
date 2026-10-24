"""Capa de datos: SQLite (incluido en Python, sin instalación extra)."""
import csv
import math
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import qr_config

DB_PATH = Path(__file__).parent / "asistencia.db"


@contextmanager
def conexion():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db():
    with conexion() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS alumnos (
                matricula TEXT PRIMARY KEY COLLATE NOCASE,
                nombre    TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS asistencias (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                matricula   TEXT NOT NULL COLLATE NOCASE,
                nombre      TEXT NOT NULL,
                fecha       TEXT NOT NULL,   -- YYYY-MM-DD
                hora        TEXT NOT NULL,   -- HH:MM:SS  (hora de ENTRADA)
                hora_salida TEXT,            -- HH:MM:SS  (NULL hasta el segundo escaneo)
                UNIQUE (matricula, fecha)    -- una fila por persona y día
            );
        """)
        # Bases creadas con la versión anterior (sin salida): se les agrega la columna y se conservan los datos.
        columnas = {r["name"] for r in c.execute("PRAGMA table_info(asistencias)")}
        if "hora_salida" not in columnas:
            c.execute("ALTER TABLE asistencias ADD COLUMN hora_salida TEXT")
    sincronizar_qr()


def sincronizar_qr():
    """Aplica qr_config.py: agrega/actualiza QR_REGISTRADOS y da de baja QR_ELIMINAR."""
    with conexion() as c:
        for entrada in qr_config.QR_REGISTRADOS:
            if not (isinstance(entrada, (tuple, list)) and len(entrada) == 2):
                print(f'[qr_config] Línea ignorada (usa ("CÓDIGO", "Nombre")): {entrada!r}')
                continue
            codigo, nombre = str(entrada[0]).strip(), str(entrada[1]).strip()
            if not codigo or not nombre:
                print(f"[qr_config] Línea ignorada (código o nombre vacío): {entrada!r}")
                continue
            c.execute("INSERT INTO alumnos (matricula, nombre) VALUES (?, ?) "
                      "ON CONFLICT(matricula) DO UPDATE SET nombre = excluded.nombre", (codigo, nombre))
        for codigo in qr_config.QR_ELIMINAR:
            c.execute("DELETE FROM alumnos WHERE matricula = ?", (str(codigo).strip(),))


def alumnos():
    with conexion() as c:
        return [dict(r) for r in c.execute("SELECT * FROM alumnos ORDER BY nombre")]


def agregar_alumno(matricula, nombre):
    """Devuelve True si se agregó, False si la matrícula ya existía."""
    try:
        with conexion() as c:
            c.execute("INSERT INTO alumnos VALUES (?, ?)", (matricula.strip(), nombre.strip()))
        return True
    except sqlite3.IntegrityError:
        return False


def registrar(codigo, ahora=None):
    """Registra un escaneo: el 1.º del día es la ENTRADA y el 2.º es la SALIDA.

    Devuelve un dict con 'estado':
      'entrada' | 'salida' -> se registró en 'hora'
      'espera'             -> la salida llegó demasiado pronto; 'faltan' son los segundos restantes
      'completo'           -> ya tenía entrada y salida hoy
      'desconocido'        -> el código no está registrado
    y además 'alumno', 'entrada' y 'salida' (None si aún no existen)."""
    ahora = (ahora or datetime.now()).replace(microsecond=0)
    fecha, hora = ahora.strftime("%Y-%m-%d"), ahora.strftime("%H:%M:%S")
    res = {"estado": "desconocido", "alumno": None, "entrada": None, "salida": None, "hora": None, "faltan": 0}
    with conexion() as c:
        a = c.execute("SELECT * FROM alumnos WHERE matricula = ?", (codigo,)).fetchone()
        if a is None:
            return res
        res["alumno"] = dict(a)
        fila = c.execute("SELECT id, hora, hora_salida FROM asistencias WHERE matricula = ? AND fecha = ?",
                         (a["matricula"], fecha)).fetchone()
        if fila is None:
            c.execute("INSERT INTO asistencias (matricula, nombre, fecha, hora) VALUES (?,?,?,?)",
                      (a["matricula"], a["nombre"], fecha, hora))
            res.update(estado="entrada", entrada=hora, hora=hora)
            return res
        res.update(entrada=fila["hora"], salida=fila["hora_salida"])
        if fila["hora_salida"] is not None:
            res["estado"] = "completo"
            return res
        entrada_dt = datetime.strptime(f"{fecha} {fila['hora']}", "%Y-%m-%d %H:%M:%S")
        faltan = math.ceil(qr_config.SEGUNDOS_ENTRE_ENTRADA_Y_SALIDA - (ahora - entrada_dt).total_seconds())
        if faltan > 0:
            res.update(estado="espera", faltan=faltan)
            return res
        c.execute("UPDATE asistencias SET hora_salida = ? WHERE id = ?", (hora, fila["id"]))
        res.update(estado="salida", salida=hora, hora=hora)
        return res


def asistencias(fecha=None):
    fecha = fecha or datetime.now().strftime("%Y-%m-%d")
    with conexion() as c:
        return [dict(r) for r in c.execute(
            "SELECT matricula, nombre, fecha, hora, hora_salida FROM asistencias WHERE fecha=? ORDER BY hora",
            (fecha,))]


def exportar_csv(fecha, ruta):
    """CSV con BOM (utf-8-sig) para que Excel muestre bien los acentos."""
    filas = asistencias(fecha)
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Matrícula", "Nombre", "Fecha", "Entrada", "Salida"])
        w.writerows([[r["matricula"], r["nombre"], r["fecha"], r["hora"], r["hora_salida"] or ""] for r in filas])
    return len(filas)

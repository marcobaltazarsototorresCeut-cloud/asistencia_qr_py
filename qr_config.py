"""CONFIGURACIÓN DE QR Y HORARIOS  —  este es el único archivo que necesitas editar.

Los cambios se aplican la próxima vez que abras la app (o ejecutes generar_qr.py).
"""

# ============================================================================================
#  1) AGREGA AQUÍ LOS QR QUE QUIERAS
#
#  Una línea por persona:      ("CÓDIGO", "Nombre completo"),
#
#  - CÓDIGO es el texto que contiene el QR (matrícula, número de empleado, etc.).
#  - Si ya tienes QR impresos, escribe exactamente el texto que traen: se aceptan QR con
#    cualquier contenido, siempre que su código esté en esta lista.
#  - Si todavía no tienes los QR, ejecuta `python generar_qr.py`: crea un PNG por cada
#    línea de esta lista en la carpeta qr_alumnos/.
#  - Si cambias el nombre de un código que ya existía, el nombre se actualiza.
#  - Un QR que NO esté aquí (ni agregado con el botón "Agregar alumno") se rechaza.
# ============================================================================================
QR_REGISTRADOS = [
    ("A001", "Ana López Martínez"),
    ("A002", "Carlos Hernández Ruiz"),
    ("A003", "María Fernanda Torres"),
    # ("A004", "Escribe aquí otro nombre"),
]

# ============================================================================================
#  2) QUITAR QR (opcional)
#  Escribe aquí los códigos que quieras dar de baja, por ejemplo: ["A001", "A002"]
#  Se borran de la lista de personas; sus asistencias anteriores se conservan.
# ============================================================================================
QR_ELIMINAR = []

# ============================================================================================
#  3) ENTRADA Y SALIDA
#  El 1.er escaneo del día registra la ENTRADA y el 2.º la SALIDA. Los siguientes se ignoran.
#
#  Segundos que deben pasar entre la entrada y la salida. Evita que un solo QR sostenido frente
#  a la cámara registre entrada y salida por accidente. Ponlo en 0 para desactivarlo (útil al
#  hacer pruebas).
# ============================================================================================
SEGUNDOS_ENTRE_ENTRADA_Y_SALIDA = 60

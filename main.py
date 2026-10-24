"""Asistencia por QR con webcam integrada o cámara externa (Tkinter + OpenCV + SQLite)."""
import os

# Debe ir antes de importar cv2: evita que Media Foundation (Windows) tarde ~30 s en abrir cámaras.
os.environ.setdefault("OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS", "0")

import queue
import threading
import time
import tkinter as tk
from datetime import date
from tkinter import filedialog, messagebox, simpledialog, ttk

import cv2
from PIL import Image, ImageTk

import camaras
import db
from qr_utils import leer_qr, parse_qr

COOLDOWN = 3.0          # segundos antes de volver a procesar el mismo QR
ANCHO_VIDEO = 640
FALLOS_MAX = 20         # lecturas fallidas seguidas (~0.6 s) antes de dar la cámara por desconectada
REBUSCAR_CADA = 4.0     # segundos entre búsquedas automáticas mientras no hay cámara
REVISAR_USB_CADA = 2.0  # segundos entre revisiones de conexión/desconexión (Linux)
MOTORES = {"Motor: automático": "auto", "Motor: DirectShow": "dshow", "Motor: Media Foundation": "msmf"}
COLORES = {"ok": "#c8f0d2", "salida": "#cfe3f7", "duplicado": "#fff0b8", "error": "#f6c9c9", "info": "#e8e8e8"}


class App:
    def __init__(self, root):
        self.root = root
        root.title("Asistencia QR")
        db.init_db()
        self.cap = None
        self.cam = None              # cámara abierta ahora (dict de camaras.py)
        self.lista_camaras = []      # resultado de la última búsqueda
        self.ultimo = ("", 0.0)      # (texto, momento) para el anti-rebote
        self.cola = queue.Queue()    # resultados de los hilos de búsqueda / apertura (Tk solo se toca en el hilo principal)
        self.escaneando = False
        self.abriendo = False
        self.gen = 0                 # identifica la última petición de apertura (descarta respuestas viejas)
        self.fallos = 0
        self.auto_buscar = True      # buscar solas mientras no haya cámara
        self.t_rescan = 0.0
        self.t_usb = 0.0
        self.firma = camaras.firma_dispositivos()

        # ---------- Interfaz ----------
        izq = ttk.Frame(root, padding=8); izq.grid(row=0, column=0, sticky="n")
        der = ttk.Frame(root, padding=8); der.grid(row=0, column=1, sticky="nsew")
        root.columnconfigure(1, weight=1); root.rowconfigure(0, weight=1)

        barra = ttk.Frame(izq); barra.pack(fill="x", pady=(0, 6))
        ttk.Label(barra, text="Cámara:").pack(side="left")
        self.combo = ttk.Combobox(barra, state="readonly", width=30)
        self.combo.pack(side="left", padx=6)
        self.combo.bind("<<ComboboxSelected>>", self.al_elegir)
        ttk.Button(barra, text="Buscar cámaras", command=lambda: self.buscar_camaras(manual=True)).pack(side="left")
        self.combo_motor = None
        if camaras.WIN:  # solo Windows tiene varios motores de video; sirve si una cámara sale con la imagen distorsionada
            etiqueta = next(k for k, v in MOTORES.items() if v == camaras.cargar_motor())
            self.combo_motor = ttk.Combobox(barra, state="readonly", width=22, values=list(MOTORES))
            self.combo_motor.set(etiqueta)
            self.combo_motor.pack(side="left", padx=6)
            self.combo_motor.bind("<<ComboboxSelected>>", self.al_cambiar_motor)

        self.video = ttk.Label(izq, background="#222")
        self.video.pack()
        self.estado = tk.Label(izq, text="Iniciando...", font=("Segoe UI", 14), width=44, height=4,
                               wraplength=ANCHO_VIDEO - 20, bg=COLORES["info"])
        self.estado.pack(fill="x", pady=8)

        filtro = ttk.Frame(der); filtro.pack(fill="x")
        ttk.Label(filtro, text="Fecha (AAAA-MM-DD):").pack(side="left")
        self.fecha = tk.StringVar(value=date.today().isoformat())
        ttk.Entry(filtro, textvariable=self.fecha, width=12).pack(side="left", padx=6)
        ttk.Button(filtro, text="Ver", command=self.refrescar).pack(side="left")
        ttk.Button(filtro, text="Exportar CSV", command=self.exportar).pack(side="right")

        self.tabla = ttk.Treeview(der, columns=("mat", "nom", "ent", "sal"), show="headings", height=16)
        for col, txt, w in (("mat", "Matrícula", 90), ("nom", "Nombre", 200), ("ent", "Entrada", 80), ("sal", "Salida", 80)):
            self.tabla.heading(col, text=txt); self.tabla.column(col, width=w)
        self.tabla.pack(fill="both", expand=True, pady=6)
        self.total = ttk.Label(der); self.total.pack(anchor="w")
        ttk.Button(der, text="Agregar alumno", command=self.agregar_alumno).pack(anchor="e")

        root.protocol("WM_DELETE_WINDOW", self.cerrar)
        self.refrescar()
        self.buscar_camaras(manual=True)
        self.bucle()

    # ---------- Cámara: búsqueda, selección y apertura (en hilos para no congelar la ventana) ----------
    def buscar_camaras(self, manual=False):
        if self.escaneando:
            return
        if manual:
            self.auto_buscar = True
            if not self.cap:
                self.mensaje("info", "Buscando cámaras...")
        self.escaneando = True
        activa = dict(self.cam) if (self.cap and self.cam) else None

        def tarea():
            try:
                lista = camaras.buscar_camaras(activa)
            except Exception:
                lista = []
            self.cola.put(("escaneo", lista))

        threading.Thread(target=tarea, daemon=True).start()

    def tras_escaneo(self, lista):
        self.escaneando = False
        self.t_rescan = time.time()
        self.lista_camaras = lista
        self.combo["values"] = [camaras.etiqueta(c) for c in lista]
        if not lista:
            self.cerrar_camara()
            self.combo.set("")
            self.auto_buscar = True
            self.mensaje("error", "No se detectó ninguna cámara.\nConéctala (o ciérrala en otras apps); "
                                  "se buscará automáticamente.\n(Windows/macOS: revisa los permisos de cámara.)")
            return
        preferida = camaras.buscar_preferida(lista, camaras.cargar_preferencia())
        if self.cap and self.cam:
            self.sincronizar_combo()
            # Si se acaba de conectar la cámara que el usuario eligió la última vez, cambia a ella.
            if preferida and preferida["indice"] != self.cam["indice"]:
                self.abrir_camara(preferida)
            return
        self.abrir_camara(preferida or camaras.elegir(lista, {}))

    def al_elegir(self, _evento=None):
        pos = self.combo.current()
        if 0 <= pos < len(self.lista_camaras):
            self.abrir_camara(self.lista_camaras[pos], guardar=True)

    def al_cambiar_motor(self, _evento=None):
        """El usuario fuerza un motor de video (se recuerda) y se reabre la cámara actual con él."""
        camaras.guardar_motor(MOTORES[self.combo_motor.get()])
        if self.cam:
            self.abrir_camara(dict(self.cam))
        else:
            self.buscar_camaras(manual=True)

    def abrir_camara(self, cam, guardar=False):
        self.cerrar_camara()
        self.gen += 1
        gen, self.abriendo = self.gen, True
        motor = camaras.cargar_motor()
        self.mensaje("info", f"Abriendo {camaras.nombre_corto(cam)}...")

        def tarea():
            cap, ancho, alto, formato_ok = camaras.abrir(cam["indice"], cam.get("nombre", ""), motor)
            self.cola.put(("apertura", gen, cam, cap, ancho, alto, formato_ok, guardar))

        threading.Thread(target=tarea, daemon=True).start()

    def tras_apertura(self, gen, cam, cap, ancho, alto, formato_ok, guardar):
        if gen != self.gen:  # el usuario ya pidió otra cámara: esta respuesta quedó vieja
            if cap:
                cap.release()
            return
        self.abriendo = False
        if cap is None:
            self.auto_buscar = False  # no reintentar en bucle: el usuario decide
            self.mensaje("error", f"No se pudo abrir {camaras.nombre_corto(cam)}.\nPuede estar en uso por otra "
                                  "aplicación, sin permisos o entrega un formato de video no compatible.\n"
                                  "Elige otra cámara o pulsa Buscar cámaras.")
            return
        self.cap, self.fallos = cap, 0
        self.cam = dict(cam, ancho=ancho, alto=alto)
        if guardar:  # solo se recuerda lo que el usuario eligió, no lo que la app eligió sola
            camaras.guardar_preferencia(self.cam)
        self.sincronizar_combo()
        try:
            motor = f" · {cap.getBackendName()}"
        except Exception:
            motor = ""
        texto = f"{camaras.nombre_corto(cam)} ({ancho}x{alto}{motor})\nAcerca el código QR a la cámara."
        if not formato_ok:
            texto += "\nAviso: la imagen puede verse distorsionada." + (" Prueba otro motor de video." if camaras.WIN else "")
        self.mensaje("duplicado" if not formato_ok else "info", texto)

    def sincronizar_combo(self):
        for pos, c in enumerate(self.lista_camaras):
            if self.cam and c["indice"] == self.cam["indice"]:
                self.combo.current(pos)
                return

    def cerrar_camara(self):
        if self.cap:
            self.cap.release()
        self.cap = self.cam = None

    def procesar_cola(self):
        try:
            while True:
                tipo, *datos = self.cola.get_nowait()
                if tipo == "escaneo":
                    self.tras_escaneo(*datos)
                elif tipo == "apertura":
                    self.tras_apertura(*datos)
        except queue.Empty:
            pass

    def vigilar(self):
        """Sin cámara: reintenta sola. Con o sin cámara (Linux): detecta conexión/desconexión USB."""
        ahora = time.time()
        if self.escaneando or self.abriendo:
            return
        if not self.cap and self.auto_buscar and ahora - self.t_rescan >= REBUSCAR_CADA:
            self.buscar_camaras()
        elif ahora - self.t_usb >= REVISAR_USB_CADA:
            self.t_usb = ahora
            firma = camaras.firma_dispositivos()
            if firma is not None and firma != self.firma:
                self.firma = firma
                self.buscar_camaras()

    def bucle(self):
        """Se ejecuta ~30 veces por segundo: lee un frame, busca QR y lo muestra."""
        self.procesar_cola()
        if self.cap:
            ok, frame = self.cap.read()
            if ok and frame is not None:
                self.fallos = 0
                texto, pts = leer_qr(frame)
                if pts is not None:
                    cv2.polylines(frame, [pts.astype(int)], True, (0, 200, 0), 4)
                if texto:
                    self.procesar(texto)
                alto = int(frame.shape[0] * ANCHO_VIDEO / frame.shape[1])
                rgb = cv2.cvtColor(cv2.resize(frame, (ANCHO_VIDEO, alto)), cv2.COLOR_BGR2RGB)
                img = ImageTk.PhotoImage(Image.fromarray(rgb))
                self.video.configure(image=img)
                self.video.image = img  # evita que Tk libere la imagen
            else:
                self.fallos += 1  # una cámara USB puede perder algún frame suelto sin estar desconectada
                if self.fallos >= FALLOS_MAX:
                    nombre = camaras.nombre_corto(self.cam) if self.cam else "La cámara"
                    self.cerrar_camara()
                    self.auto_buscar = True
                    self.mensaje("error", f"{nombre} dejó de enviar imagen (¿se desconectó?).\nBuscando cámaras...")
                    self.buscar_camaras()
        self.vigilar()
        self.root.after(30, self.bucle)

    # ---------- Lógica de registro ----------
    def procesar(self, texto):
        ahora = time.time()
        if texto == self.ultimo[0] and ahora - self.ultimo[1] < COOLDOWN:
            self.ultimo = (texto, ahora)  # el QR sigue a la vista: renueva el anti-rebote (así no cuenta como 2.º escaneo)
            return
        self.ultimo = (texto, ahora)
        qr = parse_qr(texto)
        if not qr:
            self.mensaje("error", "QR vacío o ilegible."); self.pitido(False); return
        r = db.registrar(qr["matricula"])
        a, estado = r["alumno"], r["estado"]
        if estado == "entrada":
            self.mensaje("ok", f"{a['nombre']}\n{a['matricula']}\nENTRADA registrada a las {r['hora']}")
            self.pitido(True); self.refrescar()
        elif estado == "salida":
            self.mensaje("salida", f"{a['nombre']}\n{a['matricula']}\nSALIDA registrada a las {r['hora']}\n(entrada: {r['entrada']})")
            self.pitido(True); self.refrescar()
        elif estado == "espera":
            self.mensaje("duplicado", f"{a['nombre']}\nEntrada registrada a las {r['entrada']}.\n"
                                      f"Podrás registrar la salida en {r['faltan']} s.")
            self.pitido(False)
        elif estado == "completo":
            self.mensaje("duplicado", f"{a['nombre']}\nYa registró hoy entrada ({r['entrada']}) y salida ({r['salida']}).")
            self.pitido(False)
        else:
            codigo = qr["matricula"] if len(qr["matricula"]) <= 40 else qr["matricula"][:37] + "..."
            self.mensaje("error", f"El código {codigo} no está registrado.\nAgrégalo en qr_config.py.")
            self.pitido(False)

    # ---------- Panel ----------
    def refrescar(self):
        self.tabla.delete(*self.tabla.get_children())
        filas = db.asistencias(self.fecha.get().strip())
        for r in filas:
            self.tabla.insert("", "end", values=(r["matricula"], r["nombre"], r["hora"], r["hora_salida"] or "—"))
        con_salida = sum(1 for r in filas if r["hora_salida"])
        self.total.config(text=f"{len(filas)} con entrada · {con_salida} con salida")

    def exportar(self):
        f = self.fecha.get().strip()
        ruta = filedialog.asksaveasfilename(defaultextension=".csv", initialfile=f"asistencia-{f}.csv",
                                            filetypes=[("CSV (Excel)", "*.csv")])
        if ruta:
            n = db.exportar_csv(f, ruta)
            messagebox.showinfo("Exportado", f"{n} registro(s) guardados en:\n{ruta}")

    def agregar_alumno(self):
        mat = simpledialog.askstring("Nuevo alumno", "Matrícula:", parent=self.root)
        nom = mat and simpledialog.askstring("Nuevo alumno", "Nombre completo:", parent=self.root)
        if mat and nom:
            if db.agregar_alumno(mat, nom):
                messagebox.showinfo("Listo", "Alumno agregado. Ejecuta generar_qr.py para crear su QR.")
            else:
                messagebox.showerror("Error", "Esa matrícula ya existe.")

    # ---------- Utilidades ----------
    def mensaje(self, tipo, texto):
        self.estado.config(text=texto, bg=COLORES[tipo])

    def pitido(self, exito):
        try:
            import winsound
            winsound.Beep(880 if exito else 300, 150)
        except ImportError:
            self.root.bell()

    def cerrar(self):
        self.gen += 1  # cualquier apertura pendiente se descarta
        self.cerrar_camara()
        self.root.destroy()


if __name__ == "__main__":
    raiz = tk.Tk()
    App(raiz)
    raiz.mainloop()

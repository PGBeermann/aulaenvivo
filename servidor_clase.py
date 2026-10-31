#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Clase en Vivo UNACHI — orquestador del aula.

Funciones:
  1. Descarga (una sola vez) MediaMTX para el sistema operativo del profesor.
  2. Inicia MediaMTX con ./mediamtx.yml.
  3. Sirve las páginas web del aula (profesor y estudiantes) en el puerto 8080.
  4. Expone /config.js (IP de la LAN, puertos) y /api/estado (espectadores).
  5. Abre el panel del profesor en el navegador y detiene todo con Ctrl+C.

Sólo usa la biblioteca estándar de Python 3.8+.
Uso:  python servidor_clase.py [--ip 192.168.1.50] [--puerto-web 8080]
                               [--sin-navegador] [--sin-mediamtx]
"""
from __future__ import annotations

import argparse
import http.server
import io
import json
import os
import platform
import shutil
import signal
import socket
import socketserver
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser
import zipfile
from pathlib import Path

MEDIAMTX_VERSION = "v1.21.1"
RUTA_STREAM = "clase"
PUERTO_WEBRTC = 8889
PUERTO_ICE = 8189
API_MEDIAMTX = "http://127.0.0.1:9997"

BASE = Path(__file__).resolve().parent
DIR_WEB = BASE / "web"
DIR_BIN = BASE / "mediamtx"
CONFIG_MTX = BASE / "mediamtx.yml"

ES_WINDOWS = os.name == "nt"
NOMBRE_BIN = "mediamtx.exe" if ES_WINDOWS else "mediamtx"


def log(msg: str) -> None:
    print(f"[clase] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Red
# ---------------------------------------------------------------------------
def ip_principal() -> str:
    """IP de la interfaz con ruta por defecto (no envía tráfico real)."""
    for destino in ("10.255.255.255", "192.168.255.255", "8.8.8.8"):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((destino, 1))
            ip = s.getsockname()[0]
            if not ip.startswith("127."):
                return ip
        except OSError:
            pass
        finally:
            s.close()
    return "127.0.0.1"


def ips_locales() -> list[str]:
    """Todas las IPv4 privadas conocidas del equipo (la principal primero)."""
    ips = [ip_principal()]
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except socket.gaierror:
        pass
    privadas = [ip for ip in ips if ip.startswith(("10.", "192.168.")) or
                (ip.startswith("172.") and 16 <= int(ip.split(".")[1]) <= 31)]
    resto = [ip for ip in ips if ip not in privadas and ip != "127.0.0.1"]
    return privadas + resto or ["127.0.0.1"]


def puerto_libre(puerto: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", puerto))
            return True
        except OSError:
            return False


# ---------------------------------------------------------------------------
# MediaMTX
# ---------------------------------------------------------------------------
def nombre_paquete() -> str:
    sistema = platform.system().lower()
    maquina = platform.machine().lower()
    if sistema == "windows":
        return f"mediamtx_{MEDIAMTX_VERSION}_windows_amd64.zip"
    if sistema == "darwin":
        arq = "arm64" if maquina in ("arm64", "aarch64") else "amd64"
        return f"mediamtx_{MEDIAMTX_VERSION}_darwin_{arq}.tar.gz"
    if sistema == "linux":
        arq = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64",
               "arm64": "arm64", "armv7l": "armv7", "armv6l": "armv6"}.get(maquina)
        if arq:
            return f"mediamtx_{MEDIAMTX_VERSION}_linux_{arq}.tar.gz"
    raise RuntimeError(f"Plataforma no soportada: {sistema}/{maquina}")


def asegurar_mediamtx() -> Path:
    binario = DIR_BIN / NOMBRE_BIN
    if binario.exists():
        return binario
    en_path = shutil.which("mediamtx")
    if en_path:
        log(f"Usando MediaMTX del sistema: {en_path} (se recomienda {MEDIAMTX_VERSION})")
        return Path(en_path)

    paquete = nombre_paquete()
    url = (f"https://github.com/bluenviron/mediamtx/releases/download/"
           f"{MEDIAMTX_VERSION}/{paquete}")
    log(f"Descargando MediaMTX {MEDIAMTX_VERSION} (sólo la primera vez)...")
    log(f"  {url}")
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            datos = r.read()
    except (urllib.error.URLError, TimeoutError) as e:
        raise RuntimeError(
            f"No se pudo descargar MediaMTX ({e}).\n"
            f"  Descárguelo manualmente desde {url}\n"
            f"  y copie '{NOMBRE_BIN}' dentro de la carpeta: {DIR_BIN}") from e

    DIR_BIN.mkdir(exist_ok=True)
    if paquete.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(datos)) as z:
            z.extract(NOMBRE_BIN, DIR_BIN)
            if "LICENSE" in z.namelist():
                z.extract("LICENSE", DIR_BIN)
    else:
        with tarfile.open(fileobj=io.BytesIO(datos), mode="r:gz") as t:
            for nombre in (NOMBRE_BIN, "LICENSE"):
                try:
                    miembro = t.getmember(nombre)
                except KeyError:
                    continue
                with t.extractfile(miembro) as src, open(DIR_BIN / nombre, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        binario.chmod(0o755)
    log(f"MediaMTX instalado en {binario}")
    return binario


def iniciar_mediamtx(binario: Path) -> subprocess.Popen:
    for puerto in (PUERTO_WEBRTC, 9997):
        if not puerto_libre(puerto):
            raise RuntimeError(
                f"El puerto {puerto} ya está en uso: ¿hay otra instancia de "
                f"MediaMTX abierta? Ciérrela e intente de nuevo.")
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if ES_WINDOWS else 0
    proc = subprocess.Popen([str(binario), str(CONFIG_MTX)], cwd=str(BASE),
                            creationflags=flags)
    # Esperar a que la API responda
    for _ in range(50):
        if proc.poll() is not None:
            raise RuntimeError("MediaMTX terminó al iniciar; revise los mensajes anteriores.")
        try:
            urllib.request.urlopen(f"{API_MEDIAMTX}/v3/paths/list", timeout=1).read()
            return proc
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
            time.sleep(0.2)
    log("Advertencia: la API de MediaMTX aún no responde; se continúa.")
    return proc


def estado_stream() -> dict:
    try:
        with urllib.request.urlopen(
                f"{API_MEDIAMTX}/v3/paths/get/{RUTA_STREAM}", timeout=2) as r:
            d = json.load(r)
        return {
            "servidor": True,
            "enVivo": bool(d.get("online", d.get("ready", False))),
            "espectadores": len(d.get("readers") or []),
            "bytesEntrada": d.get("inboundBytes", d.get("bytesReceived", 0)),
            "fuente": (d.get("source") or {}).get("type"),
        }
    except urllib.error.HTTPError as e:
        # 404 = la ruta existe en la config pero nadie publica todavía
        return {"servidor": True, "enVivo": False, "espectadores": 0,
                "bytesEntrada": 0, "fuente": None, "codigo": e.code}
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
        return {"servidor": False, "enVivo": False, "espectadores": 0,
                "bytesEntrada": 0, "fuente": None}


# ---------------------------------------------------------------------------
# Servidor web
# ---------------------------------------------------------------------------
class ManejadorAula(http.server.SimpleHTTPRequestHandler):
    ips: list[str] = []
    puerto_web: int = 8080

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(DIR_WEB), **kw)

    def es_local(self) -> bool:
        return self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def responder(self, cuerpo: bytes, tipo: str, codigo: int = 200):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        ruta = self.path.split("?", 1)[0]
        if ruta == "/config.js":
            cfg = {"ips": self.ips, "ip": self.ips[0], "puertoWeb": self.puerto_web,
                   "puertoWebrtc": PUERTO_WEBRTC, "ruta": RUTA_STREAM,
                   "version": MEDIAMTX_VERSION}
            js = "window.CLASE = " + json.dumps(cfg) + ";\n"
            return self.responder(js.encode(), "application/javascript; charset=utf-8")
        if ruta == "/api/estado":
            if not self.es_local():
                return self.responder(b'{"error":"solo profesor"}', "application/json", 403)
            return self.responder(json.dumps(estado_stream()).encode(), "application/json")
        if ruta in ("/profesor", "/profesor.html") and not self.es_local():
            # El panel del profesor sólo se abre desde el propio equipo.
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
            return
        return super().do_GET()

    def log_message(self, fmt, *args):
        if os.environ.get("CLASE_DEBUG"):
            super().log_message(fmt, *args)


class ServidorHilos(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Clase en Vivo UNACHI")
    ap.add_argument("--ip", help="IP de la LAN a mostrar a los estudiantes")
    ap.add_argument("--puerto-web", type=int, default=8080)
    ap.add_argument("--sin-navegador", action="store_true")
    ap.add_argument("--sin-mediamtx", action="store_true",
                    help="no iniciar MediaMTX (ya se ejecuta aparte)")
    args = ap.parse_args()

    ips = ips_locales()
    if args.ip:
        ips = [args.ip] + [i for i in ips if i != args.ip]
    ManejadorAula.ips = ips
    ManejadorAula.puerto_web = args.puerto_web

    proc = None
    try:
        if not args.sin_mediamtx:
            proc = iniciar_mediamtx(asegurar_mediamtx())
        if not puerto_libre(args.puerto_web):
            raise RuntimeError(f"El puerto web {args.puerto_web} está ocupado; "
                               f"use --puerto-web 8081")
        httpd = ServidorHilos(("0.0.0.0", args.puerto_web), ManejadorAula)
    except RuntimeError as e:
        log(f"ERROR: {e}")
        if proc:
            proc.terminate()
        return 1

    url_prof = f"http://localhost:{args.puerto_web}/profesor.html"
    url_est = f"http://{ips[0]}:{args.puerto_web}/"
    print("\n" + "=" * 64)
    print("  CLASE EN VIVO — UNACHI")
    print(f"  Panel del profesor : {url_prof}")
    print(f"  Enlace estudiantes : {url_est}")
    if len(ips) > 1:
        print(f"  Otras IP del equipo: {', '.join(ips[1:])}")
    print("  Detener            : Ctrl+C")
    print("=" * 64 + "\n", flush=True)

    hilo = threading.Thread(target=httpd.serve_forever, daemon=True)
    hilo.start()
    if not args.sin_navegador:
        threading.Timer(1.0, lambda: webbrowser.open(url_prof)).start()

    detener = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: detener.set())
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: detener.set())
    try:
        while not detener.is_set():
            if proc and proc.poll() is not None:
                log("MediaMTX se detuvo inesperadamente.")
                break
            detener.wait(1)
    finally:
        log("Cerrando...")
        httpd.shutdown()
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())

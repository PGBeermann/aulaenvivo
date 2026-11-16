#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Clase en Vivo UNACHI — orquestador del aula.

Dos modos de funcionamiento:

  LOCAL (predeterminado): el profesor ejecuta el programa en su equipo y los
  estudiantes ven la clase en la misma red Wi-Fi.

  ONLINE (--online, pensado para un VPS con Docker/Dokploy): el programa corre
  en un servidor con dominio y HTTPS; el profesor entra con contraseña desde
  cualquier lugar y los estudiantes ven la clase desde sus casas.

Funciones:
  1. Descarga (una sola vez) MediaMTX para el sistema operativo.
  2. Inicia MediaMTX con ./mediamtx.yml.
  3. Sirve las páginas web del aula (profesor y estudiantes).
  4. Hace de intermediario (proxy) hacia MediaMTX para WHIP/WHEP, de modo que
     todo pasa por un único puerto HTTP (y por HTTPS detrás de Traefik).
  5. Controla quién puede transmitir (profesor) y quién puede ver (estudiantes).

Sólo usa la biblioteca estándar de Python 3.8+.

Uso local : python servidor_clase.py [--ip 192.168.1.50] [--puerto-web 8080]
                                     [--sin-navegador] [--sin-mediamtx]
Uso online: PROFESOR_CLAVE=... python servidor_clase.py --online

Variables de entorno (modo online):
  PROFESOR_CLAVE     Contraseña del panel del profesor (obligatoria, ≥ 8 caracteres).
  CLAVE_ESTUDIANTES  Código que deben escribir los estudiantes (opcional; vacío = acceso libre).
  IP_PUBLICA         IP pública del VPS que se anuncia a los navegadores (recomendada;
                     si falta se detecta automáticamente).
  URL_PUBLICA        URL que aparece en el QR, p. ej. https://clase.midominio.com/
                     (opcional; si falta se deduce del dominio con que se abre el panel).
  PUERTO             Puerto HTTP interno (predeterminado 8080).
  PUERTO_MEDIOS      Puerto UDP/TCP de los medios WebRTC (predeterminado 8189). Debe
                     publicarse en el VPS con el MISMO número.
  SESION_SECRETO     Clave para firmar las sesiones (opcional; si falta, las sesiones
                     se invalidan al reiniciar el contenedor).
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import http.client
import http.cookies
import http.server
import io
import ipaddress
import json
import os
import platform
import queue
import re
import secrets
import shutil
import signal
import socket
import socketserver
import subprocess
import sys
import tarfile
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import zipfile
from collections import deque
from pathlib import Path

# Versión del programa: visible en /version y en el registro al iniciar.
VERSION = "2.0.0"
FUNCIONES = ["chat", "expresiones", "mano", "palabra", "grabacion"]
MEDIAMTX_VERSION = "v1.21.1"
RUTA_STREAM = "clase"
RUTA_VOZ = "voz"          # micrófono del estudiante que tiene la palabra
# Puertos internos de MediaMTX (sólo 127.0.0.1); normalmente no hace falta cambiarlos.
PUERTO_WEBRTC = int(os.environ.get("PUERTO_WHIP_INTERNO") or 8889)  # señalización WHIP/WHEP
PUERTO_API = int(os.environ.get("PUERTO_API_INTERNO") or 9997)
PUERTO_ICE = int(os.environ.get("PUERTO_MEDIOS") or 8189)
API_MEDIAMTX = f"http://127.0.0.1:{PUERTO_API}"

BASE = Path(__file__).resolve().parent
DIR_WEB = BASE / "web"
DIR_BIN = BASE / "mediamtx"
CONFIG_MTX = BASE / "mediamtx.yml"
DIR_GRABACIONES = Path(os.environ.get("DIR_GRABACIONES") or (BASE / "grabaciones")).resolve()

ES_WINDOWS = os.name == "nt"
NOMBRE_BIN = "mediamtx.exe" if ES_WINDOWS else "mediamtx"

HORAS_SESION = 12
MAX_CUERPO = 1_000_000  # 1 MB: una oferta SDP ocupa unos pocos KB


def log(msg: str) -> None:
    print(f"[clase] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Configuración global (se completa en main)
# ---------------------------------------------------------------------------
class Config:
    online = False
    clave_profesor = ""
    clave_estudiantes = ""
    url_publica = ""
    ip_publica = ""
    ips: list[str] = []
    puerto_web = 8080
    secreto = b""


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


def detectar_ip_publica() -> str:
    """Pregunta a servicios públicos cuál es la IP de salida del servidor."""
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip", "https://icanhazip.com"):
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                ip = r.read().decode().strip()
            ipaddress.ip_address(ip)
            return ip
        except (OSError, ValueError):
            continue
    return ""


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


def entorno_mediamtx() -> dict:
    """Variables MTX_* que ajustan mediamtx.yml al modo de funcionamiento."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("PROFESOR_CLAVE", "CLAVE_ESTUDIANTES", "SESION_SECRETO")}
    env["MTX_WEBRTCADDRESS"] = f"127.0.0.1:{PUERTO_WEBRTC}"
    env["MTX_APIADDRESS"] = f"127.0.0.1:{PUERTO_API}"
    env["MTX_WEBRTCLOCALUDPADDRESS"] = f":{PUERTO_ICE}"
    env["MTX_WEBRTCLOCALTCPADDRESS"] = f":{PUERTO_ICE}"
    if Config.online:
        # Grabaciones en el VPS: se borran solas a los 30 días (en el aula, nunca).
        env.setdefault("MTX_PATHDEFAULTS_RECORDDELETEAFTER", "720h")
        # En Docker las interfaces sólo tienen IP internas: se anuncia la IP pública.
        env["MTX_WEBRTCIPSFROMINTERFACES"] = "no"
        env["MTX_WEBRTCADDITIONALHOSTS"] = Config.ip_publica
        # RTMP sólo sirve para OBS en el mismo equipo: no tiene sentido en el VPS.
        env["MTX_RTMP"] = "no"
    return env


def iniciar_mediamtx(binario: Path) -> subprocess.Popen:
    for puerto in (PUERTO_WEBRTC, PUERTO_API):
        if not puerto_libre(puerto):
            raise RuntimeError(
                f"El puerto {puerto} ya está en uso: ¿hay otra instancia de "
                f"MediaMTX abierta? Ciérrela e intente de nuevo.")
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if ES_WINDOWS else 0
    proc = subprocess.Popen([str(binario), str(CONFIG_MTX)], cwd=str(BASE),
                            creationflags=flags, env=entorno_mediamtx())
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
# Sesiones (cookies firmadas con HMAC) y límite de intentos de acceso
# ---------------------------------------------------------------------------
COOKIE = {"profesor": "clase_prof", "estudiante": "clase_est"}


def firmar(rol: str) -> str:
    exp = int(time.time() + HORAS_SESION * 3600)
    msg = f"{rol}.{exp}"
    firma = hmac.new(Config.secreto, msg.encode(), hashlib.sha256).hexdigest()
    return f"{msg}.{firma}"


def token_valido(token: str, rol: str) -> bool:
    partes = token.split(".")
    if len(partes) != 3 or partes[0] != rol or not partes[1].isdigit():
        return False
    esperado = hmac.new(Config.secreto, f"{partes[0]}.{partes[1]}".encode(),
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, partes[2]) and int(partes[1]) > time.time()


class Intentos:
    """Bloquea 5 minutos una IP tras 8 contraseñas incorrectas seguidas."""
    _datos: dict[str, list] = {}
    _lock = threading.Lock()
    MAX, BLOQUEO = 8, 300

    @classmethod
    def bloqueado(cls, ip: str) -> bool:
        with cls._lock:
            fallos, hasta = cls._datos.get(ip, [0, 0])
            return hasta > time.time()

    @classmethod
    def registrar(cls, ip: str, ok: bool) -> None:
        with cls._lock:
            if ok:
                cls._datos.pop(ip, None)
                return
            fallos, _ = cls._datos.get(ip, [0, 0])
            fallos += 1
            hasta = time.time() + cls.BLOQUEO if fallos >= cls.MAX else 0
            cls._datos[ip] = [0 if hasta else fallos, hasta]
            if len(cls._datos) > 10_000:  # evita crecer sin límite
                cls._datos.clear()


# ---------------------------------------------------------------------------
# Sala: chat, expresiones, turno de palabra y grabación
# ---------------------------------------------------------------------------
REACCIONES = {"👍", "👏", "😂", "😮", "❤️", "🤔", "🐢", "🔁"}
ID_VALIDO = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
NOMBRE_GRAB = re.compile(r"^[A-Za-z0-9_.-]{1,80}\.mp4$")


def limpiar_texto(texto, maximo: int) -> str:
    """Texto plano de una línea o varias, sin caracteres de control."""
    texto = str(texto or "")[:maximo * 2]
    texto = "".join(c for c in texto if c in "\n\t" or unicodedata.category(c)[0] != "C")
    return texto.strip()[:maximo]


def api_mediamtx(metodo: str, ruta: str, cuerpo: dict | None = None, timeout: float = 3):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(API_MEDIAMTX + ruta, data=datos, method=metodo,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        cuerpo_r = r.read()
    return json.loads(cuerpo_r) if cuerpo_r else {}


class Sala:
    """Estado compartido de la clase. Los navegadores lo reciben por
    Server-Sent Events (/eventos) y actúan con POST /api/accion."""

    MAX_MENSAJES = 2000      # se guardan en memoria (para exportar el chat)
    MENSAJES_INICIALES = 200 # los que recibe quien se conecta

    def __init__(self, dir_grabaciones: Path):
        self.cerrojo = threading.RLock()
        self.participantes: dict[str, dict] = {}   # cid -> datos del estudiante
        self.colas: dict[str, set] = {}            # cid -> colas SSE abiertas
        self.colas_prof: set = set()
        self.mensajes: deque = deque(maxlen=self.MAX_MENSAJES)
        self.seq = 0
        self.chat_activo = True
        self.hablante: dict | None = None          # {cid, nombre, token, desde}
        self.grabando = False
        self.grab_desde: float | None = None
        self.dir_grab = dir_grabaciones
        self._limites: dict[tuple, list[float]] = {}

    # ---------------- utilidades ----------------
    def _id(self) -> int:
        self.seq += 1
        return self.seq

    def permitido(self, cid: str, accion: str, maximo: int, ventana: float) -> bool:
        ahora = time.time()
        with self.cerrojo:
            marcas = [t for t in self._limites.get((cid, accion), []) if ahora - t < ventana]
            if len(marcas) >= maximo:
                self._limites[(cid, accion)] = marcas
                return False
            marcas.append(ahora)
            self._limites[(cid, accion)] = marcas
            return True

    @staticmethod
    def _poner(cola: queue.Queue, evento: dict) -> None:
        try:
            cola.put_nowait(evento)
        except queue.Full:
            pass   # cliente demasiado lento: el bucle SSE lo desconectará

    def a_todos(self, evento: dict) -> None:
        with self.cerrojo:
            for colas in self.colas.values():
                for c in colas:
                    self._poner(c, evento)
            for c in self.colas_prof:
                self._poner(c, evento)

    def a_profesor(self, evento: dict) -> None:
        with self.cerrojo:
            for c in self.colas_prof:
                self._poner(c, evento)

    def a_estudiante(self, cid: str, evento: dict) -> None:
        with self.cerrojo:
            for c in self.colas.get(cid, ()):
                self._poner(c, evento)

    def _publico_hablante(self):
        h = self.hablante
        return {"id": h["cid"], "nombre": h["nombre"], "desde": h["desde"]} if h else None

    def lista_participantes(self) -> list[dict]:
        with self.cerrojo:
            return sorted(
                ({"id": cid, "nombre": p["nombre"], "mano": p["mano"], "pide": p["pide"],
                  "desde": p["desde"], "pestanas": len(self.colas.get(cid, ()))}
                 for cid, p in self.participantes.items() if self.colas.get(cid)),
                key=lambda x: x["nombre"].lower())

    def _avisar_participantes(self) -> None:
        self.a_profesor({"tipo": "participantes", "lista": self.lista_participantes()})

    def instantanea(self, rol: str, cid: str | None = None) -> dict:
        with self.cerrojo:
            base = {"tipo": "estado", "chatActivo": self.chat_activo,
                    "mensajes": list(self.mensajes)[-self.MENSAJES_INICIALES:],
                    "hablante": self._publico_hablante(), "grabando": self.grabando,
                    "grabDesde": self.grab_desde, "ahora": time.time()}
            if rol == "prof":
                base["participantes"] = self.lista_participantes()
            else:
                p = self.participantes.get(cid, {})
                base["yo"] = {"id": cid, "nombre": p.get("nombre"),
                              "mano": bool(p.get("mano")), "pide": bool(p.get("pide"))}
                if self.hablante and self.hablante["cid"] == cid:
                    base["tuPalabra"] = self.hablante["token"]
            return base

    # ---------------- conexiones SSE ----------------
    def conectar(self, rol: str, cid: str | None, nombre: str | None) -> queue.Queue:
        cola: queue.Queue = queue.Queue(maxsize=400)
        with self.cerrojo:
            if rol == "prof":
                self.colas_prof.add(cola)
            else:
                p = self.participantes.setdefault(
                    cid, {"nombre": nombre, "mano": None, "pide": None, "desde": time.time()})
                p["nombre"] = nombre
                self.colas.setdefault(cid, set()).add(cola)
            cola.put_nowait(self.instantanea(rol, cid))
        if rol != "prof":
            self._avisar_participantes()
        return cola

    def desconectar(self, rol: str, cid: str | None, cola: queue.Queue) -> None:
        se_fue = False
        with self.cerrojo:
            if rol == "prof":
                self.colas_prof.discard(cola)
                return
            colas = self.colas.get(cid)
            if colas is not None:
                colas.discard(cola)
                if not colas:
                    del self.colas[cid]
                    se_fue = True
        if se_fue:
            # Si quien tenía la palabra cierra la página, se libera el turno.
            if self.hablante and self.hablante["cid"] == cid:
                self.quitar_palabra(motivo="salio")
            self._avisar_participantes()

    # ---------------- chat y expresiones ----------------
    def publicar_mensaje(self, de: str, nombre: str, rol: str, texto: str) -> dict:
        with self.cerrojo:
            m = {"id": self._id(), "de": de, "nombre": nombre, "rol": rol,
                 "texto": texto, "t": time.time()}
            self.mensajes.append(m)
        self.a_todos({"tipo": "msg", "m": m})
        return m

    def aviso(self, texto: str) -> None:
        self.publicar_mensaje("sistema", "Aviso", "sistema", texto)

    def borrar_mensaje(self, mid: int) -> None:
        with self.cerrojo:
            for m in self.mensajes:
                if m["id"] == mid:
                    m["texto"], m["borrado"] = "", True
                    break
            else:
                return
        self.a_todos({"tipo": "borrado", "id": mid})

    def poner_mano(self, cid: str, on: bool, por_profesor: bool = False) -> None:
        with self.cerrojo:
            p = self.participantes.get(cid)
            if not p:
                return
            p["mano"] = time.time() if on else None
        self.a_estudiante(cid, {"tipo": "yo", "mano": on})
        self._avisar_participantes()
        if on:
            self.a_profesor({"tipo": "alerta", "clase": "mano", "nombre": p["nombre"]})

    def pedir_palabra(self, cid: str, on: bool) -> None:
        with self.cerrojo:
            p = self.participantes.get(cid)
            if not p:
                return
            p["pide"] = time.time() if on else None
        self.a_estudiante(cid, {"tipo": "yo", "pide": on})
        self._avisar_participantes()
        if on:
            self.a_profesor({"tipo": "alerta", "clase": "palabra", "nombre": p["nombre"]})

    # ---------------- turno de palabra ----------------
    def dar_palabra(self, cid: str) -> bool:
        with self.cerrojo:
            p = self.participantes.get(cid)
            if not p or not self.colas.get(cid):
                return False
            anterior = self.hablante
        if anterior:
            self.quitar_palabra(motivo="otro")
        with self.cerrojo:
            p["pide"] = None
            p["mano"] = None
            self.hablante = {"cid": cid, "nombre": p["nombre"],
                             "token": secrets.token_urlsafe(24), "desde": time.time()}
            token = self.hablante["token"]
        self.a_estudiante(cid, {"tipo": "tuPalabra", "token": token})
        self.a_estudiante(cid, {"tipo": "yo", "mano": False, "pide": False})
        self.a_todos({"tipo": "hablante", "h": self._publico_hablante()})
        self._avisar_participantes()
        return True

    def quitar_palabra(self, motivo: str = "profesor") -> None:
        with self.cerrojo:
            h = self.hablante
            self.hablante = None
        if not h:
            return
        self.a_estudiante(h["cid"], {"tipo": "finPalabra", "motivo": motivo})
        self.a_todos({"tipo": "hablante", "h": None})
        # Corta también la sesión WebRTC en MediaMTX aunque el navegador no colabore.
        # Es síncrono: así no puede cerrar por error la sesión del siguiente turno.
        expulsar_voz()

    def token_voz_valido(self, token: str) -> bool:
        with self.cerrojo:
            h = self.hablante
        return bool(h and token) and hmac.compare_digest(token.encode(), h["token"].encode())

    # ---------------- grabación (MediaMTX graba la ruta "clase") ----------------
    def grabar(self, on: bool) -> str | None:
        """Activa o desactiva la grabación sin interrumpir la transmisión."""
        cuerpo = {"record": on}
        if on:
            # MediaMTX no puede guardar VP8 en MP4: grabaría sólo el audio.
            try:
                d = api_mediamtx("GET", f"/v3/paths/get/{RUTA_STREAM}")
                if any("VP8" in str(p).upper() for p in d.get("tracks") or []):
                    return ("La transmisión usa el códec VP8, que no se puede grabar. Detenga la "
                            "transmisión, elija H.264 (o VP9/AV1) y vuelva a compartir la pantalla.")
            except (urllib.error.URLError, OSError, ValueError):
                pass   # aún no se transmite: se grabará en cuanto empiece
            (self.dir_grab / RUTA_STREAM).mkdir(parents=True, exist_ok=True)
            # Barras «/» también en Windows (MediaMTX/Go las acepta y evita escapes).
            cuerpo["recordPath"] = (self.dir_grab / "%path" / "clase_%Y-%m-%d_%H-%M-%S").as_posix()
        try:
            api_mediamtx("PATCH", f"/v3/config/paths/patch/{RUTA_STREAM}", cuerpo)
        except (urllib.error.URLError, OSError, ValueError) as e:
            return f"MediaMTX no aceptó el cambio: {e}"
        with self.cerrojo:
            self.grabando = on
            self.grab_desde = time.time() if on else None
        self.a_todos({"tipo": "grabando", "on": on, "desde": self.grab_desde, "ahora": time.time()})
        self.aviso("La clase se está grabando." if on else "La grabación terminó.")
        return None

    def lista_grabaciones(self) -> list[dict]:
        carpeta = self.dir_grab / RUTA_STREAM
        if not carpeta.is_dir():
            return []
        ahora = time.time()
        out = []
        for f in carpeta.glob("*.mp4"):
            st = f.stat()
            out.append({"nombre": f.name, "bytes": st.st_size, "modificado": st.st_mtime,
                        "enCurso": self.grabando and ahora - st.st_mtime < 5})
        return sorted(out, key=lambda x: x["nombre"], reverse=True)

    def exportar_chat(self) -> str:
        with self.cerrojo:
            mensajes = list(self.mensajes)
        lineas = ["Clase en Vivo UNACHI — registro del chat",
                  f"Exportado: {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
        for m in mensajes:
            if m.get("borrado"):
                continue
            hora = time.strftime("%H:%M:%S", time.localtime(m["t"]))
            quien = {"prof": "Profesor", "sistema": "[aviso]"}.get(m["rol"], m["nombre"])
            lineas.append(f"[{hora}] {quien}: {m['texto']}")
        return "\n".join(lineas) + "\n"


def expulsar_voz() -> None:
    """Cierra en MediaMTX cualquier sesión WebRTC que publique en la ruta de voz."""
    try:
        sesiones = api_mediamtx("GET", "/v3/webrtcsessions/list").get("items") or []
        for s in sesiones:
            if s.get("path") == RUTA_VOZ and s.get("state") == "publish":
                api_mediamtx("POST", f"/v3/webrtcsessions/kick/{s['id']}")
    except (urllib.error.URLError, OSError, ValueError):
        pass


SALA: Sala | None = None


# ---------------------------------------------------------------------------
# Servidor web
# ---------------------------------------------------------------------------
# Rutas de MediaMTX que se reenvían; cualquier otra se rechaza.
RE_WHIP = re.compile(rf"^/{RUTA_STREAM}/whip(/[A-Za-z0-9-]+)?$")
RE_WHEP = re.compile(rf"^/{RUTA_STREAM}/whep(/[A-Za-z0-9-]+)?$")
JS_MEDIAMTX = {f"/{RUTA_STREAM}/reader.js", f"/{RUTA_STREAM}/publisher.js"}
CABECERAS_SALTO = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
                   "te", "trailers", "transfer-encoding", "upgrade", "host",
                   "content-length", "cookie", "authorization", "x-voz-token"}
# Voz del estudiante con la palabra: publica quien tiene el token del turno; escucha el profesor.
RE_VOZ_WHIP = re.compile(rf"^/{RUTA_VOZ}/whip(/[A-Za-z0-9-]+)?$")
RE_VOZ_WHEP = re.compile(rf"^/{RUTA_VOZ}/whep(/[A-Za-z0-9-]+)?$")
PREFIJOS_MEDIAMTX = (f"/{RUTA_STREAM}/", f"/{RUTA_VOZ}/")


class ManejadorAula(http.server.SimpleHTTPRequestHandler):
    server_version = "ClaseEnVivo"
    sys_version = ""

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(DIR_WEB), **kw)

    # ----- utilidades -----
    def ruta(self) -> str:
        return self.path.split("?", 1)[0]

    def ip_cliente(self) -> str:
        ip = self.client_address[0]
        if Config.online:
            # Detrás de Traefik: X-Real-Ip / último salto de X-Forwarded-For.
            real = self.headers.get("X-Real-Ip")
            xff = self.headers.get("X-Forwarded-For")
            if real:
                return real.strip()
            if xff:
                return xff.split(",")[-1].strip()
        return ip

    def es_local(self) -> bool:
        return self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")

    def cookies(self) -> http.cookies.SimpleCookie:
        c = http.cookies.SimpleCookie()
        try:
            c.load(self.headers.get("Cookie", ""))
        except http.cookies.CookieError:
            pass
        return c

    def tiene_sesion(self, rol: str) -> bool:
        m = self.cookies().get(COOKIE[rol])
        return bool(m and token_valido(m.value, rol))

    def es_profesor(self) -> bool:
        if not Config.online:
            return self.es_local()
        if self.tiene_sesion("profesor"):
            return True
        # OBS Studio (WHIP) envía la contraseña como «Bearer Token».
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return hmac.compare_digest(auth[7:].strip().encode(),
                                       Config.clave_profesor.encode())
        return False

    def es_estudiante(self) -> bool:
        if not Config.online or not Config.clave_estudiantes:
            return True
        return self.tiene_sesion("estudiante") or self.es_profesor()

    def es_https(self) -> bool:
        return self.headers.get("X-Forwarded-Proto", "").lower() == "https"

    def url_base(self) -> str:
        if Config.url_publica:
            return Config.url_publica
        if Config.online:
            host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "localhost"
            esquema = "https" if self.es_https() else "http"
            return f"{esquema}://{host.split(',')[0].strip()}/"
        return f"http://{Config.ips[0]}:{Config.puerto_web}/"

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        super().end_headers()

    def responder(self, cuerpo: bytes, tipo: str, codigo: int = 200, cabeceras=()):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        for k, v in cabeceras:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(cuerpo)

    def json(self, datos: dict, codigo: int = 200, cabeceras=()):
        self.responder(json.dumps(datos).encode(), "application/json; charset=utf-8",
                       codigo, cabeceras)

    def redirigir(self, destino: str):
        self.send_response(302)
        self.send_header("Location", destino)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def leer_cuerpo(self) -> bytes | None:
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            datos = b""
            while True:
                linea = self.rfile.readline(1024)
                n = int(linea.split(b";")[0].strip() or b"0", 16)
                if n == 0:
                    self.rfile.readline(1024)
                    return datos
                datos += self.rfile.read(n)
                self.rfile.readline(1024)
                if len(datos) > MAX_CUERPO:
                    raise ValueError("cuerpo demasiado grande")
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_CUERPO:
            raise ValueError("cuerpo demasiado grande")
        return self.rfile.read(n) if n else None

    def cookie_sesion(self, rol: str, valor: str, max_age: int) -> tuple[str, str]:
        atributos = f"Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}"
        if self.es_https():
            atributos += "; Secure"
        return ("Set-Cookie", f"{COOKIE[rol]}={valor}; {atributos}")

    # ----- proxy hacia MediaMTX -----
    def autorizar_mediamtx(self) -> int:
        """Devuelve 0 si se permite, o el código HTTP de rechazo."""
        ruta = self.ruta()
        if ruta in JS_MEDIAMTX and self.command in ("GET", "HEAD"):
            return 0
        if RE_WHIP.match(ruta):
            return 0 if self.es_profesor() else 401
        if RE_WHEP.match(ruta):
            return 0 if self.es_estudiante() else 401
        if RE_VOZ_WHIP.match(ruta):
            ok = self.es_profesor() or SALA.token_voz_valido(self.headers.get("X-Voz-Token", ""))
            return 0 if ok else 401
        if RE_VOZ_WHEP.match(ruta):
            return 0 if self.es_profesor() else 401
        return 404

    def proxy_mediamtx(self):
        rechazo = self.autorizar_mediamtx()
        if rechazo:
            return self.json({"error": "no autorizado" if rechazo == 401 else "no existe"},
                             rechazo)
        try:
            cuerpo = self.leer_cuerpo()
        except ValueError:
            return self.json({"error": "solicitud demasiado grande"}, 413)
        cab = {k: v for k, v in self.headers.items() if k.lower() not in CABECERAS_SALTO}
        if cuerpo is not None:
            cab["Content-Length"] = str(len(cuerpo))
        conn = http.client.HTTPConnection("127.0.0.1", PUERTO_WEBRTC, timeout=20)
        try:
            conn.request(self.command, self.path, body=cuerpo, headers=cab)
            r = conn.getresponse()
            datos = r.read()
        except OSError:
            return self.json({"error": "el servidor de medios no responde"}, 502)
        finally:
            conn.close()
        self.send_response(r.status)
        for k, v in r.getheaders():
            if k.lower() not in CABECERAS_SALTO and k.lower() != "cache-control":
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(datos)

    # ---------------- eventos en vivo (Server-Sent Events) ----------------
    def eventos(self, consulta: str):
        q = urllib.parse.parse_qs(consulta)
        if q.get("rol", [""])[0] == "prof":
            if not self.es_profesor():
                return self.responder(b'{"error":"solo profesor"}', "application/json", 403)
            rol, cid, nombre = "prof", None, None
        else:
            if not self.es_estudiante():
                return self.responder(b'{"error":"no autorizado"}', "application/json", 401)
            rol = "est"
            cid = q.get("id", [""])[0]
            nombre = limpiar_texto(q.get("n", [""])[0], 40)
            if not ID_VALIDO.match(cid) or not nombre:
                return self.responder(b'{"error":"falta id o nombre"}', "application/json", 400)
            if nombre.casefold() in ("profesor", "profesora", "aviso", "docente"):
                nombre += " (estudiante)"   # evita suplantar al profesor en el chat
            with SALA.cerrojo:
                demasiadas = len(SALA.colas.get(cid, ())) >= 5
            if demasiadas:   # pestañas abiertas por un mismo estudiante
                return self.responder(b'{"error":"demasiadas conexiones"}', "application/json", 429)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("X-Accel-Buffering", "no")   # sin búfer en proxies
        self.end_headers()
        cola = SALA.conectar(rol, cid, nombre)
        try:
            self.wfile.write(b"retry: 3000\n\n")
            while True:
                try:
                    # Ping cada 5 s: una página cerrada se detecta en ≤10 s y, si
                    # tenía la palabra, el turno se libera.
                    ev = cola.get(timeout=5)
                    datos = json.dumps(ev, ensure_ascii=False)
                    self.wfile.write(f"data: {datos}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")     # mantiene viva la conexión
                self.wfile.flush()
                if cola.full():
                    break   # cliente que no lee: se cierra y el navegador reconecta
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            SALA.desconectar(rol, cid, cola)
            self.close_connection = True

    # ---------------- acciones (chat, mano, palabra, grabación) ----------------
    def accion(self):
        if "application/json" not in self.headers.get("Content-Type", ""):
            return self.responder(b'{"error":"tipo"}', "application/json", 415)
        origen = self.headers.get("Origin")
        if origen and urllib.parse.urlsplit(origen).netloc != self.headers.get("Host", ""):
            return self.responder(b'{"error":"origen"}', "application/json", 403)
        try:
            d = json.loads(self.leer_cuerpo() or b"{}")
            assert isinstance(d, dict)
        except (ValueError, AssertionError):
            return self.responder(b'{"error":"json"}', "application/json", 400)
        tipo = str(d.get("tipo", ""))
        ok = lambda: self.responder(b'{"ok":true}', "application/json")
        mal = lambda t, c=400: self.responder(json.dumps({"error": t}).encode(), "application/json", c)

        if d.get("rol") == "prof":
            if not self.es_profesor():
                return mal("solo profesor", 403)
            if tipo == "chat":
                texto = limpiar_texto(d.get("texto"), 1000)
                if texto:
                    SALA.publicar_mensaje("prof", "Profesor", "prof", texto)
            elif tipo == "borrar":
                SALA.borrar_mensaje(int(d.get("id") or 0))
            elif tipo == "chatActivo":
                on = bool(d.get("on"))
                with SALA.cerrojo:
                    SALA.chat_activo = on
                SALA.a_todos({"tipo": "chatActivo", "on": on})
                SALA.aviso("El chat está abierto." if on else "El profesor cerró el chat por ahora.")
            elif tipo == "dar":
                if not SALA.dar_palabra(str(d.get("id", ""))):
                    return mal("el estudiante ya no está conectado", 409)
            elif tipo == "quitar":
                SALA.quitar_palabra()
            elif tipo == "reconectar":
                # El profesor cambió de ventana: sin este aviso los estudiantes
                # quedarían ~10 s en la sesión anterior hasta que MediaMTX la cierre.
                SALA.a_todos({"tipo": "reconectar"})
            elif tipo == "bajarMano":
                cid = d.get("id")
                with SALA.cerrojo:
                    objetivo = [cid] if cid else [c for c, p in SALA.participantes.items() if p["mano"]]
                for c in objetivo:
                    SALA.poner_mano(str(c), False)
            elif tipo == "rechazar":
                SALA.pedir_palabra(str(d.get("id", "")), False)
            elif tipo == "grabar":
                error = SALA.grabar(bool(d.get("on")))
                if error:
                    return mal(error, 502)
            else:
                return mal("acción desconocida")
            return ok()

        # ----- estudiante -----
        if not self.es_estudiante():
            return mal("no autorizado", 401)
        cid = str(d.get("id", ""))
        with SALA.cerrojo:
            p = SALA.participantes.get(cid)
            conectado = bool(SALA.colas.get(cid))
        if not p or not conectado:
            return mal("sin conexión de eventos", 409)
        if tipo == "chat":
            if not SALA.chat_activo:
                return mal("el chat está cerrado", 403)
            texto = limpiar_texto(d.get("texto"), 500)
            if not texto:
                return mal("vacío")
            if not SALA.permitido(cid, "chat", 5, 10):
                return mal("Demasiados mensajes seguidos; espere unos segundos.", 429)
            SALA.publicar_mensaje(cid, p["nombre"], "est", texto)
        elif tipo == "reaccion":
            emoji = str(d.get("emoji", ""))
            if emoji not in REACCIONES:
                return mal("expresión no válida")
            if not SALA.permitido(cid, "reaccion", 4, 4):
                return mal("Espere un momento.", 429)
            SALA.a_todos({"tipo": "reaccion", "emoji": emoji, "nombre": p["nombre"]})
        elif tipo in ("mano", "palabra"):
            if not SALA.permitido(cid, tipo, 8, 20):
                return mal("Espere un momento.", 429)
            (SALA.poner_mano if tipo == "mano" else SALA.pedir_palabra)(cid, bool(d.get("on")))
        elif tipo == "soltar":
            if SALA.hablante and SALA.hablante["cid"] == cid:
                SALA.quitar_palabra(motivo="estudiante")
        else:
            return mal("acción desconocida")
        return ok()

    # ---------------- grabaciones (sólo profesor) ----------------
    def enviar_grabacion(self, nombre: str):
        archivo = SALA.dir_grab / RUTA_STREAM / nombre
        if not NOMBRE_GRAB.match(nombre) or not archivo.is_file():
            return self.send_error(404)
        tam = archivo.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(tam))
        self.send_header("Content-Disposition", f'attachment; filename="{nombre}"')
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(archivo, "rb") as f:
            restante = tam   # el archivo en curso puede crecer: se envía lo anunciado
            while restante > 0:
                bloque = f.read(min(1 << 20, restante))
                if not bloque:
                    break
                self.wfile.write(bloque)
                restante -= len(bloque)

    # ----- configuración que leen las páginas -----
    def config_js(self):
        cfg = {"online": Config.online, "ruta": RUTA_STREAM, "version": MEDIAMTX_VERSION,
               "url": self.url_base(), "requiereCodigo": bool(Config.clave_estudiantes)}
        if not Config.online:
            cfg.update({"ips": Config.ips, "ip": Config.ips[0], "puertoWeb": Config.puerto_web})
        js = "window.CLASE = " + json.dumps(cfg) + ";\n"
        self.responder(js.encode(), "application/javascript; charset=utf-8")

    # ----- métodos HTTP -----
    def do_GET(self):
        ruta = self.ruta()
        consulta = self.path.partition("?")[2]
        if ruta.startswith(PREFIJOS_MEDIAMTX):
            return self.proxy_mediamtx()
        if ruta == "/config.js":
            return self.config_js()
        if ruta == "/version":
            return self.json({"version": VERSION, "funciones": FUNCIONES})
        if ruta == "/eventos":
            return self.eventos(consulta)
        if ruta in ("/api/grabaciones", "/api/chat.txt") or ruta.startswith("/grabaciones/"):
            if not self.es_profesor():
                return self.json({"error": "solo profesor"}, 401 if Config.online else 403)
            if ruta == "/api/grabaciones":
                return self.json({"grabando": SALA.grabando, "carpeta": str(SALA.dir_grab / RUTA_STREAM),
                                  "archivos": SALA.lista_grabaciones()})
            if ruta == "/api/chat.txt":
                nombre = time.strftime("chat_clase_%Y-%m-%d_%H-%M.txt")
                return self.responder(SALA.exportar_chat().encode("utf-8"), "text/plain; charset=utf-8", 200,
                                      [("Content-Disposition", f'attachment; filename="{nombre}"')])
            return self.enviar_grabacion(urllib.parse.unquote(ruta.split("/", 2)[2]))
        if ruta == "/salud":
            ok = estado_stream()["servidor"]
            return self.json({"ok": ok}, 200 if ok else 503)
        if ruta == "/api/estado":
            if not self.es_profesor():
                return self.json({"error": "solo profesor"}, 401 if Config.online else 403)
            datos = estado_stream()
            if Config.online:
                datos["codigoEstudiantes"] = Config.clave_estudiantes
            return self.json(datos)
        if ruta in ("/profesor", "/profesor.html"):
            if not self.es_profesor():
                # Online: pedir contraseña. Local: el panel sólo se abre desde el propio equipo.
                return self.redirigir("/acceso.html?rol=profesor" if Config.online else "/")
            self.path = "/profesor.html"
        elif ruta in ("/", "/index.html"):
            if not self.es_estudiante():
                return self.redirigir("/acceso.html?rol=estudiante")
        elif ruta == "/acceso.html" and not Config.online:
            return self.redirigir("/")
        return super().do_GET()

    def do_HEAD(self):
        if self.ruta().startswith(PREFIJOS_MEDIAMTX):
            return self.proxy_mediamtx()
        return super().do_HEAD()

    def do_POST(self):
        ruta = self.ruta()
        if ruta.startswith(PREFIJOS_MEDIAMTX):
            return self.proxy_mediamtx()
        if ruta == "/api/accion":
            return self.accion()
        if ruta == "/api/acceso" and Config.online:
            return self.acceso()
        if ruta == "/api/salir":
            return self.json({"ok": True}, cabeceras=[
                self.cookie_sesion("profesor", "", 0), self.cookie_sesion("estudiante", "", 0)])
        return self.json({"error": "no existe"}, 404)

    def do_PATCH(self):
        if self.ruta().startswith(PREFIJOS_MEDIAMTX):
            return self.proxy_mediamtx()
        return self.json({"error": "no existe"}, 404)

    do_OPTIONS = do_PATCH

    def do_DELETE(self):
        ruta = self.ruta()
        if ruta.startswith(PREFIJOS_MEDIAMTX):
            return self.proxy_mediamtx()
        if ruta.startswith("/api/grabaciones/"):
            if not self.es_profesor():
                return self.json({"error": "solo profesor"}, 401 if Config.online else 403)
            nombre = urllib.parse.unquote(ruta.rsplit("/", 1)[1])
            archivo = SALA.dir_grab / RUTA_STREAM / nombre
            if not NOMBRE_GRAB.match(nombre) or not archivo.is_file():
                return self.json({"error": "no existe"}, 404)
            archivo.unlink()
            log(f"Grabación eliminada: {nombre}")
            return self.json({"ok": True})
        return self.json({"error": "no existe"}, 404)

    def acceso(self):
        ip = self.ip_cliente()
        if Intentos.bloqueado(ip):
            return self.json({"error": "Demasiados intentos. Espere 5 minutos."}, 429)
        try:
            datos = json.loads(self.leer_cuerpo() or b"{}")
            rol = str(datos.get("rol", ""))
            clave = str(datos.get("clave", "")).strip()
        except (ValueError, AttributeError):
            return self.json({"error": "solicitud inválida"}, 400)
        if rol == "profesor":
            esperada, destino = Config.clave_profesor, "/profesor.html"
        elif rol == "estudiante":
            if not Config.clave_estudiantes:
                return self.json({"ok": True, "destino": "/"})
            esperada, destino = Config.clave_estudiantes, "/"
        else:
            return self.json({"error": "rol inválido"}, 400)
        if rol == "estudiante":  # el código de estudiantes no distingue mayúsculas
            clave, esperada = clave.lower(), esperada.lower()
        ok = bool(clave) and hmac.compare_digest(clave.encode(), esperada.encode())
        Intentos.registrar(ip, ok)
        if not ok:
            log(f"Acceso rechazado ({rol}) desde {ip}")
            return self.json({"error": "Contraseña incorrecta" if rol == "profesor"
                              else "Código incorrecto"}, 401)
        return self.json({"ok": True, "destino": destino},
                         cabeceras=[self.cookie_sesion(rol, firmar(rol), HORAS_SESION * 3600)])

    def list_directory(self, path):  # no mostrar el contenido de las carpetas
        self.send_error(404)
        return None

    def log_message(self, fmt, *args):
        if os.environ.get("CLASE_DEBUG"):
            super().log_message(fmt, *args)


class ServidorHilos(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


# ---------------------------------------------------------------------------
def configurar_online() -> None:
    Config.online = True
    Config.clave_profesor = os.environ.get("PROFESOR_CLAVE", "").strip()
    Config.clave_estudiantes = os.environ.get("CLAVE_ESTUDIANTES", "").strip()
    if len(Config.clave_profesor) < 8:
        raise RuntimeError("Defina la variable PROFESOR_CLAVE con al menos 8 caracteres "
                           "(contraseña del panel del profesor).")
    url = os.environ.get("URL_PUBLICA", "").strip()
    if url:
        Config.url_publica = url if url.endswith("/") else url + "/"
    Config.ip_publica = os.environ.get("IP_PUBLICA", "").strip()
    if not Config.ip_publica:
        log("IP_PUBLICA no definida: detectando la IP pública del servidor...")
        Config.ip_publica = detectar_ip_publica()
        if not Config.ip_publica:
            raise RuntimeError("No se pudo detectar la IP pública. Defina la variable "
                               "IP_PUBLICA con la IP del VPS.")
    log(f"IP anunciada para WebRTC: {Config.ip_publica} (puerto {PUERTO_ICE} UDP/TCP)")


def main() -> int:
    ap = argparse.ArgumentParser(description="Clase en Vivo UNACHI")
    ap.add_argument("--ip", help="IP de la LAN a mostrar a los estudiantes (modo local)")
    ap.add_argument("--puerto-web", type=int, default=int(os.environ.get("PUERTO") or 8080))
    ap.add_argument("--sin-navegador", action="store_true")
    ap.add_argument("--sin-mediamtx", action="store_true",
                    help="no iniciar MediaMTX (ya se ejecuta aparte)")
    ap.add_argument("--online", action="store_true",
                    default=os.environ.get("MODO", "").lower() == "online",
                    help="modo servidor en Internet (VPS / Docker)")
    ap.add_argument("--solo-descargar", action="store_true",
                    help="descargar MediaMTX y salir (se usa al construir la imagen Docker)")
    args = ap.parse_args()

    if args.solo_descargar:
        try:
            asegurar_mediamtx()
            return 0
        except RuntimeError as e:
            log(f"ERROR: {e}")
            return 1

    global SALA
    log(f"Clase en Vivo UNACHI v{VERSION} ({', '.join(FUNCIONES)})")
    SALA = Sala(DIR_GRABACIONES)
    Config.puerto_web = args.puerto_web
    Config.secreto = hashlib.sha256(
        (os.environ.get("SESION_SECRETO") or secrets.token_hex(32)).encode() +
        os.environ.get("PROFESOR_CLAVE", "").encode() +
        os.environ.get("CLAVE_ESTUDIANTES", "").encode()).digest()

    proc = None
    try:
        if args.online:
            configurar_online()
            Config.ips = [Config.ip_publica]
        else:
            ips = ips_locales()
            if args.ip:
                ips = [args.ip] + [i for i in ips if i != args.ip]
            Config.ips = ips
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

    print("\n" + "=" * 64)
    print("  CLASE EN VIVO — UNACHI" + ("  (modo online)" if Config.online else ""))
    if Config.online:
        base = Config.url_publica or "https://SU-DOMINIO/"
        print(f"  Escuchando en      : 0.0.0.0:{args.puerto_web} (detrás de Traefik/HTTPS)")
        print(f"  Panel del profesor : {base}profesor")
        print(f"  Enlace estudiantes : {base}")
        print(f"  Código estudiantes : {Config.clave_estudiantes or '(acceso libre)'}")
        print(f"  Medios WebRTC      : {Config.ip_publica}:{PUERTO_ICE} UDP y TCP")
    else:
        print(f"  Panel del profesor : http://localhost:{args.puerto_web}/profesor.html")
        print(f"  Enlace estudiantes : http://{Config.ips[0]}:{args.puerto_web}/")
        if len(Config.ips) > 1:
            print(f"  Otras IP del equipo: {', '.join(Config.ips[1:])}")
        print("  Detener            : Ctrl+C")
    print("=" * 64 + "\n", flush=True)

    hilo = threading.Thread(target=httpd.serve_forever, daemon=True)
    hilo.start()
    if not args.sin_navegador and not Config.online:
        url_prof = f"http://localhost:{args.puerto_web}/profesor.html"
        threading.Timer(1.0, lambda: webbrowser.open(url_prof)).start()

    detener = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: detener.set())
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: detener.set())
    codigo = 0
    try:
        while not detener.is_set():
            if proc and proc.poll() is not None:
                log("MediaMTX se detuvo inesperadamente.")
                codigo = 1  # en Docker, el contenedor se reinicia solo
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
    return codigo


if __name__ == "__main__":
    sys.exit(main())

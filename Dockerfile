# Clase en Vivo UNACHI — imagen para VPS (Dokploy / Docker)
#
# Puertos:
#   8080/tcp  páginas web + WHIP/WHEP (lo publica Traefik con HTTPS en su dominio)
#   8189/udp  medios WebRTC  ┐ publíquelos en el VPS con el MISMO número
#   8189/tcp  respaldo TCP   ┘ (Dokploy → Advanced → Ports, modo Host)
#
# Variables: PROFESOR_CLAVE (obligatoria), CLAVE_ESTUDIANTES, IP_PUBLICA,
#            URL_PUBLICA, SESION_SECRETO. Ver DESPLIEGUE_DOKPLOY.md.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MODO=online \
    PUERTO=8080 \
    PUERTO_MEDIOS=8189

WORKDIR /app

COPY servidor_clase.py mediamtx.yml ./
COPY web ./web

# Descarga MediaMTX (Linux amd64/arm64 según el VPS) durante la construcción
# y crea un usuario sin privilegios para ejecutar el servicio.
RUN python servidor_clase.py --solo-descargar \
 && /app/mediamtx/mediamtx --help > /dev/null \
 && useradd --system --uid 10001 --no-create-home clase \
 && chown -R clase:clase /app

USER clase

EXPOSE 8080/tcp 8189/udp 8189/tcp

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:%s/salud' % os.environ.get('PUERTO','8080'), timeout=4)" || exit 1

CMD ["python", "servidor_clase.py", "--online", "--sin-navegador"]

# Clase en Vivo UNACHI — versión VPS

Transmisión en vivo de la pantalla del profesor a estudiantes que están **en sus casas**, con latencia menor a 1 segundo (WebRTC). El profesor solo necesita un navegador y los estudiantes **no instalan nada**: abren un enlace, escriben un código y ven la clase en el celular, la laptop o la tableta.

Esta versión corre en un **VPS de Hostinger con Dokploy**, a partir del `Dockerfile` de este repositorio.

**En producción:** <https://clase.quimicaeduc.org>

---

## Cómo funciona

```
Profesor (casa u oficina)                 VPS Hostinger · Dokploy                      Estudiantes (casa)
https://clase.quimicaeduc.org/profesor ─► Traefik :443 (HTTPS) ─► contenedor :8080 ◄─ https://clase.quimicaeduc.org
   contraseña del profesor                 servidor_clase.py  (páginas + control       código de acceso
   «Compartir pantalla»                                         de acceso + proxy)
                                           MediaMTX v1.21.1   (WebRTC)
             ════════ video WebRTC ══════► puerto 8189 UDP/TCP ═════════════════════════►
```

| Pieza | Función |
|---|---|
| **Traefik** (incluido en Dokploy) | Publica el dominio con HTTPS de Let's Encrypt. El navegador solo permite compartir la pantalla en páginas `https://` |
| **`servidor_clase.py`** | Sirve las páginas, pide la contraseña al profesor y el código a los estudiantes, y reenvía la señalización WHIP/WHEP a MediaMTX. Solo usa la biblioteca estándar de Python |
| **MediaMTX** | Recibe la pantalla del profesor (WHIP) y la reparte a cada estudiante (WHEP). Su señalización solo escucha dentro del contenedor |
| **Puerto 8189 UDP/TCP** | Lleva el video directamente entre el VPS y los navegadores. TCP sirve de respaldo para redes que bloquean UDP |

## Uso en clase

**Profesor**

1. Abra `https://clase.quimicaeduc.org/profesor` en Chrome, Edge o Firefox y escriba la contraseña.
2. Elija la **calidad**. Para que los estudiantes lo oigan, elija **Micrófono** en *Audio*.
3. Pulse **Compartir pantalla** y elija la pantalla, ventana o pestaña.
4. Comparta con los estudiantes el **enlace**, el **QR** y el **código de acceso**. Los tres aparecen en el panel; también puede pulsar *Proyectar QR*.
5. El panel muestra cuántos estudiantes están conectados, los Mbps enviados y el tiempo en vivo. *Cambiar ventana* cambia lo que se comparte sin cortar la clase.

**Estudiantes**

1. Abren `https://clase.quimicaeduc.org` y escriben el código que les dio el profesor. El código no distingue mayúsculas de minúsculas.
2. Si el profesor todavía no transmite, ven «Esperando al profesor…». La imagen aparece sola cuando empieza la clase.
3. Tienen botones de **Pantalla completa**, **Llenar pantalla** y **Activar sonido**.

**Perfiles de calidad**

| Perfil | Resolución | fps | Bitrate por estudiante | Cuándo usarlo |
|---|---|---|---|---|
| Texto nítido | 1080p | 15 | 2,5 Mbps | Código, fórmulas, hojas de cálculo |
| Equilibrado (predeterminado) | 720p | 20 | 1,5 Mbps | Diapositivas y uso general |
| Video/animación | 720p | 30 | 2,5 Mbps | Simulaciones o videos |
| Red saturada | 720p | 10 | 0,8 Mbps | Estudiantes con Internet lento o datos móviles |

El VPS envía una copia del video a cada estudiante. Con 30 estudiantes en el perfil *Equilibrado* salen unos 45 Mbps, es decir, unos 20 GB por hora de clase.

**OBS Studio (opcional):** en *Ajustes → Emisión*, elija el servicio **WHIP**, con el servidor `https://clase.quimicaeduc.org/clase/whip`. En *Bearer Token* escriba la contraseña del profesor.

## Despliegue en Dokploy

La guía completa, paso a paso y con solución de problemas, está en **[DESPLIEGUE_DOKPLOY.md](DESPLIEGUE_DOKPLOY.md)**. Resumen:

1. **DNS:** cree un registro `A` del subdominio hacia la IP del VPS. Hágalo **antes** de desplegar.
2. **Firewall:** abra el puerto **8189** en UDP y TCP. Los puertos 80 y 443 ya los usa Dokploy.
3. **Dokploy → Create Service → Application:**
   - Proveedor GitHub, repositorio `PGBeermann/aulaenvivo`, rama `main`.
   - Build Type **Dockerfile**: Docker File `Dockerfile`, contexto `.`.
4. **Environment:** defina las variables de la tabla siguiente.
5. **Domains:** su dominio → puerto del contenedor **8080**, con **HTTPS** y **Let's Encrypt**.
6. **Advanced → Ports:** publique `8189 → 8189` en **UDP** y otra vez en **TCP**, en modo **Ingress**.
7. Pulse **Deploy** y compruebe que `https://su-dominio/salud` responde `{"ok": true}`.

Con *Autodeploy* activado, cada `git push` a `main` vuelve a desplegar la aplicación, lo que corta la clase unos segundos. No haga push durante una clase.

### Variables de entorno

| Variable | Obligatoria | Descripción |
|---|---|---|
| `PROFESOR_CLAVE` | **Sí** (mín. 8 caracteres) | Contraseña del panel del profesor y token de OBS |
| `CLAVE_ESTUDIANTES` | No | Código de acceso de los estudiantes. Vacío = cualquiera con el enlace puede ver |
| `IP_PUBLICA` | Recomendada | IP del VPS que se anuncia para el video. Si falta, se detecta al arrancar |
| `URL_PUBLICA` | No | Enlace que aparece en el QR, p. ej. `https://clase.quimicaeduc.org/` |
| `SESION_SECRETO` | No | Mantiene abiertas las sesiones aunque el contenedor se reinicie |
| `PUERTO_MEDIOS` | No | Puerto del video (predeterminado `8189`). Si lo cambia, publique ese mismo número |

Para cambiar el código de un curso a otro, edite `CLAVE_ESTUDIANTES` en Dokploy y pulse **Deploy**.

> Nunca escriba la contraseña ni el código en archivos de este repositorio: es público. Configúrelos solo en las variables de entorno de Dokploy.

### Probar la imagen en su equipo

```bash
docker build -t clase-en-vivo .
```

```bash
docker run --rm -p 8080:8080 -p 8189:8189/udp -p 8189:8189/tcp -e PROFESOR_CLAVE=prueba1234 -e IP_PUBLICA=127.0.0.1 clase-en-vivo
```

Luego abra `http://localhost:8080/profesor`.

## Seguridad

- **Solo el profesor transmite.** Publicar exige la contraseña `PROFESOR_CLAVE`. Sin ella, el servidor responde `401`.
- **Solo quien tiene el código ve la clase**, si `CLAVE_ESTUDIANTES` está definida.
- **Sesiones** con cookies firmadas (HMAC‑SHA256, `HttpOnly`, `SameSite=Strict` y `Secure`), válidas por 12 horas.
- **Contraseñas por fuerza bruta:** tras 8 intentos fallidos seguidos, esa conexión queda bloqueada 5 minutos.
- **Superficie mínima:**
  - La señalización y la API de MediaMTX solo escuchan en `127.0.0.1` dentro del contenedor.
  - Solo existe la ruta `clase` y no se listan carpetas.
  - RTSP, HLS, SRT, MoQ y RTMP están desactivados.
- **Cifrado:** HTTPS para las páginas y la señalización. El video WebRTC va siempre cifrado (DTLS‑SRTP).
- **Contenedor** sin privilegios: usuario `clase`, UID 10001. Tiene un *healthcheck* en `/salud`.

## Estructura del repositorio

| Archivo | Función |
|---|---|
| `Dockerfile` | Imagen de la versión VPS: Python 3.12 slim + MediaMTX v1.21.1 |
| `servidor_clase.py` | Servidor del aula: páginas, control de acceso, proxy WHIP/WHEP y arranque de MediaMTX |
| `mediamtx.yml` | Configuración endurecida de MediaMTX. En el VPS se ajusta con variables `MTX_*` |
| `web/index.html` | Página del estudiante |
| `web/profesor.html` | Panel del profesor |
| `web/acceso.html` | Pantalla de contraseña del profesor y código de estudiantes |
| `web/estilo.css` | Identidad visual UNACHI: verde Pantone 364 C y rojo Pantone 187 C |
| `DESPLIEGUE_DOKPLOY.md` | Guía detallada de despliegue en Hostinger + Dokploy |
| `LEAME.md` | Versión **local** para la red Wi‑Fi del aula, sin servidor |
| `iniciar_clase.*`, `abrir_firewall.*` | Scripts de la versión local |

El mismo código sirve para las dos versiones. Con `--online`, o con `MODO=online` como en el `Dockerfile`, funciona en el VPS. Sin esa opción, funciona en el equipo del profesor dentro del aula. Vea [LEAME.md](LEAME.md).

## Solución rápida de problemas

| Síntoma | Qué revisar |
|---|---|
| «Compartir pantalla» deshabilitado | La página debe abrirse con `https://` |
| Aviso «No seguro» o certificado «TRAEFIK DEFAULT CERT» | El DNS se creó después del despliegue. En **Domains**, desactive HTTPS y guarde; luego actívelo con Let's Encrypt y guarde |
| Los estudiantes no ven video aunque el profesor transmite | El puerto 8189 UDP/TCP (firewall de Hostinger y **Ports** en Dokploy) y que `IP_PUBLICA` sea la IP real del VPS |
| `/salud` no responde | En **Logs** de Dokploy, lo más común es que falte `PROFESOR_CLAVE` o que tenga menos de 8 caracteres |
| «Demasiados intentos» | Espere 5 minutos |

Mantenga **una sola réplica** de la aplicación: el estado de la transmisión vive dentro del contenedor.

## Créditos

- [MediaMTX](https://github.com/bluenviron/mediamtx) (licencia MIT). Servidor WebRTC/WHIP/WHEP.
- *QR Code Generator for JavaScript*, de K. Arase (licencia MIT).
- Identidad visual según el *Manual de Imagen Institucional* de la Universidad Autónoma de Chiriquí. El repositorio no incluye el logotipo: copie `logo-unachi.png` en `web/` para mostrarlo.

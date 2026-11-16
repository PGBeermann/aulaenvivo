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
3. Tienen botones de **Pantalla completa**, **Llenar pantalla** y **Activar sonido**, además de chat, expresiones, mano levantada y **Pedir la palabra** (ver «Participación de los estudiantes»).

**Perfiles de calidad**

| Perfil | Resolución | fps | Bitrate por estudiante | Cuándo usarlo |
|---|---|---|---|---|
| Texto nítido | 1080p | 15 | 2,5 Mbps | Código, fórmulas, hojas de cálculo |
| Equilibrado (predeterminado) | 720p | 20 | 1,5 Mbps | Diapositivas y uso general |
| Video/animación | 720p | 30 | 2,5 Mbps | Simulaciones o videos |
| Red saturada | 720p | 10 | 0,8 Mbps | Estudiantes con Internet lento o datos móviles |

El VPS envía una copia del video a cada estudiante. Con 30 estudiantes en el perfil *Equilibrado* salen unos 45 Mbps, es decir, unos 20 GB por hora de clase.

**OBS Studio (opcional):** en *Ajustes → Emisión*, elija el servicio **WHIP**, con el servidor `https://clase.quimicaeduc.org/clase/whip`. En *Bearer Token* escriba la contraseña del profesor.

## Participación de los estudiantes

La primera vez, cada estudiante escribe su nombre; el navegador lo recuerda y se puede cambiar desde el chat.

| Función | Estudiante | Profesor (recuadro **Participación**) |
|---|---|---|
| **Chat** | Botón 💬. En la computadora queda abierto a la derecha; en el celular es un panel deslizable | Lee y escribe a toda la clase, **elimina mensajes**, cierra o abre el chat y lo **descarga** en `.txt` |
| **Expresiones** | Botón 😀: 👍 De acuerdo · 👏 Aplausos · 😂 Risa · 😮 Sorpresa · ❤️ Me gusta · 🤔 Tengo una duda · 🐢 Más despacio · 🔁 ¿Puede repetir? | Aparecen flotando sobre la vista previa, con el nombre de quien las envía |
| **Mano levantada** ✋ | Levanta o baja la mano | Lista por orden de llegada, con **Bajar** y **Bajar todas** |
| **Pedir la palabra** 🎤 | Pide o cancela el turno | Lista por orden de llegada, con **Dar la palabra** y ✕ para descartar |
| **Hablar** | Al recibir la palabra pulsa **Activar micrófono**; mientras habla, el sonido de la clase se silencia en su equipo para evitar eco. Termina con **Terminar de hablar** | Ve quién habla, el tiempo y el nivel de su micrófono. **Quitar la palabra** corta el micrófono en el servidor aunque el navegador del estudiante no responda |

- **Cómo llega la voz a todos:** el micrófono del estudiante llega al panel del profesor, que lo **mezcla con el audio de la clase**. Así lo escucha todo el grupo y queda en la grabación.
- **Un turno a la vez:** si da la palabra a otro estudiante, el turno anterior se cierra. Si el estudiante cierra la página, el turno se libera en unos 10 s.
- **Micrófono y HTTPS:** el estudiante solo puede usar el micrófono con HTTPS, es decir, en la versión del VPS. En la versión local del aula (`http://IP:8080`) recibe el turno, pero habla en voz alta en el salón.
- **Use audífonos** mientras un estudiante habla; si lo escucha por parlantes, su micrófono lo recoge y se produce eco. Con la casilla **Escuchar aquí** puede dejar de oírlo en su equipo, y los estudiantes lo siguen escuchando.
- **Sonido de los estudiantes:** cada estudiante debe pulsar **Activar sonido** una vez para oír la clase. Cuando alguien tiene la palabra, el video muestra un aviso con ese botón.
- **Mientras comparte otra ventana:**
  - **⧉ Ventana flotante** (Chrome o Edge 116+) mantiene el chat y las manos siempre visibles. Si comparte la **pantalla completa**, los estudiantes también la verán; comparta solo la ventana de la presentación.
  - Suena un aviso al recibir una mano, un pedido de palabra o un mensaje. Opcionalmente, puede activar las notificaciones del escritorio.

## Grabación de la clase

Recuadro **Grabación** del panel → **● Iniciar grabación**.

- **Qué se graba:** lo mismo que reciben los estudiantes: la pantalla, el audio del profesor y la voz de quien tenga la palabra. El chat se descarga aparte en `.txt`.
- **Dónde se graba:** en el servidor, de modo que si el panel se cierra, la grabación sigue. Se activa y se detiene en caliente, sin cortar la transmisión.
- **Formato:** MP4, video H.264 y audio Opus. Se reproduce en VLC, Chrome, Edge y Firefox. Para un reproductor que no admita Opus: `ffmpeg -i clase.mp4 -c:v copy -c:a aac clase_aac.mp4`.
- **Aviso a los estudiantes:** ven la insignia **● GRABANDO** y un mensaje en el chat. Conviene informar al grupo antes de grabar.
- **Archivos:**
  - El panel los lista con **Descargar** y **🗑 Eliminar**. «Cambiar ventana» inicia un archivo nuevo.
  - En el VPS se borran solos a los 30 días. En la versión local quedan en la carpeta `grabaciones/clase/` y no se borran.
  - En Dokploy hace falta un **volumen** en `/app/grabaciones` para que sobrevivan a cada despliegue (paso 7 de [DESPLIEGUE_DOKPLOY.md](DESPLIEGUE_DOKPLOY.md)).
- **Códec:** VP8 no se puede grabar. Use H.264 (predeterminado), VP9 o AV1; con VP8, el panel avisa.
- **Espacio en disco:** 1 h en el perfil *Equilibrado* ocupa unos 0,7 GB, y en *Texto nítido* unos 1,1 GB.

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
  - Solo existen las rutas `clase` (transmisión) y `voz` (micrófono del estudiante con la palabra), y no se listan carpetas.
  - Para publicar en `voz` se exige el **token del turno vigente**, y solo el profesor puede escucharla directamente. Al quitar la palabra, el token deja de valer y la sesión se cierra en MediaMTX.
  - RTSP, HLS, SRT, MoQ y RTMP están desactivados.
- **Cifrado:** HTTPS para las páginas y la señalización. El video WebRTC va siempre cifrado (DTLS‑SRTP).
- **Chat y acciones:** solo se aceptan peticiones JSON del mismo origen, con límites de frecuencia (5 mensajes cada 10 s por estudiante). El texto se muestra siempre escapado, nunca como HTML. La moderación, el turno de palabra, la grabación y la descarga de grabaciones o del chat son exclusivas del profesor.
- **Contenedor** sin privilegios: usuario `clase`, UID 10001. Tiene un *healthcheck* en `/salud`.

## Estructura del repositorio

| Archivo | Función |
|---|---|
| `Dockerfile` | Imagen de la versión VPS: Python 3.12 slim + MediaMTX v1.21.1 |
| `servidor_clase.py` | Servidor del aula: páginas, control de acceso, proxy WHIP/WHEP y arranque de MediaMTX |
| `mediamtx.yml` | Configuración endurecida de MediaMTX. En el VPS se ajusta con variables `MTX_*` |
| `web/index.html` | Página del estudiante: video, chat, expresiones, mano, pedir la palabra y hablar |
| `web/profesor.html` | Panel del profesor: transmisión, participación y grabación |
| `web/profesor-sala.js` | Chat, manos, turno de palabra, mezcla de audio, ventana flotante y grabaciones (profesor) |
| `web/comun.js` | Funciones compartidas (eventos en vivo, chat y expresiones) |
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
| No aparecen el chat ni los botones nuevos | `https://clase.quimicaeduc.org/version` debe responder `"version": "2.0.0"` o superior. Si no responde, el contenedor sigue con la versión anterior: pulse **Deploy** en Dokploy |
| El estudiante no puede activar el micrófono | Debe permitir el micrófono en el ícono del candado del navegador |
| Se oye eco cuando habla un estudiante | Use audífonos o desmarque **Escuchar aquí** |
| La grabación quedó sin imagen | La transmisión usaba VP8. Elija H.264 |
| Las grabaciones desaparecen tras un despliegue | Falta el volumen en `/app/grabaciones` |

Mantenga **una sola réplica** de la aplicación: el estado de la transmisión vive dentro del contenedor.

## Pruebas de participación y grabación (16‑nov‑2026)

Con MediaMTX v1.21.1 y Chromium automatizado (Playwright), se probó un profesor con dos o tres estudiantes, en modo online (contraseña y código de acceso) y local. Se usó un micrófono simulado con un tono de prueba.

- **Chat:** los mensajes llegan a todos y el HTML se muestra como texto.
- **Expresiones, manos y pedidos de palabra:** llegan al profesor en tiempo real.
- **Voz del estudiante:**
  - Otro estudiante la recibe dentro de la transmisión: el nivel medido pasa de 0 a 128 mientras habla y vuelve a 0 al quitarle la palabra.
  - Queda en la grabación: −91 dB antes del turno y 0 dB durante él.
- **Turnos:** el relevo entre estudiantes funciona, y una página cerrada libera el turno.
- **Grabaciones:** el profesor las descarga; un estudiante recibe `401`.
- **Rutas nuevas sin sesión** (eventos, acciones, voz sin token): responden `401`.
- **Cambiar ventana:** los estudiantes vuelven a la imagen en unos 2 s; antes tardaban unos 10 s.

## Créditos

- [MediaMTX](https://github.com/bluenviron/mediamtx) (licencia MIT). Servidor WebRTC/WHIP/WHEP.
- *QR Code Generator for JavaScript*, de K. Arase (licencia MIT).
- Identidad visual según el *Manual de Imagen Institucional* de la Universidad Autónoma de Chiriquí. El repositorio no incluye el logotipo: copie `logo-unachi.png` en `web/` para mostrarlo.

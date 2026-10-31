# Clase en Vivo UNACHI

Transmisión de la pantalla del profesor a los estudiantes, con latencia menor a 1 segundo (WebRTC). Los estudiantes solo necesitan un navegador y **no instalan nada**.

Hay dos formas de usarlo:

| Modo | Dónde están los estudiantes | Cómo se instala |
|---|---|---|
| **Online** | En sus casas, por Internet | En un VPS con Docker/Dokploy. Vea **[DESPLIEGUE_DOKPLOY.md](DESPLIEGUE_DOKPLOY.md)** |
| **Local** | En el aula, en la misma red Wi‑Fi | En el equipo del profesor (este documento). La señal no sale de la red local y, después de la primera ejecución, no hace falta Internet |

## Modo local (red Wi‑Fi del aula)

```
Profesor (este equipo)                                   Estudiantes (misma Wi-Fi)
┌──────────────────────────────────────────┐            ┌────────────────────────┐
│ Navegador: http://localhost:8080/profesor │──WHIP──┐   │ http://IP:8080/        │
│   (captura de pantalla, se codifica 1 vez)│        │   │  (QR proyectado)       │
│ servidor_clase.py  :8080  páginas + proxy │        ▼   │                        │
│   └► MediaMTX v1.21.1 (127.0.0.1:8889) ───┼──WHEP─────▶│ celulares, laptops,    │
│                    :8189  medios UDP/TCP  │            │ tabletas               │
└──────────────────────────────────────────┘            └────────────────────────┘
```

## Contenido

| Archivo | Función |
|---|---|
| `iniciar_clase.bat` | Arranque en Windows 10/11 (doble clic) |
| `iniciar_clase.sh` | Arranque en Linux/macOS (`./iniciar_clase.sh`) |
| `abrir_firewall.bat` / `.sh` | Abre los puertos solo para la subred local (se ejecuta **una vez**). El 8889 ya no hace falta, pero abrirlo no causa problemas |
| `servidor_clase.py` | Descarga e inicia MediaMTX, sirve las páginas, reenvía WHIP/WHEP a MediaMTX y controla el acceso (solo biblioteca estándar) |
| `mediamtx.yml` | Configuración endurecida de MediaMTX |
| `Dockerfile` | Imagen para el modo online en un VPS (Dokploy) |
| `DESPLIEGUE_DOKPLOY.md` | Guía paso a paso para el VPS de Hostinger con Dokploy |
| `web/profesor.html` | Panel del profesor: compartir pantalla, QR, espectadores y Mbps |
| `web/index.html` | Página del estudiante: video en vivo, pantalla completa y reconexión automática |
| `web/acceso.html` | Pantalla de contraseña del profesor y código de estudiantes (solo modo online) |
| `web/estilo.css` | Identidad visual UNACHI (verde Pantone 364 C, rojo Pantone 187 C) |
| `web/vendor/qrcode.js` | Generador de QR sin conexión (K. Arase, licencia MIT) |

## Requisitos

- **Python 3.8+** en el equipo del profesor. En Windows: `winget install -e --id Python.Python.3.12`.
- **Navegador** Chrome, Edge o Firefox actual para el profesor. Los estudiantes pueden usar cualquier navegador moderno, incluido Safari en iOS.
- **Internet solo la primera vez**, para descargar MediaMTX v1.21.1 desde GitHub (descarga de unos 20–25 MB comprimidos). Si no hay conexión en ese momento, descargue el archivo de <https://github.com/bluenviron/mediamtx/releases/tag/v1.21.1> y coloque `mediamtx.exe` (o `mediamtx`) dentro de una carpeta `mediamtx/` junto a este LEAME.

## Uso en clase

1. **Solo la primera vez:** ejecute `abrir_firewall.bat`; pedirá permisos de administrador.
2. Conecte el equipo a la **misma red Wi‑Fi** que los estudiantes.
3. Haga doble clic en **`iniciar_clase.bat`**. Se abrirá el panel del profesor en el navegador.
4. Pulse **Proyectar QR**. Los estudiantes escanean el código, que abre `http://IP-del-profesor:8080/`. Pulse clic o Esc para cerrar la proyección.
5. Pulse **Compartir pantalla** y elija la pantalla, ventana o pestaña que quiere mostrar.
6. Durante la clase:
   - **Cambiar ventana** cambia lo que se comparte; los estudiantes se reconectan solos en unos 2 segundos.
   - El recuadro **Estado** muestra cuántos espectadores hay y el ancho de banda en uso.
7. Para terminar, pulse **Detener transmisión** y cierre la ventana de consola (o pulse Ctrl+C).

### Perfiles de calidad

| Perfil | Resolución | fps | Bitrate | Cuándo usarlo |
|---|---|---|---|---|
| Texto nítido | 1080p | 15 | 2,5 Mbps | Código fuente, fórmulas, hojas de cálculo |
| Equilibrado (predeterminado) | 720p | 20 | 1,5 Mbps | Diapositivas y uso general |
| Video/animación | 720p | 30 | 2,5 Mbps | Simulaciones o videos |
| Red saturada | 720p | 10 | 0,8 Mbps | Muchos estudiantes o una Wi‑Fi de 2,4 GHz congestionada |

**Tráfico total ≈ bitrate × número de espectadores.** Por ejemplo, 35 estudiantes con el perfil Equilibrado suman unos 53 Mbps de aire Wi‑Fi. Si puede, conecte el equipo del profesor al router por cable.

## Seguridad (configurada en `mediamtx.yml`)

- **Publicar** solo es posible desde el propio equipo del profesor. La señalización de MediaMTX escucha solo en `127.0.0.1:8889`, y `servidor_clase.py` reenvía las peticiones WHIP solo si vienen de localhost. Si un estudiante intenta transmitir, recibe `401`.
- En el **modo online**, publicar exige la contraseña `PROFESOR_CLAVE` y ver puede exigir el código `CLAVE_ESTUDIANTES`. Las sesiones usan cookies firmadas (HMAC, `HttpOnly`, `SameSite=Strict`, `Secure`).
- **Ver:** solo existe la ruta `clase`. Cualquier otra ruta se rechaza.
- **La API de control** solo escucha en `127.0.0.1`. El panel del profesor no se abre desde otros equipos (se redirige a la vista del estudiante).
- **Protocolos desactivados:** RTSP, HLS, SRT y MoQ. RTMP queda disponible solo para OBS local.
- **Firewall:** las reglas se limitan a `remoteip=localsubnet`.
- **Cifrado:** el medio WebRTC siempre va cifrado (DTLS‑SRTP). La señalización HTTP va en claro, lo que es aceptable en una LAN controlada. Para usar HTTPS, active `webrtcEncryption` con un certificado.

## Solución de problemas

| Síntoma | Causa probable y solución |
|---|---|
| El estudiante ve «No se alcanza el servidor del aula» | **Aislamiento de clientes (AP isolation)** en la Wi‑Fi institucional, o firewall. Pruebe `ping IP-del-profesor` desde otro equipo. Pida a TI una SSID o VLAN de aula sin aislamiento, o use un router propio. |
| La página carga pero el video no aparece | Está bloqueado el **UDP 8189**. Ejecute `abrir_firewall.bat`. MediaMTX también ofrece TCP 8189 como respaldo. |
| «El puerto 1935 / 8189 ya está en uso» | Hay otra copia del programa abierta (por ejemplo, desde otra carpeta). Ciérrela desde el Administrador de tareas (`mediamtx.exe`). |
| Windows no deja pasar nada aunque existan las reglas | Si alguna vez pulsó **Cancelar** en el aviso del firewall para `python.exe` o `mediamtx.exe`, Windows creó reglas de **bloqueo** que tienen prioridad. Bórrelas en `wf.msc` → *Reglas de entrada*. |
| El QR muestra una IP que no es la de la Wi‑Fi (VPN, Hyper‑V, VirtualBox) | Elija la IP correcta en el selector del panel, o inicie con `iniciar_clase.bat --ip 192.168.x.y`. Si el video no conecta, añada esa IP en `webrtcAdditionalHosts` de `mediamtx.yml`. |
| «El puerto 8889 ya está en uso» | Hay otra instancia de MediaMTX abierta. Ciérrela desde el Administrador de tareas. |
| El botón «Compartir pantalla» está deshabilitado | El panel debe abrirse como `http://localhost:8080/profesor.html` (el navegador solo permite capturar la pantalla en localhost o HTTPS). |
| En iPhone el video no pasa a pantalla completa | Use el botón **Pantalla completa**: en iOS usa el reproductor nativo. |

## Alternativa: transmitir con OBS Studio

Use OBS 30 o superior. En *Ajustes → Emisión*, elija el servicio **WHIP** con el servidor `http://localhost:8889/clase/whip`. En *Salida*, use x264, perfil `baseline`, tune `zerolatency`, intervalo de fotogramas clave de 1 s y 1500–2500 kbps. Los estudiantes siguen usando el mismo QR y el panel indica «Transmisión externa detectada».

## Logotipo institucional

Copie el archivo oficial **`logo-unachi.png`** en la carpeta `web/`. Si no existe, el encabezado se muestra sin logotipo. El paquete no reproduce el logotipo, conforme al *Manual de Imagen Institucional* de la UNACHI (Consejo Administrativo N.° 12‑2014), que regula su área de reserva y sus proporciones. Los colores HEX (#299100, #C41237) son la conversión CMYK→RGB de los Pantone oficiales. Para piezas de alto perfil conviene confirmarlos con Relaciones Públicas.

## Pruebas realizadas

Se hicieron el 23‑sep‑2026 con **MediaMTX v1.21.1 real** y Chromium en modo automatizado:

- La configuración carga sin errores.
- El profesor publica su pantalla por WHIP y el estudiante recibe video 1280×720 por WHEP.
- El contador de espectadores y el cálculo de Mbps funcionan.
- Al pulsar «Detener», el estudiante vuelve a la pantalla de espera.
- Un intento de publicar desde otra IP de la LAN recibe **401**, y una ruta distinta de `clase` se rechaza.
- La API no es accesible desde la LAN.
- El QR se decodificó correctamente con OpenCV.
- Ctrl+C cierra también MediaMTX.

Los scripts `.bat` no pudieron ejecutarse en Windows durante las pruebas. Se revisaron manualmente y usan finales de línea CRLF.

El 31‑oct‑2026 se probó el **modo online** en Windows con MediaMTX v1.21.1 real y Chromium:

- Sin contraseña no se abre el panel, no se consulta el estado y no se puede transmitir (401). Sin código de estudiante no se puede ver (401).
- La contraseña incorrecta se rechaza y una cookie manipulada no da acceso.
- El profesor publica por WHIP a través del proxy y el estudiante, entrando con su código, recibe el video 1280×720. El contador marca 1 espectador y unos 1,07 Mbps.
- La publicación con «Bearer Token» (como OBS) funciona y la sesión se cierra con DELETE.
- El modo local sigue igual: desde la LAN no se puede transmitir ni abrir el panel.

La imagen Docker no se construyó en este equipo porque no tiene Docker; se construye en Dokploy.

## Referencias

- MediaMTX: <https://github.com/bluenviron/mediamtx> (licencia MIT). Documentación de WebRTC, WHIP y WHEP en <https://mediamtx.org/docs>.
- IETF RFC 9725, *WebRTC‑HTTP Ingestion Protocol (WHIP)*, 2025. WHEP: borrador `draft-ietf-wish-whep`.
- W3C, *Screen Capture* (`getDisplayMedia`), que requiere un contexto seguro.
- K. Arase, *QR Code Generator for JavaScript* v2.0.4 (MIT).

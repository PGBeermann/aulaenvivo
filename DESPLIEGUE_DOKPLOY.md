# Clase en Vivo UNACHI en un VPS de Hostinger con Dokploy

Con esta configuración el profesor transmite su pantalla desde cualquier lugar y los estudiantes ven la clase **desde sus casas**, con cualquier navegador y sin instalar nada.

```
Profesor (casa u oficina)                VPS Hostinger (Dokploy)                    Estudiantes (casa)
https://clase.su-dominio/profesor  ──►  Traefik :443 (HTTPS) ─► contenedor :8080  ◄──  https://clase.su-dominio/
   contraseña PROFESOR_CLAVE             servidor_clase.py (páginas + proxy)            código CLAVE_ESTUDIANTES
                                         MediaMTX (WebRTC)                               (opcional)
           ══════ video WebRTC ════════► puerto 8189 UDP/TCP ════════════════════════►
```

- **HTTPS** lo pone Dokploy (Traefik + Let's Encrypt). Es obligatorio: el navegador solo permite compartir la pantalla en páginas `https://`.
- **Video**: viaja por el puerto **8189** (UDP, y TCP como respaldo), que se publica directamente en el VPS.
- **Seguridad**: solo quien conoce `PROFESOR_CLAVE` puede transmitir. Si define `CLAVE_ESTUDIANTES`, solo quien tenga el código puede ver la clase.

---

## 1. Lo que necesita

| Requisito | Detalle |
|---|---|
| VPS Hostinger con Dokploy | Plantilla «Dokploy» de Hostinger, o Dokploy instalado en Ubuntu |
| Un nombre de dominio | Un subdominio, p. ej. `clase.su-dominio.com`. Si no tiene dominio, puede usar el nombre del VPS que da Hostinger (`srvXXXXXX.hstgr.cloud`), que ya apunta a su IP |
| IP pública del VPS | Aparece en hPanel → VPS → Resumen |

## 2. Apuntar el dominio al VPS (DNS)

> Cree el registro **antes** de desplegar (paso 8). Si no, Let's Encrypt puede fallar en el primer intento (vea «Solución de problemas»).

En el panel DNS del dominio (en Hostinger: hPanel → Dominios → DNS / Nameservers) cree un registro:

| Tipo | Nombre | Apunta a | TTL |
|---|---|---|---|
| A | `clase` | IP pública del VPS | 300 |

Espere unos minutos y compruebe que `clase.su-dominio.com` responde con la IP del VPS (por ejemplo con `ping clase.su-dominio.com`). Si usa `srvXXXXXX.hstgr.cloud`, omita este paso.

## 3. Abrir el puerto de video en el firewall

Dokploy ya tiene abiertos los puertos 80 y 443. Falta el **8189**, en **UDP y TCP**.

**Firewall de Hostinger** (hPanel → VPS → Seguridad → Firewall). Si tiene reglas activas, agregue:

| Acción | Protocolo | Puerto | Origen |
|---|---|---|---|
| Aceptar | UDP | 8189 | Cualquiera |
| Aceptar | TCP | 8189 | Cualquiera |

Confirme también que siguen permitidos el 22 (SSH), el 80, el 443 y el 3000 (panel de Dokploy).

**Firewall del sistema (UFW)**: solo si lo activó usted. Compruébelo por SSH:

```bash
sudo ufw status
```

Si dice `Status: active`, abra el puerto:

```bash
sudo ufw allow 8189/udp && sudo ufw allow 8189/tcp
```

## 4. Crear la aplicación en Dokploy

1. Abra Dokploy (`http://IP-del-VPS:3000`) → **Projects** → **Create Project** → nombre `aula`.
2. Dentro del proyecto: **Create Service → Application** → nombre `clase-en-vivo`.
3. Pestaña **General → Provider**:
   - Elija **Git** (o **GitHub** si ya conectó su cuenta).
   - Repository URL: `https://github.com/PGBeermann/aulaenvivo.git`
   - Branch: `main`
   - Build Path: `/`
   - Pulse **Save**.
4. En **Build Type** elija **Dockerfile**:
   - Docker File: `Dockerfile`
   - Docker Context Path: `.`
   - Pulse **Save**.

## 5. Variables de entorno

Pestaña **Environment**: pegue lo siguiente, cambie los valores y pulse **Save**.

```env
PROFESOR_CLAVE=una-contraseña-larga-y-secreta
CLAVE_ESTUDIANTES=quimica2026
IP_PUBLICA=203.0.113.10
URL_PUBLICA=https://clase.su-dominio.com/
SESION_SECRETO=cadena-aleatoria-de-40-caracteres-o-mas
```

| Variable | ¿Obligatoria? | Para qué sirve |
|---|---|---|
| `PROFESOR_CLAVE` | **Sí** (mín. 8 caracteres) | Contraseña del panel del profesor y token de OBS |
| `CLAVE_ESTUDIANTES` | No | Código que escriben los estudiantes (sin distinguir mayúsculas). Si la deja vacía, cualquiera con el enlace puede ver |
| `IP_PUBLICA` | Recomendada | IP del VPS que se anuncia a los navegadores para el video. Si falta, se detecta sola al arrancar |
| `URL_PUBLICA` | No | Enlace que aparece en el QR. Si falta, se usa el dominio con que se abre el panel |
| `SESION_SECRETO` | No | Mantiene las sesiones abiertas aunque el contenedor se reinicie |

> Para cambiar el código de estudiantes en otro curso, edite `CLAVE_ESTUDIANTES` y pulse **Deploy**. Las sesiones anteriores se cierran solas.

## 6. Dominio con HTTPS

Pestaña **Domains → Add Domain**:

| Campo | Valor |
|---|---|
| Host | `clase.su-dominio.com` |
| Path | `/` |
| Container Port | `8080` |
| HTTPS | Activado |
| Certificate Provider | Let's Encrypt |

Pulse **Create**.

## 7. Publicar el puerto de video

Pestaña **Advanced → Ports → Add Port**. Agregue **dos** puertos:

| Published Port | Published Port Mode | Target Port | Protocol |
|---|---|---|---|
| 8189 | Ingress | 8189 | **UDP** |
| 8189 | Ingress | 8189 | **TCP** |

- Los dos números **deben ser iguales** (8189 → 8189).
- Use **Ingress** (el valor predeterminado). Con **Host**, Dokploy advierte que al redesplegar el contenedor viejo puede retener el puerto y el nuevo no arranca; habría que detenerlo e iniciarlo a mano. Ingress se probó en un VPS de Hostinger con Dokploy v0.30 y el video funciona.
- Si necesita otro número, cambie también `PUERTO_MEDIOS` en las variables y use ese mismo número en ambas columnas y en el firewall.

## 8. Desplegar

1. Pulse **Deploy** (arriba a la derecha).
2. En **Deployments** verá la construcción. La primera tarda 1–3 minutos, porque descarga Python y MediaMTX.
3. En **Logs** debe aparecer:

```
[clase] IP anunciada para WebRTC: 203.0.113.10 (puerto 8189 UDP/TCP)
  CLASE EN VIVO — UNACHI  (modo online)
INF [WebRTC] started with listeners on 127.0.0.1:8889 (TCP/HTTP), :8189 (UDP/ICE), :8189 (TCP/ICE)
```

4. Abra `https://clase.su-dominio.com/salud`. Debe responder `{"ok": true}`.

Para que cada cambio en GitHub se despliegue solo, active **Auto Deploy** en la pestaña General (con el proveedor GitHub) o use el webhook de la pestaña **Deployments**.

## 9. Dar la clase

1. **Profesor**: abra `https://clase.su-dominio.com/profesor` en Chrome, Edge o Firefox y escriba `PROFESOR_CLAVE`.
2. Comparta con los estudiantes el **enlace** (o el **QR**) y el **código de acceso**. Los dos aparecen en el panel. Puede enviarlos por WhatsApp, correo o la plataforma del curso.
3. Pulse **Compartir pantalla** y elija la pantalla, ventana o pestaña.
4. **Estudiantes**: abren el enlace, escriben el código y ven la clase. Si el profesor todavía no transmite, verán «Esperando al profesor…» y la imagen aparece sola cuando comienza.
5. Para el audio de la clase, elija **Micrófono** en «Audio» antes de compartir. Desde casa, los estudiantes no oyen al profesor de otro modo.

### Transmitir con OBS Studio (opcional)

En OBS 30 o superior: *Ajustes → Emisión → Servicio: WHIP*.

- Servidor: `https://clase.su-dominio.com/clase/whip`
- Bearer Token: el valor de `PROFESOR_CLAVE`

## 10. Capacidad y consumo de datos

El VPS envía una copia del video a cada estudiante:

| Perfil | Por estudiante | 30 estudiantes | 60 estudiantes |
|---|---|---|---|
| Red saturada | 0,8 Mbps | 24 Mbps | 48 Mbps |
| Equilibrado | 1,5 Mbps | 45 Mbps | 90 Mbps |
| Texto nítido | 2,5 Mbps | 75 Mbps | 150 Mbps |

Una clase de 1 hora con 30 estudiantes en el perfil Equilibrado transfiere unos **20 GB** de salida. Revise el tráfico mensual incluido en su plan de Hostinger (KVM 1: 4 TB; KVM 2: 8 TB).

Si los estudiantes tienen Internet lento (datos móviles), use el perfil **Red saturada**.

## 11. Solución de problemas

| Síntoma | Causa probable y solución |
|---|---|
| El botón «Compartir pantalla» está deshabilitado | La página no está en `https://`. Revise el dominio y el certificado (paso 6) |
| Error de certificado / «No seguro» | El DNS todavía no apunta al VPS o Let's Encrypt no terminó. Espere unos minutos. Si creó el registro DNS **después** de desplegar, Traefik puede quedarse con el certificado provisional («TRAEFIK DEFAULT CERT»). Espere 10 minutos, edite el dominio en **Domains**, desactive HTTPS y guarde, y luego vuelva a activarlo con Let's Encrypt y guarde |
| Los estudiantes ven «Esperando al profesor…» aunque el profesor transmite, o la imagen nunca carga | El puerto **8189** no llega al contenedor. Revise el firewall (paso 3) y los puertos (paso 7), y que `IP_PUBLICA` sea la IP real del VPS |
| `/salud` devuelve error 502 / 503 | El contenedor no arrancó. Revise **Logs**. Lo más común es que `PROFESOR_CLAVE` falte o tenga menos de 8 caracteres |
| «Demasiados intentos» al entrar | Hubo 8 claves incorrectas seguidas desde esa conexión. Espere 5 minutos |
| El video se corta o va a saltos | Ancho de banda insuficiente del profesor o de los estudiantes. Use un perfil más bajo |
| En una red institucional el video no carga | Esas redes suelen bloquear UDP. El respaldo por TCP 8189 debería funcionar. Si también está bloqueado, el estudiante debe usar otra red |

**Importante:** mantenga **una sola réplica** de la aplicación (es el valor predeterminado). El estado de la transmisión vive dentro del contenedor.

## 12. Probar la imagen en su propio equipo (opcional)

Con Docker instalado:

```bash
docker build -t clase-en-vivo .
```

```bash
docker run --rm -p 8080:8080 -p 8189:8189/udp -p 8189:8189/tcp -e PROFESOR_CLAVE=prueba1234 -e IP_PUBLICA=127.0.0.1 clase-en-vivo
```

Abra `http://localhost:8080/profesor`.

/* Clase en Vivo UNACHI — panel del profesor: participación y grabación.
   - Mezcla de audio: la transmisión siempre lleva UNA pista de audio que mezcla
     el audio del profesor (micrófono o sistema, si lo eligió) con la voz del
     estudiante que tiene la palabra. Así todos lo escuchan y queda grabado.
   - Chat, manos levantadas, pedidos de palabra y expresiones (Server-Sent Events).
   - Ventana flotante (Document Picture-in-Picture) para verlos mientras se
     comparte otra ventana.
   - Grabación en el servidor (MediaMTX) y descarga de los archivos. */
"use strict";
window.SalaProf = (() => {
  const C = window.CLASE || {};
  const A = window.Aula;
  const $ = (id) => document.getElementById(id);

  // =====================================================================
  // Mezcla de audio
  // =====================================================================
  let ac = null, destino = null, fuenteProf = null, entradaVoz = null, monitor = null;
  let vozReader = null, vozFuente = null, vozElemento = null, pararMedidor = null;

  const asegurarMezcla = () => {
    if (!ac) {
      ac = new AudioContext({ latencyHint: "interactive" });
      destino = ac.createMediaStreamDestination();
      entradaVoz = ac.createGain();             // voz del estudiante
      entradaVoz.connect(destino);
      monitor = ac.createGain();                // el profesor la escucha en su equipo
      monitor.gain.value = el.chkEscuchar?.checked === false ? 0 : 1;
      entradaVoz.connect(monitor);
      monitor.connect(ac.destination);
    }
    if (ac.state === "suspended") ac.resume().catch(() => {});
    return destino.stream.getAudioTracks()[0];
  };

  /** Conecta el audio capturado por el profesor (si lo hay) a la mezcla. */
  const conectarProfesor = (captura) => {
    asegurarMezcla();
    try { fuenteProf?.disconnect(); } catch { /* ya desconectado */ }
    fuenteProf = null;
    const pistas = captura?.getAudioTracks() || [];
    if (pistas.length) {
      fuenteProf = ac.createMediaStreamSource(new MediaStream(pistas));
      fuenteProf.connect(destino);
    }
  };

  const cargarReader = () => new Promise((ok, mal) => {
    if (window.MediaMTXWebRTCReader) return ok();
    // WHIP/WHEP pasan por el mismo servidor web (proxy hacia MediaMTX).
    const base = `${location.origin}/${C.ruta || "clase"}/`;
    const s = document.createElement("script");
    s.src = base + "reader.js";
    s.onload = ok;
    s.onerror = () => { s.remove(); mal(new Error("reader.js")); };
    document.head.appendChild(s);
  });

  /** Recibe el micrófono del estudiante con la palabra (WHEP por /voz/). */
  const escucharVoz = async () => {
    cerrarVoz();
    asegurarMezcla();
    try { await cargarReader(); } catch { return setTimeout(escucharVoz, 3000); }
    if (!hablante) return;
    vozReader = new window.MediaMTXWebRTCReader({
      url: new URL((C.baseVoz || "/voz/") + "whep", location.href).href,
      onError: () => { el.vozEstado.textContent = "Esperando el micrófono del estudiante…"; },
      onTrack: (evt) => {
        if (evt.track.kind !== "audio") return;
        try { vozFuente?.disconnect(); } catch { /* ya desconectado */ }
        // Chrome sólo entrega audio WebRTC a Web Audio si también está
        // asociado a un elemento multimedia (silenciado para no duplicarlo).
        vozElemento = vozElemento || Object.assign(new Audio(), { muted: true, autoplay: true });
        vozElemento.srcObject = evt.streams[0];
        vozElemento.play().catch(() => {});
        vozFuente = ac.createMediaStreamSource(evt.streams[0]);
        vozFuente.connect(entradaVoz);
        pararMedidor?.();
        pararMedidor = A.medidor(ac, vozFuente, (v) => (el.vozNivel.style.width = `${Math.round(v * 100)}%`));
        el.vozEstado.textContent = "Micrófono conectado: su voz va en la transmisión.";
      },
    });
  };

  const cerrarVoz = () => {
    try { vozReader?.close(); } catch { /* ignorar */ }
    vozReader = null;
    try { vozFuente?.disconnect(); } catch { /* ignorar */ }
    vozFuente = null;
    if (vozElemento) vozElemento.srcObject = null;
    pararMedidor?.(); pararMedidor = null;
    if (el.vozNivel) el.vozNivel.style.width = "0";
  };

  // =====================================================================
  // Participación (eventos en vivo)
  // =====================================================================
  const el = {};                    // referencias fijas (también funcionan dentro de la ventana flotante)
  let participantes = [], hablante = null, chatActivo = true, grabando = false, grabDesde = 0, desfase = 0;
  let pendientes = 0;

  const tomarElementos = () => {
    for (const id of ["participacion", "turno", "turnoNombre", "turnoTiempo", "vozNivel", "vozEstado",
      "btnQuitar", "chkEscuchar", "listaPide", "listaManos", "listaTodos", "nPide", "nManos", "nTodos",
      "btnBajarTodas", "chatLista", "chatForm", "chatTexto", "chkChat", "lnkChat", "chkSonido", "chkNotif",
      "btnFlotante", "reacciones", "conexionSala", "btnGrabar", "grabTiempo", "grabLista", "grabNota",
      "insigniaGrab", "vistaContenedor", "tabPart"]) el[id] = $(id);
  };

  // ----- alertas (sonido, título y notificación) -----
  const tituloBase = document.title;
  const pitido = (frec = 880) => {
    if (!el.chkSonido.checked) return;
    try {
      const ctx = ac || new AudioContext();
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.frequency.value = frec; g.gain.value = 0.0001;
      o.connect(g); g.connect(ctx.destination);
      const t = ctx.currentTime;
      g.gain.exponentialRampToValueAtTime(0.25, t + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.35);
      o.start(t); o.stop(t + 0.4);
    } catch { /* sin audio */ }
  };
  const alertar = (texto, frec) => {
    pitido(frec);
    if (document.hidden) {
      pendientes++;
      document.title = `(${pendientes}) ${texto}`;
      if (el.chkNotif.checked && "Notification" in window && Notification.permission === "granted") {
        try { new Notification("Clase en Vivo", { body: texto, tag: "clase-" + Date.now(), silent: true }); } catch { /* ignorar */ }
      }
    }
  };
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) { pendientes = 0; document.title = tituloBase; }
  });

  // ----- listas de participantes -----
  const fila = (p, botones) => `
    <li data-id="${A.esc(p.id)}"><span class="nom">${A.esc(p.nombre)}</span>
      ${p.mano ? '<span title="Mano levantada">✋</span>' : ""}${p.pide ? '<span title="Pide la palabra">🎤</span>' : ""}
      <span class="acc">${botones}</span></li>`;
  const pintarParticipantes = () => {
    const pide = participantes.filter((p) => p.pide).sort((a, b) => a.pide - b.pide);
    const manos = participantes.filter((p) => p.mano && !p.pide).sort((a, b) => a.mano - b.mano);
    const dar = '<button class="btn mini" data-a="dar" title="Dar la palabra">Dar la palabra</button>';
    el.listaPide.innerHTML = pide.map((p) => fila(p, dar +
      '<button class="btn mini sec" data-a="rechazar" title="Descartar el pedido">✕</button>')).join("")
      || '<li class="vacio">Nadie ha pedido la palabra.</li>';
    el.listaManos.innerHTML = manos.map((p) => fila(p, dar +
      '<button class="btn mini sec" data-a="bajar">Bajar</button>')).join("")
      || '<li class="vacio">No hay manos levantadas.</li>';
    el.listaTodos.innerHTML = participantes.map((p) => fila(p,
      hablante?.id === p.id ? "<b>🎤 hablando</b>" : '<button class="btn mini sec" data-a="dar">Dar la palabra</button>')).join("")
      || '<li class="vacio">Todavía no hay estudiantes conectados.</li>';
    el.nPide.textContent = el.nPide.dataset.n = pide.length;
    el.nManos.textContent = el.nManos.dataset.n = manos.length;
    el.nTodos.textContent = participantes.length;
    el.btnBajarTodas.classList.toggle("oculto", !participantes.some((p) => p.mano));
    const n = pide.length + manos.length;
    el.tabPart.textContent = el.tabPart.dataset.n = n;
  };
  const clicLista = async (e) => {
    const b = e.target.closest("button[data-a]");
    if (!b) return;
    const id = b.closest("li").dataset.id;
    const tipo = { dar: "dar", rechazar: "rechazar", bajar: "bajarMano" }[b.dataset.a];
    const r = await A.accion({ rol: "prof", tipo, id });
    if (!r.ok) avisoBreve(r.error);
  };
  // Mensaje breve dentro del recuadro (los alert() no se ven en la ventana flotante).
  let relojAviso = null;
  const avisoBreve = (t) => {
    el.conexionSala.textContent = t;
    clearTimeout(relojAviso);
    relojAviso = setTimeout(() => (el.conexionSala.textContent = ""), 5000);
  };

  // ----- turno de palabra -----
  let relojTurno = null;
  const pintarHablante = () => {
    el.turno.classList.toggle("oculto", !hablante);
    clearInterval(relojTurno);
    if (hablante) {
      el.turnoNombre.textContent = hablante.nombre;
      const pinta = () => (el.turnoTiempo.textContent = A.mmss((Date.now() / 1000 + desfase - hablante.desde) * 1000));
      pinta(); relojTurno = setInterval(pinta, 1000);
      el.vozEstado.textContent = "Esperando que el estudiante active su micrófono…";
      escucharVoz();
    } else {
      cerrarVoz();
    }
    pintarParticipantes();
  };

  // ----- chat -----
  const pintarMensaje = (m) => {
    const div = document.createElement("div");
    div.className = `chat-msg ${m.rol}${m.borrado ? " borrado" : ""}`;
    div.dataset.id = m.id;
    if (m.rol === "sistema") div.textContent = m.texto;
    else div.innerHTML = `<div class="quien">${A.esc(m.rol === "prof" ? "Profesor" : m.nombre)}<time>${A.hora(m.t)}</time></div>
      <div class="texto">${m.borrado ? "Mensaje eliminado por el profesor" : A.esc(m.texto)}</div>
      ${m.borrado || m.rol === "sistema" ? "" : '<button class="borrar" title="Eliminar mensaje">✕</button>'}`;
    const abajo = el.chatLista.scrollHeight - el.chatLista.scrollTop - el.chatLista.clientHeight < 60;
    el.chatLista.appendChild(div);
    while (el.chatLista.children.length > 400) el.chatLista.firstChild.remove();
    if (abajo) el.chatLista.scrollTop = el.chatLista.scrollHeight;
  };

  // ----- grabación -----
  let relojGrab = null;
  const pintarGrabando = () => {
    el.btnGrabar.textContent = grabando ? "■ Detener grabación" : "● Iniciar grabación";
    el.btnGrabar.classList.toggle("rojo", !grabando);
    el.insigniaGrab.classList.toggle("oculto", !grabando);
    clearInterval(relojGrab);
    if (grabando) {
      const pinta = () => (el.grabTiempo.textContent = "Grabando " + A.mmss((Date.now() / 1000 + desfase - grabDesde) * 1000));
      pinta(); relojGrab = setInterval(pinta, 1000);
    } else el.grabTiempo.textContent = "";
  };
  const tamano = (b) => b >= 1e9 ? (b / 1e9).toFixed(2) + " GB" : (b / 1e6).toFixed(1) + " MB";
  const cargarGrabaciones = async () => {
    try {
      const r = await fetch("/api/grabaciones", { cache: "no-store" });
      if (!r.ok) return;
      const d = await r.json();
      el.grabLista.innerHTML = d.archivos.length ? d.archivos.map((f) => `
        <li><span class="nom" title="${A.esc(f.nombre)}">${A.esc(f.nombre.replace(/^clase_/, "").replace(/\.mp4$/, "").replace("_", " · "))}</span>
          <span class="tam">${tamano(f.bytes)}${f.enCurso ? " · en curso" : ""}</span>
          <span class="acc"><a class="btn mini sec" href="/grabaciones/${encodeURIComponent(f.nombre)}" download>Descargar</a>
          ${f.enCurso ? "" : `<button class="btn mini sec" data-borrar="${A.esc(f.nombre)}" title="Eliminar del servidor">🗑</button>`}</span></li>`).join("")
        : '<li class="vacio">Aún no hay grabaciones.</li>';
      el.grabNota.textContent = C.online
        ? "Los archivos quedan en el servidor; descárguelos y elimínelos cuando ya no los necesite."
        : `También están en la carpeta: ${d.carpeta}`;
    } catch { /* servidor detenido */ }
  };

  // ----- eventos del servidor -----
  const manejar = (ev) => {
    switch (ev.tipo) {
      case "estado":
        desfase = ev.ahora - Date.now() / 1000;
        el.chatLista.innerHTML = "";
        ev.mensajes.forEach(pintarMensaje);
        chatActivo = ev.chatActivo; el.chkChat.checked = chatActivo;
        participantes = ev.participantes || [];
        hablante = ev.hablante; pintarHablante();
        grabando = ev.grabando; grabDesde = ev.grabDesde; pintarGrabando();
        break;
      case "participantes": participantes = ev.lista; pintarParticipantes(); break;
      case "msg":
        pintarMensaje(ev.m);
        if (ev.m.rol === "est") alertar(`💬 ${ev.m.nombre}: ${ev.m.texto}`.slice(0, 80), 660);
        break;
      case "borrado": {
        const d = el.chatLista.querySelector(`[data-id="${ev.id}"]`);
        if (d) { d.classList.add("borrado"); d.querySelector(".texto").textContent = "Mensaje eliminado por el profesor"; d.querySelector(".borrar")?.remove(); }
        break;
      }
      case "chatActivo": chatActivo = ev.on; el.chkChat.checked = ev.on; break;
      case "reaccion":
        A.flotar(el.vistaContenedor, ev.emoji, ev.nombre);
        A.flotar(el.reacciones, ev.emoji, ev.nombre);
        break;
      case "hablante": hablante = ev.h; pintarHablante(); break;
      case "grabando":
        desfase = ev.ahora - Date.now() / 1000;
        grabando = ev.on; grabDesde = ev.desde; pintarGrabando(); cargarGrabaciones();
        break;
      case "alerta":
        alertar(ev.clase === "mano" ? `✋ ${ev.nombre} levantó la mano` : `🎤 ${ev.nombre} pide la palabra`,
                ev.clase === "mano" ? 880 : 990);
        break;
    }
  };

  // ----- ventana flotante (Document Picture-in-Picture, Chrome/Edge 116+) -----
  const abrirFlotante = async () => {
    const lugar = document.createComment("participacion");
    el.participacion.before(lugar);
    const w = await window.documentPictureInPicture.requestWindow({ width: 420, height: 640 });
    for (const hoja of document.styleSheets) {
      try {
        const st = w.document.createElement("style");
        st.textContent = [...hoja.cssRules].map((r) => r.cssText).join("\n");
        w.document.head.appendChild(st);
      } catch {
        if (hoja.href) w.document.head.appendChild(Object.assign(w.document.createElement("link"), { rel: "stylesheet", href: hoja.href }));
      }
    }
    w.document.title = "Participación · Clase en Vivo";
    w.document.body.classList.add("flotante-body");
    w.document.body.appendChild(el.participacion);
    el.btnFlotante.classList.add("oculto");
    w.addEventListener("pagehide", () => {
      lugar.replaceWith(el.participacion);
      el.btnFlotante.classList.remove("oculto");
    });
  };

  // ----- inicio -----
  const iniciar = () => {
    tomarElementos();
    // Cualquier clic en el panel reactiva el audio si el navegador lo suspendió.
    document.addEventListener("click", () => { if (ac && ac.state === "suspended") ac.resume().catch(() => {}); });
    [el.listaPide, el.listaManos, el.listaTodos].forEach((l) => l.addEventListener("click", clicLista));
    el.btnQuitar.onclick = () => A.accion({ rol: "prof", tipo: "quitar" });
    el.btnBajarTodas.onclick = () => A.accion({ rol: "prof", tipo: "bajarMano" });
    el.chkEscuchar.onchange = () => { if (monitor) monitor.gain.value = el.chkEscuchar.checked ? 1 : 0; };
    el.chkChat.onchange = () => A.accion({ rol: "prof", tipo: "chatActivo", on: el.chkChat.checked });
    el.chatForm.onsubmit = async (e) => {
      e.preventDefault();
      const texto = el.chatTexto.value.trim();
      if (!texto) return;
      el.chatTexto.value = "";
      const r = await A.accion({ rol: "prof", tipo: "chat", texto });
      if (!r.ok) { el.chatTexto.value = texto; avisoBreve(r.error); }
    };
    el.chatLista.addEventListener("click", (e) => {
      const b = e.target.closest(".borrar");
      if (b) A.accion({ rol: "prof", tipo: "borrar", id: +b.closest(".chat-msg").dataset.id });
    });
    el.lnkChat.href = "/api/chat.txt";
    try { el.chkSonido.checked = localStorage.getItem("clase:sonido") !== "0"; } catch { /* ignorar */ }
    el.chkSonido.onchange = () => { try { localStorage.setItem("clase:sonido", el.chkSonido.checked ? "1" : "0"); } catch { /* ignorar */ } };
    if (!("Notification" in window)) el.chkNotif.closest("label").classList.add("oculto");
    else el.chkNotif.checked = Notification.permission === "granted";
    el.chkNotif.onchange = async () => {
      if (el.chkNotif.checked && Notification.permission !== "granted") {
        el.chkNotif.checked = (await Notification.requestPermission()) === "granted";
      }
    };
    if ("documentPictureInPicture" in window) {
      el.btnFlotante.classList.remove("oculto");
      el.btnFlotante.onclick = () => abrirFlotante().catch((e) => avisoBreve("No se pudo abrir la ventana flotante: " + e.message));
    }
    el.btnGrabar.onclick = async () => {
      if (!grabando && !confirm("Se grabará en el servidor lo que reciben los estudiantes (pantalla, audio y la voz de quien tenga la palabra).\n" +
          "Los estudiantes verán el aviso «Grabando».\n\n¿Iniciar la grabación?")) return;
      el.btnGrabar.disabled = true;
      const r = await A.accion({ rol: "prof", tipo: "grabar", on: !grabando });
      el.btnGrabar.disabled = false;
      if (!r.ok) alert("No se pudo cambiar la grabación: " + r.error);
    };
    el.grabLista.addEventListener("click", async (e) => {
      const b = e.target.closest("[data-borrar]");
      if (!b || !confirm(`¿Eliminar definitivamente «${b.dataset.borrar}» del servidor?`)) return;
      await fetch("/api/grabaciones/" + encodeURIComponent(b.dataset.borrar), { method: "DELETE" });
      cargarGrabaciones();
    });
    setInterval(cargarGrabaciones, 15000);
    cargarGrabaciones();
    A.eventos("/eventos?rol=prof", manejar, (ok) => {
      el.conexionSala.textContent = ok ? "" : "Reconectando con el servidor…";
    });
  };

  return {
    iniciar,
    /** Pista de audio mezclada que se publica junto al video. */
    /** Crea (o reactiva) el contexto de audio; llamar dentro de un clic. */
    preparar: () => { asegurarMezcla(); },
    // Se entrega un clon: cerrar una sesión de publicación no apaga la mezcla.
    pistaAudio: () => asegurarMezcla().clone(),
    conectarProfesor,
  };
})();

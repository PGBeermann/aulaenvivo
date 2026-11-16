/* Clase en Vivo UNACHI — utilidades compartidas por el panel del profesor y
   la página del estudiante (chat, expresiones y turno de palabra). */
"use strict";
window.Aula = (() => {
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const hora = (t) => new Date(t * 1000).toLocaleTimeString("es-PA", { hour: "2-digit", minute: "2-digit" });
  const mmss = (ms) => {
    const s = Math.max(0, Math.floor(ms / 1000)), h = Math.floor(s / 3600);
    const mm = String(Math.floor((s % 3600) / 60)).padStart(2, "0"), ss = String(s % 60).padStart(2, "0");
    return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
  };

  const EXPRESIONES = [
    ["👍", "De acuerdo"], ["👏", "Aplausos"], ["😂", "Risa"], ["😮", "Sorpresa"],
    ["❤️", "Me gusta"], ["🤔", "Tengo una duda"], ["🐢", "Más despacio"], ["🔁", "¿Puede repetir?"],
  ];

  /** POST /api/accion con JSON. Devuelve {ok, error}. */
  const accion = async (datos) => {
    try {
      const r = await fetch("/api/accion", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(datos), credentials: "same-origin",
      });
      const j = await r.json().catch(() => ({}));
      return r.ok ? { ok: true } : { ok: false, error: j.error || `Error ${r.status}`, status: r.status };
    } catch {
      return { ok: false, error: "Sin conexión con el servidor" };
    }
  };

  /** Conexión de eventos (Server-Sent Events) con reconexión automática. */
  const eventos = (url, manejar, alCambiarEstado = () => {}) => {
    let es = null, cerrado = false;
    const abrir = () => {
      es = new EventSource(url);
      es.onopen = () => alCambiarEstado(true);
      es.onmessage = (e) => { try { manejar(JSON.parse(e.data)); } catch (err) { console.error(err); } };
      es.onerror = () => {
        alCambiarEstado(false);
        // EventSource reintenta solo; si el servidor respondió con error (p. ej. 401), se reabre más tarde.
        if (es.readyState === EventSource.CLOSED && !cerrado) setTimeout(abrir, 4000);
      };
    };
    abrir();
    return { cerrar: () => { cerrado = true; es?.close(); } };
  };

  /** Medidor de nivel (0..1) de una pista o nodo de audio. */
  const medidor = (ac, nodo, pintar) => {
    const an = ac.createAnalyser();
    an.fftSize = 512;
    nodo.connect(an);
    const buf = new Uint8Array(an.fftSize);
    let vivo = true;
    const paso = () => {
      if (!vivo) return;
      an.getByteTimeDomainData(buf);
      let pico = 0;
      for (const v of buf) pico = Math.max(pico, Math.abs(v - 128));
      pintar(Math.min(1, pico / 90));
      setTimeout(paso, 100); // setTimeout (no requestAnimationFrame): sigue en pestañas ocultas
    };
    paso();
    return () => { vivo = false; try { nodo.disconnect(an); } catch { /* ya desconectado */ } };
  };

  /** Emoji flotante sobre un contenedor (reacciones). */
  const flotar = (contenedor, emoji, nombre) => {
    const el = document.createElement("div");
    el.className = "flotante";
    el.style.left = `${8 + Math.random() * 70}%`;
    el.innerHTML = `<span class="e">${esc(emoji)}</span><span class="n">${esc(nombre)}</span>`;
    contenedor.appendChild(el);
    setTimeout(() => el.remove(), 4200);
  };

  return { esc, hora, mmss, EXPRESIONES, accion, eventos, medidor, flotar };
})();

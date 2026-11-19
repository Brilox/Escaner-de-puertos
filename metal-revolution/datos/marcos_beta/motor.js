/* Motor de animacion de los marcos beta de Metal Online.
   Cada marco es su imagen (256x256, ventana del avatar transparente) mas efectos dibujados encima en un canvas.
   Todas las coordenadas estan en el espacio de 256x256 de la imagen. */
const Motor = (() => {
  const W = 256;
  const META = {
    founder:   { win: [51.2, 53.9, 153.6, 147.2] },
    bughunter: { win: [51.2, 51.2, 153.6, 153.6] },
    vanguard:  { win: [54.2, 51.6, 148.4, 153.8] },
    patcher:   { win: [54.2, 51.2, 147.6, 153.6] },
    hero:      { win: [50.1, 44.0, 154.8, 168.0] },
  };
  const rnd = (a, b) => a + Math.random() * (b - a);
  const cv = (w, h = w) => { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; };

  // ---------- utilidades de imagen
  function soft(src, f) {           // desenfoque barato: achicar y volver a agrandar (funciona en todos los navegadores)
    const s = cv(Math.max(2, Math.round(W / f))); const x = s.getContext('2d');
    x.imageSmoothingEnabled = true; x.imageSmoothingQuality = 'high'; x.drawImage(src, 0, 0, s.width, s.height); return s;
  }
  function emissive(img, test) {    // capa con solo los pixeles que brillan (segun el color del diseno)
    const c = cv(W), x = c.getContext('2d'); x.drawImage(img, 0, 0, W, W);
    const d = x.getImageData(0, 0, W, W), p = d.data, pts = [];
    for (let i = 0; i < p.length; i += 4) {
      const k = p[i + 3] > 40 ? test(p[i], p[i + 1], p[i + 2]) : 0;
      if (k > 0) { p[i + 3] *= Math.min(1, k); if (k > .7 && Math.random() < .35) pts.push([(i / 4) % W, ((i / 4) / W) | 0]); }
      else p[i + 3] = 0;
    }
    x.putImageData(d, 0, 0);
    return { c, s1: soft(c, 5), s2: soft(c, 14), pts };
  }
  function glow(ctx, m, a, core = .45) {
    ctx.save(); ctx.globalCompositeOperation = 'lighter';
    ctx.globalAlpha = Math.max(0, a); ctx.drawImage(m.s1, 0, 0, W, W);
    ctx.globalAlpha = Math.max(0, a * .8); ctx.drawImage(m.s2, 0, 0, W, W);
    ctx.globalAlpha = Math.max(0, a * core); ctx.drawImage(m.c, 0, 0, W, W);
    ctx.restore();
  }
  function sheen(st, ctx, t, period, rgb, alpha, width = 34) {   // reflejo que barre el metal (solo sobre el marco)
    const x = st.tmp.getContext('2d'); x.globalCompositeOperation = 'source-over'; x.clearRect(0, 0, W, W);
    const u = ((t % period) / period) * 1.8 - .4, cx = u * W * 1.4 - W * .2;
    const g = x.createLinearGradient(cx - width, cx - width - 60, cx + width, cx + width - 60);
    g.addColorStop(0, `rgba(${rgb},0)`); g.addColorStop(.5, `rgba(${rgb},1)`); g.addColorStop(1, `rgba(${rgb},0)`);
    x.fillStyle = g; x.fillRect(0, 0, W, W);
    x.globalCompositeOperation = 'destination-in'; x.drawImage(st.img, 0, 0, W, W);
    ctx.save(); ctx.globalCompositeOperation = 'lighter'; ctx.globalAlpha = alpha; ctx.drawImage(st.tmp, 0, 0); ctx.restore();
  }
  function band(st, ctx, m, pos, axis, size, alpha) {           // ola de luz que recorre una capa brillante
    const x = st.tmp.getContext('2d'); x.globalCompositeOperation = 'source-over'; x.clearRect(0, 0, W, W);
    x.drawImage(m.c, 0, 0); x.globalCompositeOperation = 'source-in';
    const g = axis === 'y' ? x.createLinearGradient(0, pos - size, 0, pos + size) : x.createLinearGradient(pos - size, 0, pos + size, 0);
    g.addColorStop(0, 'rgba(255,255,255,0)'); g.addColorStop(.5, 'rgba(255,255,255,1)'); g.addColorStop(1, 'rgba(255,255,255,0)');
    x.fillStyle = g; x.fillRect(0, 0, W, W);
    ctx.save(); ctx.globalCompositeOperation = 'lighter'; ctx.globalAlpha = alpha; ctx.drawImage(st.tmp, 0, 0);
    ctx.globalAlpha = alpha * .8; ctx.drawImage(soft(st.tmp, 6), 0, 0, W, W); ctx.restore();
  }
  function rectPath(r) {                                         // punto a lo largo del borde de un rectangulo (u de 0 a 1)
    const [x, y, w, h] = r, P = 2 * (w + h);
    return u => {
      let d = ((u % 1) + 1) % 1 * P;
      if (d < w) return [x + d, y, 0];
      d -= w; if (d < h) return [x + w, y + d, 1];
      d -= h; if (d < w) return [x + w - d, y + h, 2];
      d -= w; return [x, y + h - d, 3];
    };
  }
  const grow = (r, e) => [r[0] - e, r[1] - e, r[2] + 2 * e, r[3] + 2 * e];

  // ---------- particulas (chispas, llamas, brasas)
  function stepParticles(ctx, list, dt, drawFn) {
    ctx.save(); ctx.globalCompositeOperation = 'lighter';
    for (let i = list.length - 1; i >= 0; i--) {
      const p = list[i]; p.life -= dt;
      if (p.life <= 0) { list.splice(i, 1); continue; }
      p.vx += (p.ax || 0) * dt; p.vy += (p.ay || 0) * dt; p.x += p.vx * dt; p.y += p.vy * dt;
      drawFn(ctx, p, p.life / p.max);
    }
    ctx.restore();
  }

  // ================================================================ DISENOS
  const DISENOS = {
    // ---- FOUNDER: cobre y engranajes. Luces naranjas que laten y recorren las barras, destellos que giran en los
    //      engranajes y chispas de soldadura en las esquinas.
    founder: {
      init(st) {
        st.m = emissive(st.img, (r, g, b) => (r > 170 && g > 80 && b < 120 && r - b > 110) ? (r + g - 230) / 160 : 0);
        st.p = []; st.next = 0;
        st.em = [[22, 178, -1], [236, 165, 1], [204, 20, 1]];
        st.gears = [[55, 191, 22], [129, 193, 20], [203, 191, 22], [44, 24, 18], [200, 36, 17]];
      },
      draw(ctx, st, t, dt) {
        glow(ctx, st.m, .38 + .22 * Math.sin(t * 3.2));
        band(st, ctx, st.m, ((t * 90) % 360) - 50, 'y', 26, .9);
        sheen(st, ctx, t, 4.2, '255,214,170', .35);
        ctx.save(); ctx.globalCompositeOperation = 'lighter';
        st.gears.forEach(([x, y, r], i) => {                     // destello que da vueltas sobre cada engranaje
          const a = t * (i % 2 ? -1.6 : 1.6) + i;
          const g = ctx.createRadialGradient(x + Math.cos(a) * r * .75, y + Math.sin(a) * r * .75, 0, x + Math.cos(a) * r * .75, y + Math.sin(a) * r * .75, 9);
          g.addColorStop(0, 'rgba(255,220,160,.75)'); g.addColorStop(1, 'rgba(255,160,60,0)');
          ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, r + 4, 0, 7); ctx.fill();
        });
        ctx.restore();
        if (t > st.next) {                                       // rafaga de chispas
          const [ex, ey, dir] = st.em[(Math.random() * st.em.length) | 0];
          for (let i = 0; i < 14; i++) {
            const sp = rnd(50, 150), an = rnd(-2.6, -.4);
            st.p.push({ x: ex, y: ey, vx: Math.cos(an) * sp * .55 * dir + rnd(-15, 15), vy: Math.sin(an) * sp, ay: 260, life: rnd(.35, .8), max: .8 });
          }
          st.next = t + rnd(.25, .9);
        }
        stepParticles(ctx, st.p, dt, (c, p, k) => {
          c.strokeStyle = `rgba(255,${(170 + 80 * k) | 0},${(80 * k) | 0},${k})`; c.lineWidth = 1.4;
          c.beginPath(); c.moveTo(p.x, p.y); c.lineTo(p.x - p.vx * .035, p.y - p.vy * .035); c.stroke();
        });
      },
    },

    // ---- BUG HUNTER: neon verde que parpadea, barras de glitch en los bordes de la ventana, el marco que "falla"
    //      cada tanto y una arana que camina por el borde.
    bughunter: {
      init(st) {
        st.m = emissive(st.img, (r, g, b) => (g > 140 && g - r > 50 && g - b > 40) ? (g - 110) / 120 : 0);
        st.bars = []; st.glitchUntil = 0; st.nextGlitch = 2;
        st.path = rectPath([36, 36, 184, 184]); st.u = .1; st.pause = 0;
      },
      draw(ctx, st, t, dt) {
        const flick = Math.random() < .06 ? .15 : 1;
        glow(ctx, st.m, (.45 + .2 * Math.sin(t * 7)) * flick, .6);
        const [wx, wy, ww, wh] = META.bughunter.win;
        if (Math.random() < dt * 9) {                            // barras de datos verdes (como en el diseno)
          const left = Math.random() < .5;
          st.bars.push({ x: left ? wx : wx + ww, y: rnd(wy + 12, wy + wh - 30), w: rnd(14, 46) * (left ? 1 : -1), h: rnd(2, 6), life: rnd(.08, .32) });
        }
        ctx.save(); ctx.globalCompositeOperation = 'lighter';
        for (let i = st.bars.length - 1; i >= 0; i--) {
          const b = st.bars[i]; b.life -= dt; if (b.life <= 0) { st.bars.splice(i, 1); continue; }
          ctx.fillStyle = 'rgba(70,255,90,.55)'; ctx.fillRect(Math.min(b.x, b.x + b.w), b.y, Math.abs(b.w), b.h);
          ctx.fillStyle = 'rgba(200,255,200,.9)'; ctx.fillRect(Math.min(b.x, b.x + b.w * .4), b.y + b.h * .35, Math.abs(b.w * .4), Math.max(1, b.h * .3));
        }
        const sy = (t * 70) % 300 - 20;                          // linea de escaneo
        const g = ctx.createLinearGradient(0, sy - 6, 0, sy + 6);
        g.addColorStop(0, 'rgba(80,255,120,0)'); g.addColorStop(.5, 'rgba(80,255,120,.35)'); g.addColorStop(1, 'rgba(80,255,120,0)');
        ctx.fillStyle = g; ctx.fillRect(wx, sy - 6, ww, 12);
        ctx.restore();
        if (t > st.nextGlitch) { st.glitchUntil = t + rnd(.12, .25); st.nextGlitch = t + rnd(1.8, 3.5); }
        if (t < st.glitchUntil) {                                // falla: franjas del marco corridas y un fantasma verde
          for (let i = 0; i < 7; i++) {
            const y = rnd(0, W - 10), h = rnd(3, 12), dx = rnd(-6, 6);
            ctx.drawImage(st.img, 0, y, W, h, dx, y, W, h);
          }
          ctx.save(); ctx.globalCompositeOperation = 'lighter'; ctx.globalAlpha = .5; ctx.drawImage(st.m.c, rnd(-4, 4), 0); ctx.restore();
        }
        // arana caminando por el borde; se detiene de vez en cuando
        if (st.pause > 0) st.pause -= dt; else { st.u += dt * .045; if (Math.random() < dt * .4) st.pause = rnd(.4, 1.2); }
        const [x, y, side] = st.path(st.u), ang = [0, Math.PI / 2, Math.PI, -Math.PI / 2][side], walk = st.pause > 0 ? 0 : t * 22;
        ctx.save(); ctx.translate(x, y); ctx.rotate(ang);
        ctx.strokeStyle = '#0d140d'; ctx.lineWidth = 1.3; ctx.lineCap = 'round';
        for (let s = -1; s <= 1; s += 2) for (let k = 0; k < 4; k++) {
          const sw = Math.sin(walk + k * 1.7 + (s > 0 ? Math.PI : 0)) * 2.2, bx = -3 + k * 2.2;
          ctx.beginPath(); ctx.moveTo(bx, 0); ctx.lineTo(bx + sw, s * 5); ctx.lineTo(bx + sw * 1.4 + (k - 1.5) * 1.6, s * 8.5); ctx.stroke();
        }
        ctx.fillStyle = '#1b2a1b'; ctx.beginPath(); ctx.ellipse(-1, 0, 5.2, 4, 0, 0, 7); ctx.fill();
        ctx.fillStyle = '#2c4a2c'; ctx.beginPath(); ctx.ellipse(4.5, 0, 2.8, 2.6, 0, 0, 7); ctx.fill();
        ctx.globalCompositeOperation = 'lighter'; ctx.fillStyle = '#7dff7a';
        ctx.shadowColor = '#5dff5a'; ctx.shadowBlur = 5;
        ctx.beginPath(); ctx.arc(6, -1.2, .9, 0, 7); ctx.arc(6, 1.2, .9, 0, 7); ctx.fill();
        ctx.restore();
      },
    },

    // ---- BETA VANGUARD: rayos azules que recorren el borde exterior, gemas que laten y un reflejo frio sobre el acero.
    vanguard: {
      init(st) {
        st.m = emissive(st.img, (r, g, b) => (b > 200 && g > 140 && r < 190) ? (b + g - 330) / 150 : 0);
        st.edge = rectPath([22, 16, 216, 212]); st.bolts = []; st.next = 0;
        st.gems = [[44, 44], [213, 43], [44, 218], [213, 218], [128, 222], [128, 46]];
      },
      draw(ctx, st, t, dt) {
        glow(ctx, st.m, .4 + .15 * Math.sin(t * 2.4), .5);
        sheen(st, ctx, t, 3.4, '190,225,255', .3, 26);
        ctx.save(); ctx.globalCompositeOperation = 'lighter';
        st.gems.forEach(([x, y], i) => {
          const k = .5 + .5 * Math.sin(t * 4 + i * 1.1);
          const g = ctx.createRadialGradient(x, y, 0, x, y, 14);
          g.addColorStop(0, `rgba(200,240,255,${.75 * k})`); g.addColorStop(1, 'rgba(40,140,255,0)');
          ctx.fillStyle = g; ctx.fillRect(x - 14, y - 14, 28, 28);
        });
        if (t > st.next) {                                       // rayo nuevo sobre un tramo del borde
          const u0 = Math.random(), len = rnd(.05, .13), pts = [], n = 10;
          for (let i = 0; i <= n; i++) {
            const [x, y, side] = st.edge(u0 + len * i / n), off = (i === 0 || i === n) ? 0 : rnd(-7, 7);
            pts.push(side % 2 ? [x + off, y] : [x, y + off]);
          }
          st.bolts.push({ pts, life: rnd(.12, .3) }); st.next = t + rnd(.04, .14);
        }
        for (let i = st.bolts.length - 1; i >= 0; i--) {
          const b = st.bolts[i]; b.life -= dt; if (b.life <= 0) { st.bolts.splice(i, 1); continue; }
          if (Math.random() < .5) b.pts = b.pts.map(([x, y], j) => (j && j < b.pts.length - 1) ? [x + rnd(-1.5, 1.5), y + rnd(-1.5, 1.5)] : [x, y]);
          ctx.beginPath(); b.pts.forEach(([x, y], j) => j ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
          ctx.shadowColor = '#3aa8ff'; ctx.shadowBlur = 10;
          ctx.strokeStyle = 'rgba(70,160,255,.7)'; ctx.lineWidth = 3.2; ctx.stroke();
          ctx.shadowBlur = 0; ctx.strokeStyle = 'rgba(235,250,255,.95)'; ctx.lineWidth = 1.1; ctx.stroke();
        }
        ctx.restore();
      },
    },

    // ---- ELITE PATCHER: pulsos de datos que viajan por los dos bordes de circuito, brillo violeta que respira y
    //      destellos en los triangulos de las esquinas.
    patcher: {
      init(st) {
        st.m = emissive(st.img, (r, g, b) => (r > 150 && b > 170 && g < 150 && b - g > 70) ? (r + b - 300) / 180 : 0);
        st.paths = [rectPath(grow(META.patcher.win, 7)), rectPath([20, 20, 216, 214])];
        st.trail = [[], []];
        st.corners = [[16, 18], [240, 18], [16, 238], [240, 238]];
      },
      draw(ctx, st, t, dt) {
        glow(ctx, st.m, .42 + .25 * Math.sin(t * 1.8), .55);
        ctx.save(); ctx.globalCompositeOperation = 'lighter';
        st.paths.forEach((path, k) => {
          for (let c = 0; c < 2; c++) {                          // dos pulsos por borde, en sentidos opuestos
            const u = (k ? -1 : 1) * t * (k ? .16 : .22) + c * .5;
            for (let j = 0; j < 16; j++) {
              const [x, y] = path(u - j * .004 * (k ? -1 : 1)), a = (1 - j / 16);
              ctx.fillStyle = j ? `rgba(230,120,255,${.55 * a})` : 'rgba(255,240,255,1)';
              ctx.beginPath(); ctx.arc(x, y, j ? 2.4 * a + .6 : 2.6, 0, 7); ctx.fill();
            }
            const [hx, hy] = path(u); const g = ctx.createRadialGradient(hx, hy, 0, hx, hy, 12);
            g.addColorStop(0, 'rgba(240,150,255,.7)'); g.addColorStop(1, 'rgba(180,60,255,0)');
            ctx.fillStyle = g; ctx.fillRect(hx - 12, hy - 12, 24, 24);
          }
        });
        st.corners.forEach(([x, y], i) => {
          const k = Math.max(0, Math.sin(t * 2.2 - i * 1.57)) ** 6;
          const g = ctx.createRadialGradient(x, y, 0, x, y, 16);
          g.addColorStop(0, `rgba(255,255,255,${.9 * k})`); g.addColorStop(1, 'rgba(200,120,255,0)');
          ctx.fillStyle = g; ctx.fillRect(x - 16, y - 16, 32, 32);
        });
        ctx.restore();
      },
    },

    // ---- REVOLUTION HERO: lava que late, llamas que salen de las grietas y brasas que suben.
    hero: {
      init(st) {
        st.m = emissive(st.img, (r, g, b) => (r > 190 && b < 110 && r - b > 120) ? (r + g * .6 - 230) / 140 : 0);
        st.p = []; st.e = [];
      },
      draw(ctx, st, t, dt) {
        glow(ctx, st.m, .45 + .18 * Math.sin(t * 5) + .1 * Math.sin(t * 13.7), .5);
        const pts = st.m.pts;
        for (let i = 0; i < 70 * dt * 6 && pts.length; i++) {   // llamas sobre los pixeles de lava
          const [x, y] = pts[(Math.random() * pts.length) | 0];
          st.p.push({ x, y, vx: rnd(-6, 6), vy: rnd(-38, -16), ay: -20, life: rnd(.3, .7), max: .7, s: rnd(2.5, 5.5) });
        }
        if (Math.random() < dt * 8) st.e.push({ x: rnd(20, 236), y: rnd(150, 250), vx: rnd(-8, 8), vy: rnd(-45, -25), life: rnd(1.2, 2.4), max: 2.4, ph: rnd(0, 6) });
        stepParticles(ctx, st.p, dt, (c, p, k) => {
          const g = c.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.s * (1.4 - k * .4));
          g.addColorStop(0, `rgba(255,${(200 * k + 40) | 0},${(90 * k) | 0},${.55 * k})`); g.addColorStop(1, 'rgba(255,60,0,0)');
          c.fillStyle = g; c.fillRect(p.x - 8, p.y - 8, 16, 16);
        });
        stepParticles(ctx, st.e, dt, (c, p, k) => {
          p.x += Math.sin(t * 3 + p.ph) * .25;
          c.fillStyle = `rgba(255,${(150 + 90 * k) | 0},80,${Math.min(1, k * 1.5)})`;
          c.beginPath(); c.arc(p.x, p.y, 1.1 + k * .6, 0, 7); c.fill();
        });
      },
    },
  };

  // ================================================================ instancia
  function crear(canvas, nombre, opciones = {}) {
    const st = { img: opciones.img, avatar: opciones.avatar || null, tmp: cv(W), t0: null, last: 0, nombre };
    DISENOS[nombre].init(st);
    const ctx = canvas.getContext('2d');
    function render(t, dt) {
      const q = canvas.width / W;
      ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.setTransform(q, 0, 0, q, 0, 0);
      if (st.avatar) {
        const [x, y, w, h] = META[nombre].win;
        ctx.drawImage(st.avatar, x - 4, y - 4, w + 8, h + 8);
      }
      ctx.drawImage(st.img, 0, 0, W, W);
      if (!opciones.quieto) DISENOS[nombre].draw(ctx, st, t, Math.min(dt, .05));
    }
    return { render, st };
  }
  function cargar(src) { return new Promise((ok, mal) => { const i = new Image(); i.onload = () => ok(i); i.onerror = mal; i.src = src; }); }
  return { crear, cargar, META, W };
})();

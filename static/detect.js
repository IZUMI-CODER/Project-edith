/* Hands-free trigger shared by the pages: decides WHEN to send a frame.
   Real webcams flicker (auto-exposure), hunt for focus and add noise, so every frame is contrast-normalised before it is compared. */
window.LensDetect = (function () {
  function create(opt) {
    const video = opt.video, W = 96, H = 72;
    const cv = document.createElement("canvas"); cv.width = W; cv.height = H;
    const ctx = cv.getContext("2d", { willReadFrequently: true });
    let prev = null, lastSent = null, still = 0, best = 1, busy = false, lastAt = 0, lastStatus = "none", recent = [];
    const info = { d: 0, thr: 4, still: 0, sharp: 0, best: 0, contrast: 0, busy: false, last: "none", age: 0, phase: "starting", scans: 0 };

    function thumb() {
      ctx.drawImage(video, 0, 0, W, H);
      const px = ctx.getImageData(0, 0, W, H).data, n = W * H, g = new Float32Array(n);
      let m = 0;
      for (let i = 0; i < n; i++) { g[i] = 0.299 * px[i * 4] + 0.587 * px[i * 4 + 1] + 0.114 * px[i * 4 + 2]; m += g[i]; }
      m /= n; let v = 0;
      for (let i = 0; i < n; i++) { g[i] -= m; v += g[i] * g[i]; }
      const sd = Math.sqrt(v / n) || 1;
      for (let i = 0; i < n; i++) g[i] = g[i] / sd * 40;           // brightness and exposure changes cancel out
      return { g, sd };
    }
    const diff = (a, b) => { let s = 0; for (let i = 0; i < a.length; i++) s += Math.abs(a[i] - b[i]); return s / a.length; };
    function sharp(g) { let s = 0; for (let y = 0; y < H - 1; y++) for (let x = 0; x < W - 1; x++) { const i = y * W + x; s += Math.abs(g[i] - g[i + 1]) + Math.abs(g[i] - g[i + W]); } return s / g.length; }

    async function fire(force) {
      if (busy) return;
      busy = true; lastAt = performance.now(); info.scans++;
      try { lastSent = thumb().g; } catch (e) {}
      try { lastStatus = await opt.send(!!force); } catch (e) { lastStatus = "error"; }
      busy = false;
    }

    function tick() {
      if (video.readyState < 2 || !video.videoWidth) return;
      const { g, sd } = thumb(), s = sharp(g);
      best = Math.max(best * 0.99, s);
      const d = prev ? diff(g, prev) : 99; prev = g;
      recent.push(d); if (recent.length > 40) recent.shift();
      const floor = [...recent].sort((a, b) => a - b)[Math.floor(recent.length * 0.2)] || 0;
      const thr = Math.min(10, Math.max(4, floor * 2.5));       // adapts to this camera's own noise
      still = d < thr ? still + 1 : 0;
      const age = performance.now() - lastAt;
      const solved = lastStatus === "solved" || lastStatus === "same";
      const changed = !lastSent || diff(g, lastSent) > 6;
      const sharpOK = s >= 0.6 * best || age > 6000;             // let a stubborn focus through after a while
      const enoughContrast = sd > 6;                               // a flat dark/white frame has nothing to read
      info.d = d; info.thr = thr; info.still = still; info.sharp = s; info.best = best; info.contrast = sd; info.busy = busy; info.last = lastStatus; info.age = age;
      info.phase = busy ? "reading" : still < 3 ? "moving" : !enoughContrast ? "dark" : !sharpOK ? "focusing" : "steady";
      if (!busy && still >= 3 && sharpOK && enoughContrast && (changed || age > (solved ? 12000 : 4000))) fire(false);
      if (opt.onInfo) opt.onInfo(info);
    }
    const timer = setInterval(tick, 250);
    return { scanNow: () => fire(true), stop: () => clearInterval(timer), info };
  }
  return { create };
})();

// 按精灵图播动画（QQ 企鹅原版素材：Flash SWF -> PNG 帧 -> WebP 精灵图）
// 每张图 COLS 列，格子 CELL 大小；帧序从左到右、从上到下；原始 12 fps。

import { CELL, COLS, SHEETS, PLAY } from "./sheets/sheets.mjs";

export const FRAME_MS = 1000 / 12;

export class FramePlayer {
  constructor(ctx) {
    this.ctx = ctx;
    this.images = {};
    this.name = "Idle1";
    this.t0 = performance.now();
    this.onDone = null;
    this.raf = null;
    this.ready = false;
    this.loops = 0;
  }

  // 一次性把精灵图都读进来（本地文件，很小）
  async load(onStep) {
    const names = Object.keys(SHEETS);
    let done = 0;
    await Promise.all(
      names.map(
        (n) =>
          new Promise((resolve) => {
            const img = new Image();
            img.onload = () => {
              this.images[n] = img;
              done += 1;
              if (onStep) onStep(done, names.length, n);
              resolve();
            };
            img.onerror = () => {
              done += 1;
              if (onStep) onStep(done, names.length, n + "(失败)");
              resolve();
            };
            img.src = new URL("./sheets/" + SHEETS[n].file, import.meta.url).href;
          }),
      ),
    );
    this.ready = true;
    return Object.keys(this.images).length;
  }

  has(name) {
    return !!SHEETS[name] && !!this.images[name];
  }

  names() {
    return Object.keys(SHEETS);
  }

  frameCount(name) {
    return SHEETS[name] ? SHEETS[name].frames : 0;
  }

  play(name, onDone) {
    if (!this.has(name)) return false;
    this.name = name;
    this.t0 = performance.now();
    this.loops = 0;
    this.done = false;
    this.onDone = onDone || null;
    return true;
  }

  stop() {
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = null;
  }

  start() {
    if (this.raf) return;
    if (this.has("Idle1")) this.play("Idle1");
    const tick = () => {
      this.frame();
      this.raf = requestAnimationFrame(tick);
    };
    this.raf = requestAnimationFrame(tick);
  }

  frame() {
    const now = performance.now();
    const cfg = PLAY[this.name] || {};
    const n = this.frameCount(this.name);
    if (!n) return;
    let idx = Math.floor((now - this.t0) / FRAME_MS);

    if (cfg.loop) {
      if (cfg.max && idx >= cfg.max) idx = idx % cfg.max;
      else idx = idx % n;
    } else if (idx >= n) {
      idx = n - 1;
      if (!this.done) {
        this.done = true;
        if (this.onDone) {
          const cb = this.onDone;
          this.onDone = null;
          cb(this.name);
        }
      }
    }
    this.draw(idx, n);
  }

  draw(idx, n) {
    const img = this.images[this.name];
    if (!img) return;
    const col = idx % COLS;
    const row = Math.floor(idx / COLS);
    const [cw, ch] = CELL;
    this.ctx.clearRect(0, 0, cw, ch);
    this.ctx.drawImage(img, col * cw, row * ch, cw, ch, 0, 0, cw, ch);
    // 给外部一个"画完之后"的钩子（督战官的眼镜/教鞭就叠在这里）
    if (this.afterDraw) this.afterDraw(idx, this.name, cw, ch);
  }

  // 自检用：把某个动作的若干帧画到一张大图上
  paintStrip(name, samples, target) {
    const img = this.images[name];
    const [cw, ch] = CELL;
    const n = this.frameCount(name);
    target.width = cw * samples;
    target.height = ch;
    const c = target.getContext("2d");
    c.fillStyle = "#f2f2ef";
    c.fillRect(0, 0, target.width, target.height);
    for (let i = 0; i < samples; i++) {
      const idx = Math.floor((i / samples) * n);
      c.drawImage(img, (idx % COLS) * cw, Math.floor(idx / COLS) * ch, cw, ch, i * cw, 0, cw, ch);
    }
  }
}

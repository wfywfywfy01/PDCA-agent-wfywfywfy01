// 督战官皮肤：在企鹅本体上叠一副眼镜 + 一根教鞭。
// 位置不是写死的 —— 每帧先量出企鹅的不透明包围盒，再按比例摆，所以换动作、换形态都不会飘。

// 量当前画布上企鹅的包围盒 + 白脸的位置
// 白脸 = 轮廓上半部分里成片的亮像素（企鹅的脸是白的，肚皮在下半部分，分开取）
export function measure(ctx, w, h) {
  let d;
  try {
    d = ctx.getImageData(0, 0, w, h).data;
  } catch (e) {
    return null;
  }
  let x0 = w, y0 = h, x1 = -1, y1 = -1;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      if (d[(y * w + x) * 4 + 3] > 40) {
        if (x < x0) x0 = x;
        if (y < y0) y0 = y;
        if (x > x1) x1 = x;
        if (y > y1) y1 = y;
      }
    }
  }
  if (x1 < 0) return null;
  const all = { x: x0, y: y0, w: x1 - x0 + 1, h: y1 - y0 + 1 };

  // 在上半部分找白脸
  const faceLimit = y0 + all.h * 0.6;
  let fx0 = w, fy0 = h, fx1 = -1, fy1 = -1;
  for (let y = y0; y < Math.min(h, faceLimit); y++) {
    for (let x = x0; x <= x1; x++) {
      const i = (y * w + x) * 4;
      if (d[i + 3] > 120 && d[i] > 195 && d[i + 1] > 195 && d[i + 2] > 195) {
        if (x < fx0) fx0 = x;
        if (y < fy0) fy0 = y;
        if (x > fx1) fx1 = x;
        if (y > fy1) fy1 = y;
      }
    }
  }
  const face =
    fx1 > fx0 && fy1 >= fy0
      ? { x: fx0, y: fy0, w: fx1 - fx0 + 1, h: fy1 - fy0 + 1 }
      : null;
  return { all: all, face: face };
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

// 眼镜：黑框 + 淡蓝镜片 + 一条鼻梁 + 两根镜腿
function glasses(ctx, cx, cy, gw) {
  const r = gw * 0.5;
  const lens = gw * 0.42;
  const gap = gw * 0.1;
  const lx = cx - gap / 2 - lens;
  const rx = cx + gap / 2;
  ctx.save();
  ctx.lineWidth = Math.max(1.6, gw * 0.075);
  ctx.strokeStyle = "#1b1d24";
  [-1, 1].forEach(function (s) {
    const x = s < 0 ? lx : rx;
    ctx.beginPath();
    ctx.ellipse(x + lens / 2, cy, lens / 2, lens / 2 * 0.86, 0, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(176,214,255,0.30)";
    ctx.fill();
    ctx.stroke();
  });
  // 鼻梁
  ctx.beginPath();
  ctx.moveTo(lx + lens, cy - lens * 0.06);
  ctx.lineTo(rx, cy - lens * 0.06);
  ctx.stroke();
  // 镜腿
  ctx.beginPath();
  ctx.moveTo(lx, cy - lens * 0.34);
  ctx.lineTo(lx - r * 0.34, cy - lens * 0.55);
  ctx.moveTo(rx + lens, cy - lens * 0.34);
  ctx.lineTo(rx + lens + r * 0.34, cy - lens * 0.55);
  ctx.stroke();
  ctx.restore();
}

// 教鞭：一根细杆 + 亮色鞭头，握在（右）翅膀那一侧
function pointer(ctx, x, y, len, angle, alpha) {
  ctx.save();
  ctx.globalAlpha = alpha == null ? 1 : alpha;
  ctx.translate(x, y);
  ctx.rotate(angle);
  // 杆
  ctx.beginPath();
  ctx.moveTo(0, 0);
  ctx.lineTo(0, -len);
  ctx.lineWidth = Math.max(1.6, len * 0.028);
  ctx.strokeStyle = "#8a5a2b";
  ctx.lineCap = "round";
  ctx.stroke();
  // 高光
  ctx.beginPath();
  ctx.moveTo(-len * 0.012, 0);
  ctx.lineTo(-len * 0.012, -len);
  ctx.lineWidth = Math.max(0.7, len * 0.011);
  ctx.strokeStyle = "rgba(255,235,200,0.55)";
  ctx.stroke();
  // 鞭头
  ctx.beginPath();
  ctx.arc(0, -len, Math.max(2, len * 0.042), 0, Math.PI * 2);
  ctx.fillStyle = "#e8453c";
  ctx.fill();
  ctx.strokeStyle = "#9c2b25";
  ctx.lineWidth = Math.max(0.7, len * 0.012);
  ctx.stroke();
  // 握把
  ctx.beginPath();
  ctx.moveTo(-len * 0.026, 0);
  ctx.lineTo(len * 0.026, 0);
  ctx.lineWidth = Math.max(2.2, len * 0.042);
  ctx.strokeStyle = "#5d3a1a";
  ctx.stroke();
  ctx.restore();
}

// 主入口：在已经画好企鹅的画布上叠加督战官道具
// bounds = { all:{x,y,w,h}, face:{x,y,w,h}|null }（CSS 像素）
// swing: 0..1 用来让教鞭点一点
export function drawTeacher(ctx, bounds, cellW, cellH, swing) {
  if (!bounds || !bounds.all) return;
  const all = bounds.all;
  const face = bounds.face;

  // 眼镜：对准白脸；没有白脸（蛋、趴着）就退回按轮廓估算。尺寸要收着点，别糊住整张脸
  let cx, cy, gw;
  if (face) {
    cx = face.x + face.w / 2;
    cy = face.y + face.h * 0.4;
    gw = Math.min(face.w * 0.74, all.w * 0.5);
  } else {
    cx = all.x + all.w * 0.5;
    cy = all.y + all.h * 0.34;
    gw = all.w * 0.36;
  }
  gw = Math.max(14, gw);
  glasses(ctx, cx, cy, gw);

  // 教鞭：握在右侧翅膀那儿，斜指向右上
  const px = all.x + all.w * 0.74;
  const py = all.y + all.h * 0.7;
  const len = Math.max(24, all.h * 0.72);
  const angle = 0.6 + (swing || 0) * 0.2; // 正角度 = 往右上
  pointer(ctx, px, py, len, angle, 1);
}

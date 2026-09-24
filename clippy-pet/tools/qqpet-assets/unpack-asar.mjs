// 解包 Electron 的 app.asar（格式：4 个 u32 头 + JSON 目录 + 数据区）
// 用法：node unpack-asar.mjs <app.asar> <输出目录>
import fs from "node:fs";
import path from "node:path";

const [src, outDir] = process.argv.slice(2);
if (!src || !outDir) {
  console.error("用法: node unpack-asar.mjs <app.asar> <outDir>");
  process.exit(2);
}

const fd = fs.openSync(src, "r");
const head = Buffer.alloc(16);
fs.readSync(fd, head, 0, 16, 0);

const b0 = head.readUInt32LE(0); // 恒为 4
const b1 = head.readUInt32LE(4); // jsonLen + 8
const b2 = head.readUInt32LE(8); // jsonLen + 4
const b3 = head.readUInt32LE(12); // jsonLen
const jsonLen = b3;
const jsonStart = 16;
const dataStart = 8 + b1; // 对齐后的数据区起点

const jsonBuf = Buffer.alloc(jsonLen);
fs.readSync(fd, jsonBuf, 0, jsonLen, jsonStart);
const header = JSON.parse(jsonBuf.toString("utf8"));

console.log(
  "asar 头: b0=" + b0 + " b1=" + b1 + " b2=" + b2 + " jsonLen=" + b3 +
    " 数据区起点=" + dataStart + " 文件大小=" + fs.statSync(src).size,
);

let count = 0;
let bytes = 0;
const byExt = new Map();

function walk(node, rel) {
  for (const name of Object.keys(node.files || {})) {
    const item = node.files[name];
    const p = rel ? rel + "/" + name : name;
    if (item.files) {
      walk(item, p);
      continue;
    }
    const size = Number(item.size) || 0;
    if (item.unpacked) {
      // 外置文件，asar 里没有数据
      continue;
    }
    const off = Number(item.offset);
    const dest = path.join(outDir, p);
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    const buf = Buffer.alloc(size);
    if (size > 0) fs.readSync(fd, buf, 0, size, dataStart + off);
    fs.writeFileSync(dest, buf);
    count += 1;
    bytes += size;
    const ext = (path.extname(name) || "(无扩展名)").toLowerCase();
    const cur = byExt.get(ext) || { n: 0, b: 0 };
    cur.n += 1;
    cur.b += size;
    byExt.set(ext, cur);
  }
}

walk(header, "");
fs.closeSync(fd);

console.log("解出 " + count + " 个文件, " + (bytes / 1048576).toFixed(1) + " MB");
const rows = [...byExt.entries()].sort((a, b) => b[1].b - a[1].b).slice(0, 20);
for (const [ext, v] of rows) {
  console.log("  " + ext.padEnd(12) + String(v.n).padStart(6) + " 个  " + (v.b / 1048576).toFixed(2) + " MB");
}

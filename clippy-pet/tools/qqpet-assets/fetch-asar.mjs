// 分块下载 app.asar 的 deflate 数据流并解压成 app.asar
// 用法: node fetch-asar.mjs <chunkDir> <outAsar>
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";

const [chunkDir, outAsar] = process.argv.slice(2);
const START = 90294404;
const END = 266702998; // 含
const TOTAL = END - START + 1;

const parts = fs
  .readdirSync(chunkDir)
  .filter((f) => /^chunk-\d+\.bin$/.test(f))
  .map((f) => ({ f, i: Number(f.match(/chunk-(\d+)\.bin/)[1]) }))
  .sort((a, b) => a.i - b.i);

let got = 0;
const bufs = [];
for (const p of parts) {
  const b = fs.readFileSync(path.join(chunkDir, p.f));
  bufs.push(b);
  got += b.length;
}
console.log("分块 " + parts.length + " 个, 合计 " + (got / 1048576).toFixed(1) + " MB / " + (TOTAL / 1048576).toFixed(1) + " MB");
if (got !== TOTAL) {
  console.error("分块不完整，缺 " + (TOTAL - got) + " 字节");
  process.exit(1);
}
const raw = Buffer.concat(bufs);
console.log("解压中 ...");
const out = zlib.inflateRawSync(raw, { maxOutputLength: 400 * 1048576 });
fs.writeFileSync(outAsar, out);
console.log("app.asar: " + (out.length / 1048576).toFixed(1) + " MB -> " + outAsar);

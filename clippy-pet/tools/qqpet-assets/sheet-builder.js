// 把导出的 PNG 帧序列拼成精灵图（WebP）+ sheets.json
// 运行：host\electron.exe assets-qqpet\sheet-builder.js
const { app, BrowserWindow } = require("electron");
const fs = require("fs");
const path = require("path");

const HERE = __dirname;
const FRAMES_DIR = path.join(HERE, "frames");
const OUT = process.argv.includes("--out")
  ? process.argv[process.argv.indexOf("--out") + 1]
  : path.join(HERE, "sheets");

function argNum(flag, dflt) {
  const i = process.argv.indexOf(flag);
  return i >= 0 ? Number(process.argv[i + 1]) : dflt;
}

app.disableHardwareAcceleration();
app.whenReady().then(async () => {
  try {
    const anims = fs
      .readdirSync(FRAMES_DIR, { withFileTypes: true })
      .filter((e) => e.isDirectory())
      .map((e) => {
        const dir = path.join(FRAMES_DIR, e.name);
        const files = fs
          .readdirSync(dir)
          .filter((f) => /\.png$/i.test(f))
          .sort((a, b) => parseInt(a, 10) - parseInt(b, 10))
          .map((f) => path.join(dir, f));
        return { name: e.name, dir, files };
      })
      .filter((a) => a.files.length > 0)
      .sort((a, b) => a.name.localeCompare(b.name));

    const totalFrames = anims.reduce((s, a) => s + a.files.length, 0);
    console.log("动作 " + anims.length + " 个, 共 " + totalFrames + " 帧");

    const win = new BrowserWindow({
      width: 400,
      height: 300,
      show: false,
      webPreferences: { nodeIntegration: true, contextIsolation: false, webSecurity: false },
    });
    await win.loadFile(path.join(HERE, "sheet.html"));
    await win.webContents.executeJavaScript(
      "window.__FRAMES = " + JSON.stringify(anims) +
        "; window.__OUT = " + JSON.stringify(OUT) +
        "; window.__SCALE = " + argNum("--scale", 1) +
        "; window.__QUALITY = " + argNum("--quality", 0.92) + ";",
    );
    const res = await win.webContents.executeJavaScript("window.__build()");
    console.log("结果: " + JSON.stringify(res));
    const lines = await win.webContents.executeJavaScript("document.getElementById('log').textContent");
    process.stdout.write(lines);
  } catch (e) {
    console.error("拼图失败: " + (e && e.stack ? e.stack : e));
  }
  app.exit(0);
});

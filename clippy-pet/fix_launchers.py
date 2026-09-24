# 把 _launcher_src 里的 cmd 启动器转成 GBK + CRLF，并放到桌宠根目录
# （cmd.exe 在中文 Windows 上按 GBK 读 .cmd，UTF-8 会把中文注释和提示读成乱码）
# 用法: python fix_launchers.py
import io
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "_launcher_src")

def convert(name):
    src = os.path.join(SRC, name)
    dst = os.path.join(ROOT, name)
    if not os.path.exists(src):
        print("missing:", src)
        return False
    with io.open(src, "r", encoding="utf-8") as fh:
        text = fh.read()
    with io.open(dst, "w", encoding="gbk", newline="\r\n") as fh:
        fh.write(text)
    size = os.path.getsize(dst)
    print("{} -> {} bytes (gbk+crlf)".format(name, size))
    return True

for n in ("启动桌宠.cmd", "自检.cmd"):
    convert(n)
print("done")

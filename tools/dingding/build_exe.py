# -*- coding: utf-8 -*-
"""把 dingding_exe.py 打成单个「叮叮课表.exe」。

只用本机已有的 Python 3.11 + PyInstaller，不下载任何依赖、不联网、
不需要管理员权限。图标是纯标准库现画的 32x32 ICO，不引用外部素材。

    python tools/dingding/build_exe.py
产物：tools/dingding/dist/叮叮课表.exe
"""
import shutil
import struct
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WINDOWS = HERE / "windows"
DIST = HERE / "dist"
BUILD = HERE / "build" / "pyi"
ENTRY = WINDOWS / "dingding_exe.py"
OUT = DIST / "叮叮课表.exe"
PY311 = Path(r"C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe")


def make_icon(path):
    """32x32 32bpp ICO：蓝底 + 白色铃铛。纯 struct，不用 PIL。"""
    w = h = 32
    pixels = bytearray()
    for y in range(h - 1, -1, -1):          # BMP 行序自下而上
        for x in range(w):
            cx, cy = x - 15.5, y - 15.5
            if cx * cx + cy * cy > 15.5 * 15.5:
                b, g, r, a = 0, 0, 0, 0     # 透明圆外
            else:
                b, g, r, a = 0xC0, 0x70, 0x2F, 0xFF   # #2F70C0
            bell = 8 <= y <= 21 and abs(x - 15) <= (3 + (21 - y) // 3)
            dot = 23 <= y <= 25 and abs(x - 15) <= 2
            if bell or dot:
                b, g, r, a = 0xFF, 0xFF, 0xFF, 0xFF
            pixels += bytes((b, g, r, a))
    and_mask = b"\x00" * (4 * h)
    dib = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0,
                      len(pixels) + len(and_mask), 0, 0, 0, 0)
    image = dib + bytes(pixels) + and_mask
    ico = (struct.pack("<HHH", 0, 1, 1)
           + struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(image), 22)
           + image)
    path.write_bytes(ico)


def main():
    if not PY311.exists():
        raise SystemExit("找不到本机 Python 3.11：%s" % PY311)
    check = subprocess.run([str(PY311), "-c", "import PyInstaller,tkinter;print('ok')"],
                           capture_output=True, text=True)
    if "ok" not in (check.stdout or ""):
        raise SystemExit("Python 3.11 缺 PyInstaller 或 tkinter：%s" % check.stderr)

    DIST.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    ico = BUILD / "dingding.ico"
    make_icon(ico)

    cmd = [str(PY311), "-m", "PyInstaller",
           "--noconfirm", "--onefile", "--noconsole", "--clean",
           "--name", "DingDingTimetable",
           "--icon", str(ico),
           "--distpath", str(DIST), "--workpath", str(BUILD), "--specpath", str(BUILD),
           "--paths", str(HERE), "--paths", str(WINDOWS),
           "--hidden-import", "commit_usage_logs",
           "--hidden-import", "courses_data",
           "--add-data", str(WINDOWS / "courses.json") + ";.",
           str(ENTRY)]
    print("打包中（约 1 分钟）…")
    p = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        print((p.stdout or "")[-3000:])
        print((p.stderr or "")[-3000:], file=sys.stderr)
        raise SystemExit("PyInstaller 失败，退出码 %d" % p.returncode)

    built = DIST / "DingDingTimetable.exe"
    if not built.exists():
        raise SystemExit("没产出 EXE：%s" % built)
    if OUT.exists():
        OUT.unlink()
    shutil.move(str(built), str(OUT))

    size = OUT.stat().st_size
    print("产物：%s（%.1f MB）" % (OUT, size / 1048576))
    if size < 3 * 1048576:
        raise SystemExit("EXE 体积异常，可能没打进运行时")
    # 只匹配「密钥形态」，不裸搜 sk- 这类短前缀 —— 压缩数据里随机三字节会误报。
    blob = OUT.read_bytes()
    import re
    patterns = [rb"sk-[A-Za-z0-9_\-]{20,}", rb"SCT[A-Za-z0-9]{8,}",
                rb"ghp_[A-Za-z0-9]{20,}", rb"github_pat_[A-Za-z0-9_]{20,}"]
    for pat in patterns:
        hit = re.search(pat, blob)
        if hit:
            raise SystemExit("EXE 中出现疑似密钥 %r，拒绝交付" % hit.group()[:12])
    print("密钥串扫描：零命中（按密钥形态匹配，非裸前缀）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

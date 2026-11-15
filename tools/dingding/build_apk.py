"""叮叮课表 · 安卓 APK 本机构建（不联网、不用 Gradle、不用 GitHub Actions）

用本机 Android SDK 的最小工具链：
  aapt2 compile/link → javac --release 8 → d8 → zip 合并 dex → zipalign → apksigner

复用仓库里已有的固定开发签名（PowerProbe 的 powerprobe.jks），
目的是让以后每次构建都能直接覆盖安装，不用先卸载、不会清掉数据。
"""
import os
import shutil
import struct
import subprocess
import sys
import zipfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
AND = HERE / "android"
BUILD = HERE / "build"
DIST = HERE / "dist"
SIGNING = REPO / "tools" / "PowerProbe" / "signing" / "powerprobe.jks"
OUT_APK = DIST / "叮叮课表.apk"


# ---------- 纯标准库生成一个 PNG 启动图标（蓝色圆角底 + 白色铃铛） ----------

def png_chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def make_icon(path, size=96):
    r = 20
    rows = []
    for y in range(size):
        row = bytearray(b"\x00")  # filter type 0
        for x in range(size):
            dx, dy = min(x, size - 1 - x), min(y, size - 1 - y)
            inside = True
            if dx < r and dy < r:
                inside = (dx - r) ** 2 + (dy - r) ** 2 <= r * r
            bell = False
            if 45 <= x <= 51 and 21 <= y <= 27:
                bell = True
            if 28 <= y <= 62 and abs(x - 48) <= 9 + (y - 28) * 0.78:
                bell = True
            if 63 <= y <= 67 and abs(x - 48) <= 36:
                bell = True
            if 68 <= y <= 74 and (abs(x - 48) <= 7):
                bell = True
            if bell and inside:
                row += bytes((255, 255, 255, 255))
            elif inside:
                row += bytes((47, 111, 235, 255))
            else:
                row += bytes((0, 0, 0, 0))
        rows.append(bytes(row))
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    data = (b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", ihdr)
            + png_chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
            + png_chunk(b"IEND", b""))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


# ---------- 工具链 ----------

def sdk_root():
    root = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if not root:
        raise SystemExit("没有设置 ANDROID_HOME，无法本地构建 APK")
    p = Path(root)
    if not p.exists():
        raise SystemExit("ANDROID_HOME 指向的目录不存在：%s" % p)
    return p


def run(args, label, optional=False):
    print("  → " + label)
    p = subprocess.run([str(a) for a in args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        print((p.stdout or "")[-2500:])
        print((p.stderr or "")[-2500:], file=sys.stderr)
        if optional:
            print("  （这一步仅作额外核对，失败不阻断；签名与内容校验仍以 apksigner / zipfile 为准）")
            return ""
        raise SystemExit("构建失败于：%s（退出码 %d）" % (label, p.returncode))
    return p.stdout or ""


def main():
    sdk = sdk_root()
    bt = sdk / "build-tools" / "29.0.3"
    platform = sdk / "platforms" / "android-29" / "android.jar"
    aapt2 = bt / "aapt2.exe"
    aapt = bt / "aapt.exe"
    zipalign = bt / "zipalign.exe"
    d8 = bt / "lib" / "d8.jar"
    apksigner = bt / "lib" / "apksigner.jar"
    for f in (bt, platform, aapt2, zipalign, d8, apksigner):
        if not Path(f).exists():
            raise SystemExit("缺少构建工具：%s" % f)
    if not SIGNING.exists():
        raise SystemExit("缺少固定开发签名：%s" % SIGNING)

    assets_index = AND / "assets" / "index.html"
    if not assets_index.exists():
        print("先生成三端产物 …")
        run([sys.executable, str(HERE / "build_assets.py")], "生成课表数据")
    assert assets_index.exists(), "assets/index.html 仍不存在"

    icon = AND / "res" / "drawable" / "ic_launcher.png"
    if not icon.exists():
        make_icon(icon)

    if BUILD.exists():
        shutil.rmtree(BUILD)
    (BUILD / "gen").mkdir(parents=True)
    (BUILD / "classes").mkdir()
    (BUILD / "dex").mkdir()
    DIST.mkdir(exist_ok=True)

    print("SDK: %s" % sdk)
    print("1/7 编译资源")
    run([aapt2, "compile", "--dir", AND / "res", "-o", BUILD / "res.zip"], "aapt2 compile")

    print("2/7 链接 APK 骨架（Manifest + 资源 + assets）")
    run([aapt2, "link",
         "-o", BUILD / "base.apk",
         "-I", platform,
         "--manifest", AND / "AndroidManifest.xml",
         "-A", AND / "assets",
         BUILD / "res.zip"], "aapt2 link")

    print("3/7 编译 Java（--release 8，兼容 d8/build-tools 29）")
    run(["javac", "--release", "8", "-encoding", "UTF-8",
         "-classpath", platform,
         "-d", BUILD / "classes",
         AND / "MainActivity.java"], "javac")

    classes = sorted((BUILD / "classes").rglob("*.class"))
    if not classes:
        raise SystemExit("javac 没有产出任何 class")
    print("   class 文件 %d 个" % len(classes))

    print("4/7 d8 → classes.dex")
    run(["java", "-cp", d8, "com.android.tools.r8.D8",
         "--lib", platform, "--min-api", "26",
         "--output", BUILD / "dex"] + classes, "d8")
    dex = BUILD / "dex" / "classes.dex"
    if not dex.exists():
        raise SystemExit("d8 没有产出 classes.dex")

    print("5/7 合并 dex 到 APK")
    unsigned = BUILD / "unsigned.apk"
    with zipfile.ZipFile(BUILD / "base.apk", "r") as zin, \
         zipfile.ZipFile(unsigned, "w") as zout:
        for item in zin.infolist():
            zout.writestr(item, zin.read(item.filename))
        zout.write(dex, "classes.dex", compress_type=zipfile.ZIP_DEFLATED)

    print("6/7 zipalign")
    aligned = BUILD / "aligned.apk"
    run([zipalign, "-f", "4", unsigned, aligned], "zipalign")

    print("7/7 签名（固定开发密钥，可直接覆盖安装）")
    run(["java", "-jar", apksigner, "sign",
         "--ks", SIGNING,
         "--ks-pass", "pass:powerprobe",
         "--key-pass", "pass:powerprobe",
         "--ks-key-alias", "powerprobe",
         "--out", OUT_APK, aligned], "apksigner sign")

    print("\n=== 验证 ===")
    print(run(["java", "-jar", apksigner, "verify", "--print-certs", OUT_APK],
              "apksigner verify").strip()[:600])
    badging = ""
    if aapt.exists():
        # aapt.exe 在 Windows 下读不了中文路径，用 ASCII 名副本核对 badging
        check = BUILD / "check.apk"
        shutil.copyfile(OUT_APK, check)
        badging = run([aapt, "dump", "badging", check], "aapt dump badging", optional=True)
        for line in badging.splitlines():
            if line.startswith("package:") or "application-label" in line or "sdkVersion" in line:
                print("  " + line[:300])
    with zipfile.ZipFile(OUT_APK) as z:
        names = z.namelist()
        need = ["AndroidManifest.xml", "classes.dex", "assets/index.html", "resources.arsc"]
        for n in need:
            print("  %-24s %s" % (n, "OK" if n in names else "缺失"))
        assert all(n in names for n in need), "APK 内容不完整"
        idx = z.read("assets/index.html").decode("utf-8", "ignore")
        n = idx.count('"d":"')
        print("  内嵌课表条目数        %d" % n)
        assert n >= 140, "内嵌课表数量异常（应为 140）"

    print("\n成品：%s  (%.1f KB)" % (OUT_APK, OUT_APK.stat().st_size / 1024))
    print("安装：把 叮叮课表.apk 传到手机 → 允许安装未知来源 → 打开后点「写入手机日历」")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""叮叮课表 · Windows 安装版（只用 Python 标准库，不下载任何依赖）

这一版按 2026-11-15 的新要求做：开机自启、常驻、到点弹窗、可即时测试通知、
每天自动把真实使用日志 commit 到 GitHub。

  python dingding_win.py --install     安装（复制程序 + 写自启 + 建测试入口 + 弹一条测试通知）
  python dingding_win.py --daemon      开机自启后常驻运行（pythonw 启动，无黑框）
  python dingding_win.py --test        立即弹一条测试通知（5 秒后自动关闭）
  python dingding_win.py --fire P1     手动触发某一大节的提醒
  python dingding_win.py --commit-logs 提交当天使用日志
  python dingding_win.py --selftest    不弹窗不写注册表的自检
  python dingding_win.py --status      看当前状态
  python dingding_win.py --uninstall   取消开机自启

诚实边界：
  - Windows 这边靠「开机自启的常驻小程序」弹窗，进程被结束就不会弹；
    真正不依赖任何进程的一层仍然是 叮叮课表.ics 导入 Windows 日历后的系统提醒。
  - 使用日志只记真实发生的事件；关机、没启动、断网的日子就是空白，不补写。
  - GitHub 凭据只在本机 .workbuddy/.gh_token，不写进本程序、不入库。
"""
import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import winsound
from datetime import date, datetime
from pathlib import Path

# pythonw.exe 无控制台，sys.stdout / stderr 可能是 None；不重定向的话常驻状态下
# 任何一次 print 都会抛 AttributeError，被记成假的 daemon_error。
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

HERE = Path(__file__).resolve().parent
APP = "DingDingTimetable"
INSTALL_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
COMMIT_HHMM = "23:50"

try:
    import winreg
except ImportError:  # 非 Windows 上只做自检，不写注册表
    winreg = None


# ---------- 配置与数据 ----------

def load_cfg():
    p = HERE / "config.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    # 未安装、直接在仓库里跑：从 tools/dingding/windows 反推仓库根
    repo = HERE.parents[2]
    return {"repo_root": str(repo), "workspace_root": str(repo.parent),
            "python": sys.executable, "pythonw": "", "installed": False}


def courses():
    data = json.loads((HERE / "courses.json").read_text(encoding="utf-8"))
    return data["entries"]


def log_dir():
    return Path(load_cfg()["repo_root"]) / "tools" / "dingding" / "usage_logs"


def log(event, detail, ok=True):
    """只追加真实事件。不补写、不回填、不编造时间戳。"""
    now = datetime.now().astimezone()
    rec = {"ts": now.isoformat(timespec="seconds"), "date": now.date().isoformat(),
           "event": event, "detail": detail, "ok": ok, "source": "windows-client"}
    try:
        d = log_dir()
        d.mkdir(parents=True, exist_ok=True)
        with (d / (now.date().isoformat() + ".jsonl")).open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception as e:
        print("日志写失败：%s %s" % (type(e).__name__, e), file=sys.stderr)
    return rec


# ---------- 通知 ----------

def notify(title, text, blocking=True):
    """置顶弹窗 + 提示音。MessageBoxTimeoutW 5 秒自动关，避免测试时卡住。"""
    try:
        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except Exception:
        pass
    if not sys.platform.startswith("win"):
        print("[通知] %s | %s" % (title, text))
        return
    u = ctypes.windll.user32
    flags = 0x40 | 0x40000 | 0x10000  # MB_ICONINFORMATION | MB_TOPMOST | MB_SETFOREGROUND

    def show():
        try:
            u.MessageBoxTimeoutW(0, text, title, flags, 0, 5000)
        except Exception:
            try:
                u.MessageBoxW(0, text, title, flags)
            except Exception as e:
                print("弹窗失败：%s" % e, file=sys.stderr)

    if blocking:
        show()
    else:
        threading.Thread(target=show, daemon=True).start()


def entry_for(day, period=None, remind_at=None):
    for e in courses():
        if e["d"] != day:
            continue
        if period and e["p"] == period:
            return e
        if remind_at and e["r"] == remind_at:
            return e
    return None


def render(e):
    names = " / ".join(x for x in e["n"] if x)
    rooms = " / ".join(x for x in e["m"] if x)
    title = "叮叮课表 · 该去上课了"
    text = "%s 上课｜%s%s\n第 %d 周 · %s" % (
        e["s"], names, (" @" + rooms) if rooms else "", e["w"], e["pl"])
    return title, text


def fire(period=None, remind_at=None, source="manual"):
    day = date.today().isoformat()
    e = entry_for(day, period, remind_at)
    if not e:
        log("no_course", "%s %s 这一节没课，不弹窗" % (day, period or remind_at))
        print("%s %s 没课，按设计不打扰" % (day, period or remind_at))
        return False
    t, x = render(e)
    notify(t, x, blocking=True)
    log("reminder_fired", "%s %s %s" % (day, e["r"], " / ".join(e["n"])))
    return True


# ---------- 日志自动提交 ----------

def commit_logs():
    cfg = load_cfg()
    script = Path(cfg["repo_root"]) / "tools" / "dingding" / "commit_usage_logs.py"
    py = cfg.get("python") or sys.executable
    if not script.exists():
        log("commit_logs", "提交脚本不存在，未提交", ok=False)
        return False
    try:
        r = subprocess.run([py, str(script)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        out = (r.stdout or "").strip().splitlines()
        tail = out[-1] if out else (r.stderr or "").strip()[:200]
        log("commit_logs", "exit=%d %s" % (r.returncode, tail[:300]),
            ok=(r.returncode == 0))
        print("日志提交：%s" % tail)
        return r.returncode == 0
    except Exception as e:
        log("commit_logs", "%s %s" % (type(e).__name__, e), ok=False)
        return False


# ---------- 安装 / 卸载 ----------

def pythonw_path():
    p = Path(sys.executable).parent / "pythonw.exe"
    return str(p) if p.exists() else sys.executable


def install():
    if winreg is None:
        raise SystemExit("只能在 Windows 上安装")
    repo = HERE.parents[2]
    cfg = {"repo_root": str(repo), "workspace_root": str(repo.parent),
           "python": sys.executable, "pythonw": pythonw_path(), "installed": True}
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("dingding_win.py", "courses.json"):
        shutil.copy2(HERE / name, INSTALL_DIR / name)
    (INSTALL_DIR / "config.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    runner = cfg["pythonw"]
    script = str(INSTALL_DIR / "dingding_win.py")
    cmd = '"%s" "%s" --daemon' % (runner, script)
    k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE)
    winreg.SetValueEx(k, APP, 0, winreg.REG_SZ, cmd)
    winreg.CloseKey(k)

    # 桌面放一个「立即测试通知」入口，内容全 ASCII，避免 cmd 中文代码页问题
    desktop = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
    try:
        desktop.mkdir(parents=True, exist_ok=True)
        (desktop / "叮叮课表-测试通知.cmd").write_text(
            '@echo off\r\nstart "" "%s" "%s" --test\r\n' % (runner, script),
            encoding="ascii")
    except Exception as e:
        print("桌面测试入口没建成：%s" % e, file=sys.stderr)

    log("install", "安装到 %s，已写开机自启" % INSTALL_DIR)
    print("安装完成：%s" % INSTALL_DIR)
    print("开机自启：HKCU\\%s\\%s" % (RUN_KEY, APP))
    print("桌面已放「叮叮课表-测试通知.cmd」，双击即可立即测一条通知。")
    # 安装完立刻弹一条，当场验证通知链路
    notify("叮叮课表 · 安装完成", "这就是上课提醒的样子。5 秒后自动关闭。\n"
           "以后课前 20 分钟会自动弹。", blocking=True)
    # 启动常驻
    subprocess.Popen([runner, script, "--daemon"],
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    print("常驻程序已启动。")
    return 0


def uninstall():
    if winreg is None:
        return 0
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE)
        winreg.DeleteValue(k, APP)
        winreg.CloseKey(k)
        log("uninstall", "已取消开机自启")
        print("已取消开机自启。常驻进程需自行在任务管理器结束，或重启电脑。")
    except FileNotFoundError:
        print("本来就没有自启项。")
    return 0


# ---------- 常驻 ----------

def daemon():
    log("daemon_start", "开机自启常驻进程启动，pid=%d" % os.getpid())
    fired = set()
    committed = None
    while True:
        try:
            now = datetime.now()
            today = now.date().isoformat()
            hhmm = now.strftime("%H:%M")
            e = entry_for(today, remind_at=hhmm)
            key = today + "-" + hhmm
            if e and key not in fired:
                fired.add(key)
                t, x = render(e)
                notify(t, x, blocking=False)
                log("reminder_fired", "%s %s %s" % (today, hhmm, " / ".join(e["n"])))
            if hhmm == COMMIT_HHMM and committed != today:
                committed = today
                threading.Thread(target=commit_logs, daemon=True).start()
        except Exception as e:
            log("daemon_error", "%s %s" % (type(e).__name__, e), ok=False)
        time.sleep(15)


def selftest():
    c = courses()
    cfg = load_cfg()
    today = date.today().isoformat()
    future = [e for e in c if e["d"] + " " + e["r"] > today + " 00:00"]
    nxt = future[0] if future else None
    print("课表条数           %d" % len(c))
    print("今天               %s" % today)
    print("下一次提醒         %s" % ("%s %s %s" % (
        nxt["d"], nxt["r"], " / ".join(nxt["n"])) if nxt else "学期已结束"))
    print("日志目录           %s" % log_dir())
    print("提交脚本           %s" % (Path(cfg["repo_root"]) / "tools" / "dingding" / "commit_usage_logs.py"))
    print("开机自启命令       %s" % (Path(cfg.get("pythonw") or pythonw_path())))
    assert len(c) == 140, "课表条数异常"
    assert log_dir().parent.exists(), "仓库路径推断错误"
    print("自检通过（未弹窗、未写注册表、未启动常驻）")
    return 0


def main():
    ap = argparse.ArgumentParser(description="叮叮课表 Windows 安装版")
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--fire", default=None, help="P1/P2/P3/P4 或 HH:MM")
    ap.add_argument("--commit-logs", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if a.install:
        return install()
    if a.uninstall:
        return uninstall()
    if a.status:
        cfg = load_cfg()
        print("已安装: %s | 安装目录: %s | 仓库: %s"
              % (cfg.get("installed"), INSTALL_DIR, cfg["repo_root"]))
        return 0
    if a.test:
        notify("叮叮课表 · 测试通知",
               "这就是上课提醒的样子：课程名 + 教室 + 时间。\n5 秒后自动关闭。")
        log("test_notify", "用户手动触发的即时测试通知")
        print("测试通知已弹出。")
        return 0
    if a.commit_logs:
        return 0 if commit_logs() else 1
    if a.fire:
        if ":" in a.fire:
            fire(remind_at=a.fire)
        else:
            fire(period=a.fire.upper())
        return 0
    if a.daemon:
        daemon()
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())

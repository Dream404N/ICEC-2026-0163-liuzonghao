# -*- coding: utf-8 -*-
"""叮叮课表 · Windows 单文件 EXE（图形设置面板 + 事件驱动提醒）

用 PyInstaller 打成一个 .exe，双击就能用，不需要装 Python。

【调度：不是轮询】
旧版每 15 秒把整张课表扫一遍，被使用者指出「像病毒」，这一版已删除。
现在的行为是：
  1. 启动时把课表读进内存一次，算出「下一次要响的时刻」；
  2. 用一个单次 threading.Timer 直接睡到那一刻，中途不查表、不读文件、不联网；
  3. 到点弹通知 → 再算下一次 → 再睡；
  4. 为防止系统休眠/改时间让长定时器失准，最多每 30 分钟做一次「校准唤醒」，
     校准只重算内存里的时间点，不弹窗、不写日志、不产生任何 I/O。
界面上的倒计时每秒只做一次减法，同样不碰磁盘和网络。

【能自己调的东西】
提前几分钟、总开关、提示音、弹窗、开机自启、静音时段、只在工作日提醒、
每天自动 commit 日志的开关与时间、外部课表文件、即时测试通知。

【日志】
只写本机真实发生的事件到 tools/dingding/usage_logs/，每天一次由
commit_usage_logs.py 的逻辑推到 GitHub。凭据从工作区外读取，不进 EXE、不入库。
关机、断网、没启动那天就是空白，不补写。
"""
import argparse
import ctypes
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import winsound
from datetime import date, datetime, timedelta
from pathlib import Path

# --noconsole 打包后 sys.stdout/stderr 为 None，任何 print 都会抛异常。
for _name in ("stdout", "stderr"):
    if getattr(sys, _name, None) is None:
        setattr(sys, _name, open(os.devnull, "w", encoding="utf-8"))

WIN = sys.platform.startswith("win")
APP = "DingDingTimetable"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
CALIBRATE_MINUTES = 30      # 休眠偏差校准间隔（只重算内存时间点）
LATE_TOLERANCE = 300        # 迟到超过 5 分钟不补弹，如实记日志
DEFAULT_MINUTES = 20

try:
    import winreg
except ImportError:
    winreg = None

FROZEN = bool(getattr(sys, "frozen", False))
EXE_PATH = Path(sys.executable).resolve() if FROZEN else Path(__file__).resolve()
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", str(EXE_PATH.parent))).resolve()
INSTALL_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP
SETTINGS_PATH = (Path(os.environ.get("APPDATA", str(Path.home()))) / APP / "settings.json")
APPDATA_DIR = SETTINGS_PATH.parent
CLI_LOG = APPDATA_DIR / "cli_last.txt"

DEFAULTS = {
    "minutes_before": DEFAULT_MINUTES,
    "enabled": True,
    "sound": True,
    "popup": True,
    "autostart": False,
    "quiet_enabled": True,
    "quiet_start": "22:00",
    "quiet_end": "07:00",
    "weekdays_only": True,
    "log_commit": True,
    "log_time": "23:50",
    "minimize_on_start": False,
    "courses_file": "",
    "repo_root": "",
    "workspace_root": "",
    "python": "",
}


# ---------------------------------------------------------------- 路径与配置

def guess_repo_root():
    """从 EXE 位置往上找仓库根；找不到就交给安装器写入 settings。"""
    for p in [EXE_PATH.parent] + list(EXE_PATH.parents):
        if (p / "02-20Days-Challenge").is_dir() and (p / "tools" / "dingding").is_dir():
            return str(p)
    return ""


def load_settings():
    APPDATA_DIR.mkdir(parents=True, exist_ok=True)
    cfg = dict(DEFAULTS)
    if SETTINGS_PATH.exists():
        try:
            cfg.update(json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    if not cfg.get("repo_root"):
        cfg["repo_root"] = guess_repo_root()
    if not cfg.get("workspace_root"):
        r = cfg.get("repo_root")
        cfg["workspace_root"] = str(Path(r).parent) if r else ""
    return cfg


def save_settings(cfg):
    APPDATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")


def repo_root(cfg):
    return Path(cfg.get("repo_root") or guess_repo_root())


def log_dir(cfg):
    return repo_root(cfg) / "tools" / "dingding" / "usage_logs"


def token_file(cfg):
    ws = cfg.get("workspace_root")
    base = Path(ws) if ws else repo_root(cfg).parent
    return base / ".workbuddy" / ".gh_token"


def cli_write(text):
    """命令行模式在 --noconsole 下看不到控制台，结果写文件供核对。"""
    APPDATA_DIR.mkdir(parents=True, exist_ok=True)
    CLI_LOG.write_text(text, encoding="utf-8")
    # 打包成 --noconsole 后继承的控制台是 OEM 代码页，直接 print 中文会乱码；
    # 结果以 UTF-8 文件为准，源码模式下仍打印方便调试。
    if not FROZEN:
        try:
            print(text)
        except Exception:
            pass


def log(cfg, event, detail, ok=True):
    now = datetime.now().astimezone()
    rec = {"ts": now.isoformat(timespec="seconds"), "date": now.date().isoformat(),
           "event": event, "detail": detail, "ok": ok, "source": "windows-exe"}
    try:
        d = log_dir(cfg)
        d.mkdir(parents=True, exist_ok=True)
        with (d / (now.date().isoformat() + ".jsonl")).open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception as e:
        cli_write("日志写失败：%s %s" % (type(e).__name__, e))
    return rec


def load_entries(cfg):
    """只读一次课表进内存。外部课表文件优先，否则用编译进 EXE 的那一份。"""
    p = (cfg.get("courses_file") or "").strip()
    if p and Path(p).exists():
        data = json.loads(Path(p).read_text(encoding="utf-8"))
        return data["entries"], "外部课表：" + p
    try:
        import courses_data
        return json.loads(courses_data.DATA)["entries"], "EXE 内嵌课表"
    except Exception:
        fp = BUNDLE_DIR / "courses.json"
        if not fp.exists():
            fp = EXE_PATH.parent / "courses.json"
        return json.loads(fp.read_text(encoding="utf-8"))["entries"], "同目录 courses.json"


# ---------------------------------------------------------------- 通知

def notify(cfg, title, text, wait=False):
    """置顶弹窗 + 提示音，5 秒自动关。GUI 里开线程不卡界面；命令行测试时同步等它显示完。"""
    def show():
        if cfg.get("sound", True):
            try:
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            except Exception:
                pass
        if not WIN or not cfg.get("popup", True):
            return
        u = ctypes.windll.user32
        flags = 0x40 | 0x40000 | 0x10000
        try:
            u.MessageBoxTimeoutW(0, text, title, flags, 0, 5000)
        except Exception:
            try:
                u.MessageBoxW(0, text, title, flags)
            except Exception:
                pass
    if wait:
        show()
    else:
        threading.Thread(target=show, daemon=True).start()


def render(e):
    names = " / ".join(x for x in e["n"] if x)
    rooms = " / ".join(x for x in e["m"] if x)
    return ("叮叮课表 · 该去上课了",
            "%s 上课｜%s%s\n第 %d 周 · %s" % (
                e["s"], names, (" @" + rooms) if rooms else "", e["w"], e["pl"]))


# ---------------------------------------------------------------- 事件驱动调度

def in_quiet(hhmm, cfg):
    if not cfg.get("quiet_enabled", True):
        return False
    a, b = cfg.get("quiet_start", "22:00"), cfg.get("quiet_end", "07:00")
    return (hhmm >= a or hhmm < b) if a > b else (a <= hhmm < b)


class Scheduler:
    """单次定时器睡到下一个事件；没有 while、没有 sleep(15)、没有全表扫描。"""

    def __init__(self, cfg, entries, on_fire, on_commit, on_state):
        self.cfg = cfg
        self.entries = entries
        self.on_fire = on_fire
        self.on_commit = on_commit
        self.on_state = on_state
        self.lock = threading.Lock()
        self.timer = None
        self.next_at = None
        self.next_kind = None
        self.next_entry = None
        self.fired = set()
        self.committed = set()
        self.wakes = 0          # 到点 / 提交唤醒次数
        self.calibrations = 0   # 校准唤醒次数
        self.polls = 0          # 永远是 0，界面上如实展示

    def _candidates(self, now):
        """纯内存计算，不读文件、不联网。"""
        out = []
        if self.cfg.get("enabled", True):
            mb = int(self.cfg.get("minutes_before", DEFAULT_MINUTES))
            for e in self.entries:
                if self.cfg.get("weekdays_only", True):
                    try:
                        if datetime.strptime(e["d"], "%Y-%m-%d").weekday() >= 5:
                            continue
                    except ValueError:
                        continue
                try:
                    at = (datetime.strptime(e["d"] + " " + e["s"], "%Y-%m-%d %H:%M")
                          - timedelta(minutes=mb))
                except ValueError:
                    continue
                if at < now - timedelta(seconds=LATE_TOLERANCE):
                    continue
                if in_quiet(at.strftime("%H:%M"), self.cfg):
                    continue
                out.append((at, "remind", e))
        if self.cfg.get("log_commit", True):
            t = self.cfg.get("log_time", "23:50")
            for delta in (0, 1, 2):
                day = (now + timedelta(days=delta)).date().isoformat()
                try:
                    at = datetime.strptime(day + " " + t, "%Y-%m-%d %H:%M")
                except ValueError:
                    break
                if at > now:
                    out.append((at, "commit", None))
                    break
        return out

    def reschedule(self):
        with self.lock:
            if self.timer is not None:
                self.timer.cancel()
                self.timer = None
            now = datetime.now()
            cands = self._candidates(now)
            if not cands:
                self.next_at, self.next_kind, self.next_entry = None, "idle", None
                self.on_state(self.snapshot())
                return
            at, kind, entry = min(cands, key=lambda x: x[0])
            wake_at, wake_kind = at, kind
            # 休眠/改时间保护：最多每 30 分钟校准一次；校准不弹窗、不写日志、无 I/O。
            cap = now + timedelta(minutes=CALIBRATE_MINUTES)
            if cap < at:
                wake_at, wake_kind = cap, "calibrate"
            self.next_at, self.next_kind, self.next_entry = at, kind, entry
            delay = max((wake_at - now).total_seconds(), 0.2)
            self.timer = threading.Timer(delay, self._wake, args=(wake_at, wake_kind, entry))
            self.timer.daemon = True
            self.timer.start()
            self.on_state(self.snapshot())

    def _wake(self, target, kind, entry):
        try:
            if kind == "calibrate":
                self.calibrations += 1
            else:
                self.wakes += 1
                late = (datetime.now() - target).total_seconds()
                if late > LATE_TOLERANCE:
                    log(self.cfg, "missed_too_late", "%s 迟到 %.0f 秒，不补弹" % (kind, late),
                        ok=False)
                elif kind == "remind":
                    key = entry["d"] + "-" + entry["p"]
                    if key not in self.fired:
                        self.fired.add(key)
                        title, text = render(entry)
                        notify(self.cfg, title, text)
                        self.on_fire(entry)
                        log(self.cfg, "reminder_fired",
                            "%s %s %s" % (entry["d"], entry["s"], " / ".join(entry["n"])))
                elif kind == "commit":
                    day = target.date().isoformat()
                    if day not in self.committed:
                        self.committed.add(day)
                        threading.Thread(target=self.on_commit, daemon=True).start()
        except Exception as e:
            log(self.cfg, "scheduler_error", "%s %s" % (type(e).__name__, e), ok=False)
        self.reschedule()

    def snapshot(self):
        return {"next_at": self.next_at, "next_kind": self.next_kind,
                "next_entry": self.next_entry, "wakes": self.wakes,
                "calibrations": self.calibrations, "polls": self.polls}


# ---------------------------------------------------------------- 日志提交

def commit_logs(cfg):
    """复用已验证的 Git Data API 提交逻辑，只推 usage_logs/ 一个目录。"""
    result = ""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import commit_usage_logs as cul
        cul.LOG_DIR = log_dir(cfg)
        cul.TOKEN_FILE = token_file(cfg)
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            rc = cul.main()
        finally:
            sys.stdout = old
        lines = [x for x in buf.getvalue().strip().splitlines() if x.strip()]
        result = "exit=%d | %s" % (rc, (lines[-1] if lines else "无输出"))
        if rc != 0:
            log(cfg, "commit_logs_failed", result[:300], ok=False)
    except Exception as e:
        result = "内置提交不可用：%s %s" % (type(e).__name__, e)
        py = cfg.get("python") or shutil.which("python") or shutil.which("py")
        script = repo_root(cfg) / "tools" / "dingding" / "commit_usage_logs.py"
        if py and script.exists():
            try:
                r = subprocess.run([py, str(script)], capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=150)
                tail = ((r.stdout or "").strip().splitlines() or [""])[-1]
                result = "回退 exit=%d | %s" % (r.returncode, tail[:200] or (r.stderr or "")[:200])
            except Exception as e2:
                result += "；回退也失败：%s" % e2
                log(cfg, "commit_logs_failed", result[:300], ok=False)
        else:
            log(cfg, "commit_logs_failed", result[:300], ok=False)
    return result


# ---------------------------------------------------------------- 开机自启 / 安装

def exe_target():
    """自启指向固定位置的那份 EXE，避免仓库/桌面文件被移动后失效。"""
    return INSTALL_DIR / "叮叮课表.exe"


def ensure_installed_copy():
    """自启必须指向固定位置，文件被移动后也不能失效。"""
    target = exe_target()
    if FROZEN and not target.exists():
        INSTALL_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(EXE_PATH, target)
    return target


def set_autostart(on, cfg):
    if winreg is None or not WIN:
        return "只有 Windows 支持开机自启"
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE)
        if on:
            target = ensure_installed_copy()
            winreg.SetValueEx(k, APP, 0, winreg.REG_SZ,
                              '"%s" --minimized' % target)
        else:
            try:
                winreg.DeleteValue(k, APP)
            except FileNotFoundError:
                pass
        winreg.CloseKey(k)
        return "已开启开机自启" if on else "已取消开机自启"
    except Exception as e:
        return "写自启失败：%s %s" % (type(e).__name__, e)


def single_instance():
    if not WIN:
        return True
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW(None, False, "DingDingTimetable_SingleInstance")
        return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return True


def install(cfg, repo, workspace, py):
    if not WIN:
        return "只能在 Windows 上安装"
    if repo:
        cfg["repo_root"] = str(Path(repo).resolve())
    if workspace:
        cfg["workspace_root"] = str(Path(workspace).resolve())
    if py:
        cfg["python"] = py
    cfg["autostart"] = True
    save_settings(cfg)
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    target = ensure_installed_copy()
    msg = set_autostart(True, cfg)
    desktop = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
    try:
        desktop.mkdir(parents=True, exist_ok=True)
        (desktop / "叮叮课表-测试通知.cmd").write_text(
            '@echo off\r\nstart "" "%s" --test\r\n' % target, encoding="ascii")
        (desktop / "叮叮课表-设置.cmd").write_text(
            '@echo off\r\nstart "" "%s"\r\n' % target, encoding="ascii")
    except Exception as e:
        msg += "；桌面入口失败：%s" % e
    log(cfg, "install", "安装到 %s；%s" % (INSTALL_DIR, msg), ok="失败" not in msg)
    if FROZEN:
        try:
            subprocess.Popen([str(target)], creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        except Exception as e:
            msg += "；启动界面失败：%s" % e
    return "安装完成：%s\n%s\n桌面已放「叮叮课表-设置」「叮叮课表-测试通知」两个入口。" % (INSTALL_DIR, msg)


def uninstall(cfg):
    cfg["autostart"] = False
    save_settings(cfg)
    msg = set_autostart(False, cfg)
    log(cfg, "uninstall", msg)
    return msg


# ---------------------------------------------------------------- 图形界面

def launch_gui(cfg, minimized=False):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    entries, source = load_entries(cfg)
    if not entries:
        messagebox.showerror("叮叮课表", "课表是空的，拒绝启动空壳。")
        return 1

    root = tk.Tk()
    root.title("叮叮课表 · 设置与状态")
    root.geometry("760x700")
    root.minsize(700, 620)

    state = {"entries": entries, "source": source, "last_msg": ""}

    # ---- 顶部：下一次提醒 ----
    top = ttk.LabelFrame(root, text="下一次提醒", padding=12)
    top.pack(fill="x", padx=14, pady=(12, 8))
    lbl_next = tk.Label(top, text="计算中…", font=("Microsoft YaHei", 15, "bold"),
                        anchor="w", justify="left", fg="#1f2328")
    lbl_next.pack(fill="x")
    lbl_count = tk.Label(top, text="", font=("Microsoft YaHei", 11), anchor="w", fg="#57606a")
    lbl_count.pack(fill="x", pady=(4, 0))

    # ---- 今天 / 最近上课日 ----
    mid = ttk.LabelFrame(root, text="课程", padding=10)
    mid.pack(fill="both", expand=False, padx=14, pady=4)
    txt = tk.Text(mid, height=7, font=("Microsoft YaHei", 10), wrap="word",
                  bg="#f6f8fa", relief="flat")
    txt.pack(fill="x")

    def refresh_today():
        today = date.today().isoformat()
        es = [e for e in state["entries"] if e["d"] == today]
        head = today
        if not es:
            future = [e for e in state["entries"] if e["d"] > today]
            es = [e for e in future if e["d"] == future[0]["d"]] if future else []
            head = ("今天没课；下一个上课日 " + es[0]["d"]) if es else "学期已结束"
        lines = [head]
        for e in es:
            names = " / ".join(x for x in e["n"] if x)
            rooms = " / ".join(x for x in e["m"] if x)
            lines.append("  %s–%s  %s%s  [%s]" % (
                e["s"], e["e"], names, (" @" + rooms) if rooms else "", e["pl"]))
        txt.configure(state="normal")
        txt.delete("1.0", "end")
        txt.insert("1.0", "\n".join(lines))
        txt.configure(state="disabled")

    # ---- 设置 ----
    frm = ttk.LabelFrame(root, text="设置（改完点「保存并生效」）", padding=10)
    frm.pack(fill="both", expand=True, padx=14, pady=4)
    for i in range(6):
        frm.columnconfigure(i, weight=1)

    v_min = tk.StringVar(value=str(cfg.get("minutes_before", DEFAULT_MINUTES)))
    v_enabled = tk.BooleanVar(value=bool(cfg.get("enabled", True)))
    v_sound = tk.BooleanVar(value=bool(cfg.get("sound", True)))
    v_popup = tk.BooleanVar(value=bool(cfg.get("popup", True)))
    v_autostart = tk.BooleanVar(value=bool(cfg.get("autostart", False)))
    v_quiet = tk.BooleanVar(value=bool(cfg.get("quiet_enabled", True)))
    v_quiet_a = tk.StringVar(value=cfg.get("quiet_start", "22:00"))
    v_quiet_b = tk.StringVar(value=cfg.get("quiet_end", "07:00"))
    v_weekday = tk.BooleanVar(value=bool(cfg.get("weekdays_only", True)))
    v_log = tk.BooleanVar(value=bool(cfg.get("log_commit", True)))
    v_logtime = tk.StringVar(value=cfg.get("log_time", "23:50"))
    v_minstart = tk.BooleanVar(value=bool(cfg.get("minimize_on_start", False)))
    v_courses = tk.StringVar(value=cfg.get("courses_file", ""))

    row = 0
    ttk.Label(frm, text="提前提醒").grid(row=row, column=0, sticky="w")
    ttk.Combobox(frm, textvariable=v_min, width=8, state="readonly",
                 values=["0", "5", "10", "15", "20", "30", "45", "60"]).grid(
        row=row, column=1, sticky="w")
    ttk.Label(frm, text="分钟").grid(row=row, column=2, sticky="w")
    ttk.Checkbutton(frm, text="启用提醒", variable=v_enabled).grid(row=row, column=3, sticky="w")
    ttk.Checkbutton(frm, text="开机自启", variable=v_autostart).grid(row=row, column=4, sticky="w")
    ttk.Checkbutton(frm, text="启动时最小化", variable=v_minstart).grid(row=row, column=5, sticky="w")

    row += 1
    ttk.Checkbutton(frm, text="提示音", variable=v_sound).grid(row=row, column=0, sticky="w")
    ttk.Checkbutton(frm, text="弹窗", variable=v_popup).grid(row=row, column=1, sticky="w")
    ttk.Checkbutton(frm, text="只在工作日", variable=v_weekday).grid(row=row, column=2, sticky="w")
    ttk.Checkbutton(frm, text="静音时段", variable=v_quiet).grid(row=row, column=3, sticky="w")
    ttk.Entry(frm, textvariable=v_quiet_a, width=7).grid(row=row, column=4, sticky="w")
    ttk.Entry(frm, textvariable=v_quiet_b, width=7).grid(row=row, column=5, sticky="w")

    row += 1
    ttk.Checkbutton(frm, text="每天自动提交日志", variable=v_log).grid(row=row, column=0, columnspan=2, sticky="w")
    ttk.Label(frm, text="提交时间").grid(row=row, column=2, sticky="w")
    ttk.Entry(frm, textvariable=v_logtime, width=8).grid(row=row, column=3, sticky="w")
    ttk.Label(frm, text="课表来源：" + state["source"]).grid(
        row=row, column=4, columnspan=2, sticky="w")

    row += 1
    ttk.Label(frm, text="自定义课表文件（留空用内嵌 140 条）").grid(
        row=row, column=0, columnspan=2, sticky="w")
    ttk.Entry(frm, textvariable=v_courses).grid(row=row, column=2, columnspan=3, sticky="ew")
    ttk.Button(frm, text="浏览", command=lambda: v_courses.set(
        filedialog.askopenfilename(filetypes=[("JSON", "*.json")]) or v_courses.get())
    ).grid(row=row, column=5, sticky="w")

    row += 1
    ttk.Label(frm, text="仓库根目录（日志提交用）").grid(row=row, column=0, columnspan=2, sticky="w")
    v_repo = tk.StringVar(value=cfg.get("repo_root", ""))
    ttk.Entry(frm, textvariable=v_repo).grid(row=row, column=2, columnspan=4, sticky="ew")

    # ---- 按钮 ----
    bar = ttk.Frame(root, padding=(14, 4))
    bar.pack(fill="x")

    def set_status(msg):
        state["last_msg"] = msg
        lbl_status.configure(text=msg)

    def on_fire(entry):
        root.after(0, lambda: set_status("已弹提醒：%s %s" % (entry["d"], " / ".join(entry["n"]))))
        root.after(0, refresh_today)

    def on_commit():
        msg = commit_logs(cfg)
        root.after(0, lambda: set_status("日志同步：%s" % msg))

    def on_state(snap):
        def paint():
            at, kind, e = snap["next_at"], snap["next_kind"], snap["next_entry"]
            if at is None:
                lbl_next.configure(text="学期已结束 / 没有后续提醒")
                lbl_count.configure(text="")
            else:
                what = "日志自动提交" if kind == "commit" else (
                    " / ".join(x for x in e["n"] if x) if e else kind)
                lbl_next.configure(text="%s  %s" % (at.strftime("%m月%d日 %H:%M"), what))
            lbl_polls.configure(text="轮询 %d 次 ｜ 到点唤醒 %d 次 ｜ 30 分钟校准 %d 次"
                                      % (snap["polls"], snap["wakes"], snap["calibrations"]))
        root.after(0, paint)

    scheduler = Scheduler(cfg, state["entries"], on_fire, on_commit, on_state)

    def save():
        try:
            mb = int(v_min.get())
            datetime.strptime(v_quiet_a.get(), "%H:%M")
            datetime.strptime(v_quiet_b.get(), "%H:%M")
            datetime.strptime(v_logtime.get(), "%H:%M")
            c = dict(cfg)
            c.update({"minutes_before": mb, "enabled": v_enabled.get(),
                      "sound": v_sound.get(), "popup": v_popup.get(),
                      "autostart": v_autostart.get(), "quiet_enabled": v_quiet.get(),
                      "quiet_start": v_quiet_a.get(), "quiet_end": v_quiet_b.get(),
                      "weekdays_only": v_weekday.get(), "log_commit": v_log.get(),
                      "log_time": v_logtime.get(), "minimize_on_start": v_minstart.get(),
                      "courses_file": v_courses.get().strip(),
                      "repo_root": v_repo.get().strip()})
            if c["courses_file"] != cfg.get("courses_file", ""):
                state["entries"], state["source"] = load_entries(c)
                scheduler.entries = state["entries"]
                refresh_today()
            save_settings(c)
            cfg.clear()
            cfg.update(c)
            scheduler.cfg = cfg
            msg = set_autostart(v_autostart.get(), cfg)
            scheduler.reschedule()
            log(cfg, "settings_saved",
                "提前%d分 提醒=%s 自启=%s 日志=%s@%s 课表=%s" % (
                    mb, v_enabled.get(), v_autostart.get(), v_log.get(),
                    v_logtime.get(), state["source"]))
            set_status("已保存并生效；%s。共 %d 条课程。" % (msg, len(state["entries"])))
        except Exception as e:
            messagebox.showerror("设置没保存", "%s %s" % (type(e).__name__, e))

    ttk.Button(bar, text="保存并生效", command=save).pack(side="left")
    ttk.Button(bar, text="立即测试通知", command=lambda: (
        notify(cfg, "叮叮课表 · 测试", "这就是上课提醒的样子，5 秒后自动关闭。"),
        log(cfg, "test_notification", "使用者点了「立即测试通知」"),
        set_status("已发一条测试通知（5 秒自动关）。"))).pack(side="left", padx=6)
    ttk.Button(bar, text="立即同步日志", command=lambda: threading.Thread(
        target=on_commit, daemon=True).start()).pack(side="left")

    bar2 = ttk.Frame(root, padding=(14, 4))
    bar2.pack(fill="x")

    def open_path(p, label):
        if Path(p).exists():
            os.startfile(str(p))
        else:
            set_status("%s 不存在：%s" % (label, p))

    r = repo_root(cfg)
    ttk.Button(bar2, text="打开课表网页", command=lambda: open_path(
        r / "tools" / "dingding" / "windows" / "叮叮课表.html", "课表网页")).pack(side="left")
    ttk.Button(bar2, text="导入系统日历(.ics)", command=lambda: open_path(
        r / "tools" / "dingding" / "windows" / "叮叮课表.ics", "ics")).pack(side="left", padx=6)
    ttk.Button(bar2, text="打开日志目录", command=lambda: open_path(log_dir(cfg), "日志目录")).pack(side="left")
    ttk.Button(bar2, text="最小化", command=root.iconify).pack(side="right")
    ttk.Button(bar2, text="退出程序", command=lambda: (
        log(cfg, "app_exit", "使用者点了退出"),
        root.destroy())).pack(side="right", padx=6)

    foot = ttk.Frame(root, padding=(14, 6))
    foot.pack(fill="x")
    lbl_polls = tk.Label(foot, text="", font=("Microsoft YaHei", 9), fg="#57606a", anchor="w")
    lbl_polls.pack(fill="x")
    tk.Label(foot, text="调度：单次定时器睡到下一个事件；不扫表、不常驻轮询、不联网查课表。"
                        "倒计时每秒只做一次减法。",
             font=("Microsoft YaHei", 9), fg="#57606a", anchor="w").pack(fill="x")
    lbl_status = tk.Label(foot, text="就绪", font=("Microsoft YaHei", 9),
                          fg="#1a7f37", anchor="w")
    lbl_status.pack(fill="x", pady=(3, 0))

    def tick():
        """只刷新界面上的倒计时数字，纯算术，无 I/O。"""
        snap = scheduler.snapshot()
        at = snap["next_at"]
        if at:
            delta = at - datetime.now()
            sec = int(delta.total_seconds())
            if sec >= 0:
                lbl_count.configure(text="还有 %d 天 %02d:%02d:%02d ｜ 提前 %s 分钟提醒" % (
                    sec // 86400, (sec % 86400) // 3600, (sec % 3600) // 60,
                    sec % 60, cfg.get("minutes_before", DEFAULT_MINUTES)))
            else:
                lbl_count.configure(text="正在响起…")
        root.after(1000, tick)

    scheduler.reschedule()
    refresh_today()
    tick()
    log(cfg, "app_start", "EXE 启动，%d 条课程，来源 %s" % (len(entries), source))

    def on_close():
        # 关窗口 = 最小化，不偷偷留黑框进程；要退出请点「退出程序」。
        root.iconify()
        set_status("窗口已最小化到任务栏；点「退出程序」才真正退出。")

    root.protocol("WM_DELETE_WINDOW", on_close)
    if minimized or cfg.get("minimize_on_start"):
        root.iconify()
    root.mainloop()
    return 0


# ---------------------------------------------------------------- 自检 / CLI

def selftest(cfg):
    entries, source = load_entries(cfg)
    s = Scheduler(cfg, entries, lambda e: None, lambda: None, lambda x: None)
    now = datetime.now()
    cands = s._candidates(now)
    nxt = min(cands, key=lambda x: x[0]) if cands else None
    lines = [
        "叮叮课表 EXE 自检",
        "时间           " + now.strftime("%Y-%m-%d %H:%M:%S"),
        "课表条数       %d" % len(entries),
        "课表来源       " + source,
        "覆盖日期       %s ~ %s" % (entries[0]["d"], entries[-1]["d"]),
        "设置文件       " + str(SETTINGS_PATH),
        "仓库根         " + str(repo_root(cfg)),
        "日志目录       " + str(log_dir(cfg)),
        "凭据文件       %s（存在=%s）" % (token_file(cfg), token_file(cfg).exists()),
        "下一次事件     " + (("%s %s" % (nxt[0].strftime("%Y-%m-%d %H:%M"), nxt[1]))
                          if nxt else "无"),
        "调度方式       单次 Timer；轮询 0 次；校准间隔 %d 分钟" % CALIBRATE_MINUTES,
        "内嵌 EXE       " + ("是" if FROZEN else "否（源码运行）"),
    ]
    out = "\n".join(lines)
    cli_write(out)
    return 0


def main():
    ap = argparse.ArgumentParser(description="叮叮课表 Windows EXE")
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--commit-logs", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--minimized", action="store_true")
    ap.add_argument("--repo-root", default="")
    ap.add_argument("--workspace", default="")
    ap.add_argument("--python", default="")
    a = ap.parse_args()

    cfg = load_settings()
    if a.install:
        msg = install(cfg, a.repo_root, a.workspace, a.python)
        cli_write(msg)
        notify(cfg, "叮叮课表 · 安装完成", "这就是上课提醒的样子，5 秒后自动关闭。", wait=True)
        return 0
    if a.uninstall:
        cli_write(uninstall(cfg))
        return 0
    if a.test:
        notify(cfg, "叮叮课表 · 测试", "这就是上课提醒的样子，5 秒后自动关闭。", wait=True)
        log(cfg, "test_notification", "命令行 --test 触发")
        cli_write("已弹一条测试通知（5 秒自动关），并写入真实日志。")
        return 0
    if a.commit_logs:
        msg = commit_logs(cfg)
        cli_write("日志同步：%s" % msg)
        return 0
    if a.selftest:
        return selftest(cfg)
    if a.status:
        entries, source = load_entries(cfg)
        cli_write("课表 %d 条（%s）\n设置 %s\n自启 %s\n日志目录 %s" % (
            len(entries), source, SETTINGS_PATH, cfg.get("autostart"), log_dir(cfg)))
        return 0
    if not single_instance():
        cli_write("叮叮课表已经在运行了（任务栏里找窗口）。")
        return 0
    return launch_gui(cfg, minimized=a.minimized)


if __name__ == "__main__":
    sys.exit(main())

"""业务插件注册表。

换校园痛点只改这里：把新模块名加进 REGISTRY，并在 config 的 tasks 里启用。
插件必须实现 run(cfg, emit) -> dict；emit 的签名见 telemetry.Telemetry.emit。
插件内部每条真实调用都要 emit 一次，外层不再重复计数。
"""
import importlib

REGISTRY = {
    "source_probe": "tasks.source_probe",
}


def available():
    return sorted(REGISTRY)


def load(name):
    if name not in REGISTRY:
        raise KeyError("未注册的任务 %r；可用：%s" % (name, ", ".join(available())))
    return importlib.import_module(REGISTRY[name])

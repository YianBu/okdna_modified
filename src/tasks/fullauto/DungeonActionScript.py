"""自由填充的「行动逻辑」：一个 JSON 文件就是一段行动序列，任务只负责逐条执行。

为什么要放外部文件：走位 / 解谜 / 开战条件这些要反复试，写死在 Python 里每次都得
重启程序；放在这里改完只要重开那个测试任务，马上就能再跑一遍。

文件位置：mod/行动逻辑/*.json（目录不存在时任务会生成一份带说明的模板）。
一个文件就是一段序列（想要几段就建几个文件，任务配置里选）：

    {
      "_说明": "下划线开头的字段程序不看，随便写",
      "note": "进本后先上台阶（可选，只写进日志）",
      "steps": [
        {"type": "log", "text": "起步"},
        {"type": "key", "key": "w", "seconds": 1.5},
        {"type": "wait", "seconds": 0.3},
        {"type": "key", "key": "space", "seconds": 0.05}
      ]
    }

顶层也可以直接就是一个数组（那就是 steps 本身），省掉外面那层对象。

支持的步骤（steps 里按顺序执行）：

    {"type": "log",          "text": "随便一个标记"}
    {"type": "key",          "key": "w", "seconds": 1.2}   按住某键 N 秒
    {"type": "key_down",     "key": "w"}                   按下不放
    {"type": "key_up",       "key": "w"}
    {"type": "wait",         "seconds": 0.5}               纯等待
    {"type": "mouse_move",   "dx": 120, "dy": 0}           相对转视角（走游戏灵敏度换算）
    {"type": "click",        "x": 0.5, "y": 0.5}           点屏幕相对位置
    {"type": "until_combat", "key": "w", "timeout": 20, "extra": 2}
                                                           按住 key 一直走到进战斗
    {"type": "repeat",       "times": 3, "steps": [...]}   嵌套重复
    {"type": "call",         "method": "execute_xxx"}      调任务上的 Python 方法

键名就用框架认的那套：字母直接写（w / a / s / d）、space、enter、esc、lshift 之类。
call 是逃生口：常见走位用 JSON 填就够，真需要识别 / 分支的复杂逻辑就写成任务上的
Python 方法，JSON 里点名调用 —— 两头都不用改执行器。
"""

import json
import time
from pathlib import Path

SCRIPT_DIR = Path("mod") / "行动逻辑"
SCRIPT_SUFFIX = ".json"
TEMPLATE_NAME = "示例-行动逻辑.json"

# 自动生成的模板：每种步骤各写一条，照着改就行
TEMPLATE = {
    "_说明": [
        "这是「自由填充行动逻辑」的模板：程序只认 steps，下划线开头的字段随便写。",
        "改完不需要重启程序，重新开始「行动逻辑脚本测试」会重新读这个文件。",
        "steps 支持的 type 见 src/tasks/fullauto/DungeonActionScript.py 顶部的说明。",
    ],
    "note": "演示用，把 steps 整个换成你自己的行动序列",
    "steps": [
        {"type": "log", "text": "开始走位"},
        {"type": "key", "key": "w", "seconds": 1.0},
        {"type": "wait", "seconds": 0.3},
        {"type": "key", "key": "space", "seconds": 0.05},
        {"type": "repeat", "times": 2, "steps": [
            {"type": "key", "key": "w", "seconds": 0.5},
        ]},
        {"type": "until_combat", "key": "w", "timeout": 20, "extra": 2},
    ],
}


class ActionScriptError(Exception):
    """行动逻辑文件写错了 / 走到一半条件不满足。"""


def script_dir(base=None):
    return (base or Path.cwd()) / SCRIPT_DIR


def list_scripts(base=None):
    """可用行动逻辑文件的名字（按名字排序）。"""
    folder = script_dir(base)
    if not folder.is_dir():
        return []
    return sorted(p.name for p in folder.glob("*" + SCRIPT_SUFFIX))


def ensure_template(base=None):
    """目录/模板不存在就生成一份，返回模板路径；目的是"打开就能填"。"""
    folder = script_dir(base)
    template = folder / TEMPLATE_NAME
    if template.exists():
        return None
    folder.mkdir(parents=True, exist_ok=True)
    with open(template, "w", encoding="utf-8") as f:
        json.dump(TEMPLATE, f, ensure_ascii=False, indent=2)
    return template


def load_script(path):
    """读一个行动逻辑文件，返回 {"note": ..., "steps": [...]}。

    顶层可以是 {"steps": [...]}，也可以直接就是 [...]（steps 本身）。
    """
    path = Path(path)
    if not path.is_file():
        raise ActionScriptError(f"行动逻辑文件不存在：{path}")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise ActionScriptError(f"行动逻辑文件读不出来（{path}）：{e}")
    if isinstance(data, list):
        data = {"steps": data}
    if not isinstance(data, dict):
        raise ActionScriptError("行动逻辑文件顶层要是 {...} 或 [...]")
    steps = data.get("steps")
    if steps is None:
        steps = []
    if not isinstance(steps, list):
        raise ActionScriptError("steps 要是数组")
    return {"note": data.get("note"), "steps": steps}


# ----------------------------------------------------------------------
# 执行步骤
# ----------------------------------------------------------------------
def run_steps(task, steps, depth=0):
    """逐条执行步骤，返回执行条数。写错时抛 ActionScriptError（带上是第几步）。"""
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise ActionScriptError(f"第 {index} 步要是个对象，实际是 {type(step).__name__}")
        kind = step.get("type")
        handler = STEP_HANDLERS.get(kind)
        if handler is None:
            raise ActionScriptError(
                "第 %d 步的 type「%s」不认识，支持：%s" % (index, kind, "、".join(sorted(STEP_HANDLERS))))
        try:
            handler(task, step, depth)
        except ActionScriptError:
            raise
        except KeyError as e:
            raise ActionScriptError(f"第 {index} 步（{kind}）缺少字段：{e}")
        except Exception as e:
            raise ActionScriptError(f"第 {index} 步（{kind}）执行出错：{e}")
    return len(steps)


def _log(task, step, depth):
    task.log_info("[行动逻辑]" + "  " * depth + str(step.get("text", "")))


def _key(task, step, depth):
    task.send_key(step["key"], down_time=float(step.get("seconds", 0.2)))


def _key_down(task, step, depth):
    task.send_key_down(step["key"])


def _key_up(task, step, depth):
    task.send_key_up(step["key"])


def _wait(task, step, depth):
    task.sleep(float(step.get("seconds", 0.5)))


def _mouse_move(task, step, depth):
    task.move_mouse_relative(int(step.get("dx", 0)), int(step.get("dy", 0)))


def _click(task, step, depth):
    task.click_relative(float(step.get("x", 0.5)), float(step.get("y", 0.5)),
                        after_sleep=float(step.get("after_sleep", 0.2)))


def _until_combat(task, step, depth):
    """按住某个键一直走，直到开战判据成立；走满 timeout 还没开战就报错。

    和原版「自动前进到开战」同一套判据（扼守看波次、探险看血清），只是按键和超时可填。
    """
    key = step.get("key", "w")
    timeout = float(step.get("timeout", 20))
    extra = float(step.get("extra", 0))
    task.send_key_down(key)
    try:
        deadline = time.time() + timeout
        while time.time() < deadline:
            task.next_frame()
            if task.is_in_combat():
                if extra > 0:
                    extra_deadline = time.time() + extra
                    while time.time() < extra_deadline:
                        task.next_frame()
                return
        raise ActionScriptError(f"按住 {key} 走了 {timeout:g} 秒还没进战斗")
    finally:
        task.send_key_up(key)


def _repeat(task, step, depth):
    times = int(step.get("times", 1))
    inner = step.get("steps") or []
    if not isinstance(inner, list):
        raise ActionScriptError("repeat 的 steps 要是数组")
    for _ in range(max(0, times)):
        run_steps(task, inner, depth + 1)


def _call(task, step, depth):
    method = step.get("method")
    func = getattr(task, method, None)
    if not callable(func):
        raise ActionScriptError(f"任务上没有方法「{method}」")
    func()


STEP_HANDLERS = {
    "log": _log,
    "key": _key,
    "key_down": _key_down,
    "key_up": _key_up,
    "wait": _wait,
    "mouse_move": _mouse_move,
    "click": _click,
    "until_combat": _until_combat,
    "repeat": _repeat,
    "call": _call,
}

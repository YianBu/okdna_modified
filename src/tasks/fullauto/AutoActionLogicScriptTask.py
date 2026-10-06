from qfluentwidgets import FluentIcon

from ok import Logger, TaskDisabledException

from src.tasks.DNAOneTimeTask import DNAOneTimeTask
from src.tasks.CommissionsTask import CommissionsTask
from src.tasks.BaseCombatTask import BaseCombatTask
from src.tasks.fullauto.DungeonActionScript import (
    ActionScriptError,
    ensure_template,
    list_scripts,
    load_script,
    run_steps,
    script_dir,
)
from src.tasks.TaskHotkey import DEFAULT_KEY as DEFAULT_HOTKEY
from src.tasks.TaskHotkey import KEY_OPTIONS as HOTKEY_OPTIONS

logger = Logger.get_logger(__name__)


class AutoActionLogicScriptTask(DNAOneTimeTask, CommissionsTask, BaseCombatTask):
    """自由填充的行动逻辑测试：一段行动序列写在 mod/行动逻辑/*.json 里，任务原样跑一遍。

    和「行动逻辑测试」（AutoDungeonActionTestTask）的分工：那边是"判地图 -> 跑对应
    地图的逻辑"，逻辑写成了 Python 方法；这个不管地图，只干一件事 —— 把你填的这段
    序列（按键 / 走位 / 等待 / 开战条件）按顺序执行。

    用法：
      1) 第一次启动会在 mod/行动逻辑/ 生成「示例-行动逻辑.json」，照着填你自己的序列；
      2) 配置里选「行动逻辑文件」（一个文件就是一段序列，想要几段就建几个文件）；
      3) 进本后按「快捷启动键」（默认 F8）可以随时重跑：改完 JSON 再按一次，
         任务重新启动、重新读文件、再跑一遍。

    步骤类型和字段含义见 DungeonActionScript 模块顶部的说明；需要识别 / 分支的复杂
    逻辑可以写成任务上的 Python 方法，JSON 里用 {"type": "call", "method": "..."} 调。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.icon = FluentIcon.FLAG
        self.name = "行动逻辑脚本测试"
        self.description = "测试"
        self.group_name = "测试"
        self.group_icon = FluentIcon.DEVELOPER_TOOLS

        # 顺手把目录和模板建好，用户打开就能看到该往哪填
        created = ensure_template()
        scripts = list_scripts()

        self.default_config.update({
            "行动逻辑文件": scripts[0] if scripts else "",
            "重复次数": 1,
            "快捷启动键": DEFAULT_HOTKEY,
        })
        self.config_type["行动逻辑文件"] = {"type": "drop_down", "options": scripts}
        self.config_type["快捷启动键"] = {"type": "drop_down", "options": list(HOTKEY_OPTIONS)}
        self.config_description.update({
            "行动逻辑文件": "mod/行动逻辑/ 下的序列；改完重开这个任务就会重新读，不用重启程序",
            "重复次数": "连续跑几遍这段序列；0 = 一直重复到手动停止",
            "快捷启动键": "按这个键启动 / 停止本任务（游戏里也认，不用切回程序点按钮）："
                          "没在跑就启动，正在跑就停止，再按一次就是重跑并重新读一遍 JSON",
        })
        if created:
            self.log_info(f"已生成行动逻辑模板：{created}（照着填就行）")

    # ------------------------------------------------------------------
    # 配置 / 文件
    # ------------------------------------------------------------------
    def script_path(self):
        name = self.config.get("行动逻辑文件") or ""
        return script_dir() / name if name else None

    def load_action_steps(self):
        """读当前配置的那个行动逻辑文件，返回 {"note": ..., "steps": [...]}。"""
        path = self.script_path()
        if path is None:
            raise ActionScriptError(f"{script_dir()} 下没有行动逻辑文件，先填一个再启动")
        data = load_script(path)
        return data

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def run(self):
        DNAOneTimeTask.run(self)
        self.move_mouse_to_safe_position(save_current_pos=False)
        self.set_check_monthly_card()
        try:
            return self.do_run()
        except ActionScriptError as e:
            logger.error("AutoActionLogicScriptTask 行动逻辑出错", e)
            self.log_info_notify(f"行动逻辑出错：{e}")
            self.soundBeep()
        except TaskDisabledException:
            pass
        except Exception as e:
            logger.error("AutoActionLogicScriptTask error", e)
            raise

    def do_run(self):
        self.load_char()
        data = self.load_action_steps()
        steps = data["steps"]
        self.log_info(f"『行动逻辑脚本测试』：{len(steps)} 步，来自 {self.script_path()}")
        if data.get("note"):
            self.log_info(f"说明：{data['note']}")
        self.log_info_notify("行动逻辑脚本测试已启动，请进入副本")
        while True:
            self.next_frame()
            if not self.in_team():
                self.sleep(1)
                continue
            break

        if not steps:
            self.log_info_notify("这个行动逻辑文件里还没填 steps，测试结束")
            self.soundBeep()
            return

        repeat = int(self.config.get("重复次数", 1) or 0)
        loop = repeat <= 0
        done = 0
        while loop or done < repeat:
            done += 1
            self.log_info(f"[测试] 第 {done} 遍：执行 {len(steps)} 步")
            try:
                run_steps(self, steps)
            except ActionScriptError as e:
                raise ActionScriptError(f"第 {done} 遍：{e}")
            self.log_info(f"[测试] 第 {done} 遍执行完毕")
            if done == repeat:
                break
        self.log_info_notify(f"行动逻辑执行完毕（{done} 遍）")
        self.soundBeep()

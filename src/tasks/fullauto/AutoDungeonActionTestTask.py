from qfluentwidgets import FluentIcon

from ok import Logger, TaskDisabledException

from src.tasks.DNAOneTimeTask import DNAOneTimeTask
from src.tasks.CommissionsTask import CommissionsTask
from src.tasks.BaseCombatTask import BaseCombatTask
from src.tasks.fullauto.DungeonActionLogic import DUNGEON_MAPS
from src.tasks.fullauto.DungeonActionMixin import DungeonActionMixin

logger = Logger.get_logger(__name__)

# 「测试地图」下拉里代表"不强制、按图标位置自动判"的那个选项
AUTO_DETECT = "自动检测"


class AutoDungeonActionTestTask(DungeonActionMixin, DNAOneTimeTask, CommissionsTask, BaseCombatTask):
    """「测试」板块里的「行动逻辑测试」：把判地图 -> 外部行动逻辑单独拎出来手动跑。

    用途是在真机上逐张核对扼守/探险密函副本的检测框与走位（格子）：启动后进入副本，
    它按「测试地图」配置决定跑哪张图的行动逻辑 ——

    * 「自动检测」：按固定的图标位置（DungeonActionLogic.DUNGEON_MAPS 里的
      track_point）判当前是哪张图，再执行它的行动逻辑；判不出来会响铃提示。
    * 指定某张图：跳过检测、直接执行那张图的行动逻辑，方便反复调试同一张图。
    * 勾「只检测不执行」：只判地图、不走位，专门用来核对检测框对不对。

    判地图、走位、开战判据和「扼守探险开密函」共用 DungeonActionMixin，所以这里测通的
    行为，正式任务里就是同一份。格子逻辑还是占位（复用原版），测好后替换
    DungeonActionMixin 里对应的 execute_* 方法即可。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.icon = FluentIcon.FLAG
        self.name = "行动逻辑测试"
        self.description = "测试"
        self.group_name = "测试"
        self.group_icon = FluentIcon.DEVELOPER_TOOLS

        self.default_config.update({
            "测试地图": AUTO_DETECT,
            "只检测不执行": False,
        })
        self.config_type["测试地图"] = {
            "type": "drop_down",
            "options": [AUTO_DETECT] + list(DUNGEON_MAPS.keys()),
        }
        self.config_description.update({
            "测试地图": "选一张图强制跑它的行动逻辑；「自动检测」则按图标位置判当前地图",
            "只检测不执行": "只按图标判地图、不执行走位，用来核对检测框是否正确",
        })
        # DungeonActionMixin.walk_to_aim 会读它；这里直接调 detect_current_map(None)，
        # 不走 walk_to_aim，但补上以免被别处调用时 AttributeError。
        self._dungeon_mode = None

    def run(self):
        DNAOneTimeTask.run(self)
        self.move_mouse_to_safe_position(save_current_pos=False)
        self.set_check_monthly_card()
        try:
            return self.do_run()
        except TaskDisabledException:
            pass
        except Exception as e:
            logger.error("AutoDungeonActionTestTask error", e)
            raise

    def do_run(self):
        self.load_char()
        self.log_info("『行动逻辑测试』：进入副本后按配置执行对应地图的行动逻辑")
        self.log_info_notify("行动逻辑测试已启动，请进入副本")
        while True:
            self.next_frame()
            if not self.in_team():
                self.log_info("等待进入副本……")
                self.sleep(1)
                continue

            map_name = self.pick_test_map()
            if map_name is None:
                self.log_info_notify("没识别到任何地图（检测框都没命中），测试结束")
                self.soundBeep()
                return
            self.log_info(f"[测试] 当前地图：{map_name}")

            if self.config.get("只检测不执行", False):
                self.log_info("[测试] 只检测不执行，测试结束")
                self.soundBeep()
                return

            self.log_info(f"[测试] 执行「{map_name}」的行动逻辑")
            self.run_dungeon_action(map_name)
            self.log_info("[测试] 本次行动逻辑执行完毕")
            self.soundBeep()
            return

    def pick_test_map(self):
        """要测哪张图：配置点名了就按配置，否则按图标位置自动判。"""
        choice = self.config.get("测试地图", AUTO_DETECT)
        if choice in DUNGEON_MAPS:
            self.log_info(f"[测试] 按配置强制使用地图「{choice}」")
            return choice
        return self.detect_current_map(None)

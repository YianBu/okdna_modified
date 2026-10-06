# 「测试」板块 -「行动逻辑测试」任务：配置面 + 选图 + 只检测不执行
#
# 用例只钉任务自己的行为（选哪张图、跑不跑走位），不碰真机与截图：
# 判地图/走位本身在 DungeonActionMixin，已由 test_letter_open_dungeon 覆盖。
import unittest

from ok.test.TaskTestCase import TaskTestCase

from src.config import config
from src.tasks.fullauto.AutoDungeonActionTestTask import (
    AUTO_DETECT,
    AutoDungeonActionTestTask,
)
from src.tasks.fullauto.DungeonActionLogic import DUNGEON_MAPS
from src.tasks.fullauto.DungeonActionMixin import DungeonActionMixin
from src.tasks.fullauto.AutoLetterOpenTask import AutoLetterOpenTask


class TestDungeonActionTestTask(TaskTestCase):
    task_class = AutoDungeonActionTestTask
    config = config

    _PATCHED = ('in_team', 'next_frame', 'sleep', 'soundBeep', 'run_dungeon_action',
                'log_info', 'log_info_notify', 'config', 'load_char',
                'detect_current_map')

    def setUp(self):
        self._saved = {name: getattr(self.task, name) for name in self._PATCHED}
        self.task.next_frame = lambda *a, **k: None
        self.task.sleep = lambda seconds: None
        self.task.soundBeep = lambda *a, **k: None
        self.task.load_char = lambda: None
        self.task.in_team = lambda *a, **k: True

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(self.task, name, value)
        super().tearDown()

    # ---- 归到「测试」板块，和「自动开密函」共用同一份行动逻辑 ----

    def test_belongs_to_test_group(self):
        self.assertEqual(self.task.group_name, "测试")
        self.assertEqual(self.task.name, "行动逻辑测试")
        self.assertIsInstance(self.task, DungeonActionMixin)
        self.assertNotIsInstance(self.task, AutoLetterOpenTask,
                                 "是独立的测试任务，只和开密函共用 mixin")

    def test_shared_mixin_by_both_tasks(self):
        self.assertTrue(issubclass(AutoDungeonActionTestTask, DungeonActionMixin))
        self.assertTrue(issubclass(AutoLetterOpenTask, DungeonActionMixin))

    # ---- 配置面 ----

    def test_config_defaults(self):
        self.assertEqual(self.task.default_config["测试地图"], AUTO_DETECT)
        self.assertFalse(self.task.default_config["只检测不执行"])

    def test_map_options_cover_all_maps(self):
        options = self.task.config_type["测试地图"]["options"]
        self.assertEqual(options[0], AUTO_DETECT, "第一项是自动检测")
        self.assertEqual(set(options[1:]), set(DUNGEON_MAPS.keys()))

    # ---- 选图：点名就按配置，否则自动判 ----

    def test_pick_map_honours_config_choice(self):
        self.task.config = {"测试地图": "探险高台"}
        self.task.detect_current_map = lambda mode=None: self.fail("点名了就不该再检测")
        self.assertEqual(self.task.pick_test_map(), "探险高台")

    def test_pick_map_auto_detects(self):
        self.task.config = {"测试地图": AUTO_DETECT}
        self.task.detect_current_map = lambda mode=None: "探险平地"
        self.assertEqual(self.task.pick_test_map(), "探险平地")

    # ---- 跑：强制图/自动判都派发到行动函数；只检测则不派发 ----

    def test_runs_forced_map_action(self):
        self.task.config = {"测试地图": "扼守斜走", "只检测不执行": False}
        calls = []
        self.task.run_dungeon_action = lambda name: calls.append(name)
        self.task.do_run()
        self.assertEqual(calls, ["扼守斜走"])

    def test_runs_detected_map_action(self):
        self.task.config = {"测试地图": AUTO_DETECT, "只检测不执行": False}
        self.task.detect_current_map = lambda mode=None: "探险平地"
        calls = []
        self.task.run_dungeon_action = lambda name: calls.append(name)
        self.task.do_run()
        self.assertEqual(calls, ["探险平地"])

    def test_dry_run_does_not_execute(self):
        self.task.config = {"测试地图": "探险平地", "只检测不执行": True}
        calls = []
        self.task.run_dungeon_action = lambda name: calls.append(name)
        self.task.do_run()
        self.assertEqual(calls, [], "只检测不执行时不该走位")

    def test_no_map_detected_ends_quietly(self):
        self.task.config = {"测试地图": AUTO_DETECT, "只检测不执行": False}
        self.task.detect_current_map = lambda mode=None: None
        calls = []
        self.task.run_dungeon_action = lambda name: calls.append(name)
        self.task.do_run()
        self.assertEqual(calls, [], "没判出地图就不该执行任何行动逻辑")


if __name__ == '__main__':
    unittest.main()

# 自动开密函：图1 列表解析 + 覆盖 do_run 后继承来的状态
#
# 这些用例不依赖真机截图：把 task.ocr 换成"喂一份仿真 OCR 结果"，直接钉住解析逻辑
# （哪一栏、是不是驱离、有没有开完、坐标框怎么划）。真机截图会变、坐标框也会调，
# 但"驱逐不是驱离""密函奖励界面不是列表"这类规则不应该跟着变。
import time
import unittest

from ok.feature.Box import Box
from ok.test.TaskTestCase import TaskTestCase

from src.config import config
from src.dna_ui.Defs import LETTER_BOARD_COLUMN_X, SCREEN_BOX
from src.tasks.fullauto.AutoLetterOpenTask import AutoLetterOpenTask, COLUMN_NAMES


def box(x, y, name, w=60, h=24):
    return Box(x, y, w, h, 0.99, name)


# 图1 列表的仿真 OCR 结果，坐标取自实测截图（1600x900 基准）：
# 角色 持有数35 / 武器 持有数50 / 魔之楔 持有数815，且「驱逐」和「驱离」同屏出现。
BOARD_OCR = [
    box(216, 340, '角色'), box(560, 340, '武器'), box(891, 339, '魔之楔'),
    box(201, 374, '持有数35'), box(545, 375, '持有数50'), box(887, 375, '持有数815'),
    box(204, 439, '当前开放'), box(550, 442, '当前开放'), box(892, 442, '当前开放'),
    box(110, 496, '探险/无尽'), box(322, 496, 'Lv.40'),
    box(108, 559, '调停'), box(452, 561, '驱逐'),
    box(796, 631, '驱离'), box(1009, 631, 'Lv.40'),
]


class TestLetterOpen(TaskTestCase):
    task_class = AutoLetterOpenTask
    config = config

    _PATCHED = ('screen_box', 'draw_boxes', 'ocr', 'in_team', 'move_on_begin',
                'random_walk_tick', 'skill_tick', 'config')

    def setUp(self):
        # 同一个 task 实例被整个类共用，打了桩要还原，别串到别的用例
        self._saved = {name: getattr(self.task, name) for name in self._PATCHED}

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(self.task, name, value)
        super().tearDown()

    def stub_board(self, results):
        """把"读整块列表"替换成喂一份固定的 OCR 结果。"""
        self.task.screen_box = lambda name: box(60, 320, name, 1050, 380)
        self.task.draw_boxes = staticmethod(lambda *a, **k: None)
        self.task.ocr = lambda **kw: list(results)
        self.task._board_cache = None
        self.task._board_cache_time = 0

    # ---- 图1 列表解析 ----

    def test_scan_letter_board(self):
        self.stub_board(BOARD_OCR)
        data = self.task.scan_letter_board(force=True)
        self.assertTrue(data['on_board'], '三栏标题 + 当前开放 都在，应该判为列表')
        self.assertEqual(data['counts'], [35, 50, 815], '三栏的持有数要各归各栏')
        self.assertEqual([None if b is None else b.name for b in data['drive_away']],
                         [None, None, '驱离'], '驱离只在魔之楔那栏')

    def test_drive_away_is_not_quzhu(self):
        """「驱逐」和「驱离」是两个任务；按「驱」前缀匹配就会去点错的那个。"""
        self.stub_board([
            box(204, 439, '当前开放'), box(550, 442, '当前开放'), box(892, 442, '当前开放'),
            box(110, 496, '驱逐'), box(452, 559, '驱逐'), box(796, 631, '驱逐'),
        ])
        data = self.task.scan_letter_board(force=True)
        self.assertTrue(data['on_board'])
        self.assertEqual(data['drive_away'], [None, None, None], '驱逐不该被当成驱离')

    def test_letter_reward_screen_is_not_board(self):
        """密函奖励界面同位置也有「持有数」，但它没有三栏标题/当前开放，不能算图1。"""
        self.stub_board([
            box(512, 584, '持有数：'), box(598, 586, '22'),
            box(748, 584, '持有数：'), box(817, 584, '36440'),
            box(977, 584, '持有数：'), box(1045, 584, '36440'),
        ])
        self.assertFalse(self.task.scan_letter_board(force=True)['on_board'])

    def test_column_index_boundaries(self):
        self.assertEqual(len(LETTER_BOARD_COLUMN_X), len(COLUMN_NAMES),
                         '栏目数量要和解析用的名字表对齐')
        self.assertEqual([left for left, _ in LETTER_BOARD_COLUMN_X], [60, 400, 744],
                         '栏目边界是列表 OCR 归属的唯一依据')
        self.assertEqual([AutoLetterOpenTask.column_index(x)
                          for x in (60, 399, 400, 743, 744, 1109, 1110)],
                         [0, 0, 1, 1, 2, 2, None])

    # ---- 密函开完 ----

    def test_letter_exhausted(self):
        """卡牌那一行读得到持有数 -> 没开完；一个数字都读不到 -> 只剩 ⊘ 不使用。"""
        self.stub_board([box(937, 424, '85'), box(1031, 424, '85')])
        self.assertFalse(self.task.letter_exhausted())
        self.stub_board([])
        self.assertTrue(self.task.letter_exhausted())

    # ---- 刷新计时：读到的时长 + 1 分钟容错 ----

    def test_refresh_deadline_adds_one_minute(self):
        before = time.time()
        self.assertAlmostEqual(AutoLetterOpenTask.refresh_deadline(120) - before, 180, delta=1.0)
        self.assertAlmostEqual(AutoLetterOpenTask.refresh_deadline(0) - before, 60, delta=1.0)

    # ---- 覆盖了 AutoExpulsion.do_run 之后，必须自己补齐它初始化的状态 ----

    def test_in_mission_path_has_inherited_state(self):
        """踩过的坑：handle_in_mission 里有 self.count += 1，而 count 是
        AutoExpulsion.do_run 初始化的 —— 这里覆盖了 do_run 却没补，一进本就直接
        AttributeError 弹「'AutoLetterOpenTask' object has no attribute 'count'」。
        """
        self.assertTrue(hasattr(self.task, 'count'),
                        'AutoLetterOpenTask 必须在构造时就初始化 count')
        self.task.runtime_state = {'start_time': 0}
        self.task.in_team = lambda *a, **k: True
        self.task.move_on_begin = lambda: True
        self.task.random_walk_tick = lambda: None
        self.task.skill_tick = lambda: None
        self.task.config = {'超时时间': 999}
        self.task.count = 0
        self.task.handle_in_mission()
        self.assertEqual(self.task.count, 1, '进本一次应该 count 1，且不抛异常')

    # ---- 坐标框 ----

    def test_letter_board_boxes_exist(self):
        for name in ('LETTER_BOARD', 'LETTER_REFRESH', 'LETTER_START_REFRESH', 'LETTER_CARD_ROW'):
            spec = getattr(SCREEN_BOX, name)
            self.assertEqual(len(spec), 7, '%s 的格式要和 SCREEN_BOX 其它框一致' % name)
            _, _, x0, y0, x1, y1, _ = spec
            self.assertLess(x0, x1)
            self.assertLess(y0, y1)


if __name__ == '__main__':
    unittest.main()

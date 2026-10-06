# 自由填充的行动序列（外部步骤表）：加载 / 报错 / 逐条执行的顺序
#
# 不碰真机：步骤执行器只依赖 task 上少数几个动作方法，这里换成记录桩，于是"填什么就
# 按什么顺序做什么"能被钉死；同时钉住"写错了要说清是第几步" —— 用户自己填 JSON 时，
# 报错信息就是他唯一的调试线索。
import json
import os
import shutil
import unittest

from ok.test.TaskTestCase import TaskTestCase

from src.config import config
from src.tasks.fullauto.DungeonActionScript import (
    ActionScriptError,
    STEP_HANDLERS,
    ensure_template,
    list_scripts,
    load_script,
    run_steps,
)
from src.tasks.fullauto.AutoActionLogicScriptTask import AutoActionLogicScriptTask


class TestActionLogicScript(TaskTestCase):
    task_class = AutoActionLogicScriptTask
    config = config

    # 临时文件放测试目录下（%TEMP% 在受限环境里建不了子目录），用完就删
    TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_action_script')

    _PATCHED = ('send_key', 'send_key_down', 'send_key_up', 'sleep', 'move_mouse_relative',
                'click_relative', 'next_frame', 'is_in_combat', 'log_info')

    def setUp(self):
        self._saved = {name: getattr(self.task, name) for name in self._PATCHED}
        shutil.rmtree(self.TMP, ignore_errors=True)
        os.makedirs(self.TMP, exist_ok=True)
        self.calls = []
        self.task.log_info = lambda msg, **kw: self.calls.append(('log', msg))
        self.task.send_key = lambda key, **kw: self.calls.append(('key', key, kw.get('down_time')))
        self.task.send_key_down = lambda key: self.calls.append(('down', key))
        self.task.send_key_up = lambda key: self.calls.append(('up', key))
        self.task.sleep = lambda seconds: self.calls.append(('sleep', seconds))
        self.task.move_mouse_relative = lambda dx, dy, **kw: self.calls.append(('mouse', dx, dy))
        self.task.click_relative = lambda x, y, **kw: self.calls.append(('click', x, y))
        self.task.next_frame = lambda: self.calls.append(('frame',))

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(self.task, name, value)
        shutil.rmtree(self.TMP, ignore_errors=True)
        super().tearDown()

    def write_script(self, name, payload):
        path = os.path.join(self.TMP, name)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False)
        return path

    # ---- 文件加载 ----

    def test_ensure_template_writes_a_fillable_sequence(self):
        created = ensure_template(self.TMP)
        self.assertIsNotNone(created, '目录为空时应该生成模板')
        self.assertTrue(created.exists())
        self.assertIsNone(ensure_template(self.TMP), '已经有模板就不再覆盖用户的文件')
        data = load_script(created)
        self.assertTrue(data['steps'], '模板里要有一段能看的示例序列')
        self.assertIn(created.name, list_scripts(self.TMP))

    def test_load_accepts_object_and_bare_array(self):
        steps = [{'type': 'key', 'key': 'space', 'seconds': 0.05}]
        cases = [
            ({'steps': steps, 'note': '进本先按空格'}, '进本先按空格'),
            (steps, None),
            ({'_说明': '下划线开头的字段只看不认', 'steps': steps}, None),
        ]
        for payload, note in cases:
            data = load_script(self.write_script('x.json', payload))
            self.assertEqual(data['steps'], steps)
            self.assertEqual(data['note'], note)

    def test_load_reports_bad_files(self):
        cases = {
            'no_steps.json': {'_说明': '只有说明'},          # 没写 steps -> 空序列，不算错
            'bad_steps.json': {'steps': 'not-a-list'},
            'bad_top.json': [1, 2, 3],                       # 数组里塞的不是步骤对象
        }
        data = load_script(self.write_script('no_steps.json', cases['no_steps.json']))
        self.assertEqual(data['steps'], [], '没填 steps 就是空序列，由任务那边提示')
        with self.assertRaises(ActionScriptError):
            load_script(self.write_script('bad_steps.json', cases['bad_steps.json']))
        with self.assertRaises(ActionScriptError) as ctx:
            run_steps(self.task, load_script(self.write_script('bad_top.json', cases['bad_top.json']))['steps'])
        self.assertIn('第 1 步', str(ctx.exception))
        with self.assertRaises(ActionScriptError, msg='文件不存在也要报错'):
            load_script(os.path.join(self.TMP, 'nope.json'))

    # ---- 步骤执行 ----

    def test_run_steps_in_order(self):
        steps = [
            {'type': 'log', 'text': '起步'},
            {'type': 'key', 'key': 'w', 'seconds': 1.5},
            {'type': 'mouse_move', 'dx': 120, 'dy': -30},
            {'type': 'wait', 'seconds': 0.5},
            {'type': 'click', 'x': 0.25, 'y': 0.75},
            {'type': 'key_down', 'key': 'a'},
            {'type': 'key_up', 'key': 'a'},
        ]
        self.assertEqual(run_steps(self.task, steps), len(steps))
        self.assertEqual(self.calls, [
            ('log', '[行动逻辑]起步'),
            ('key', 'w', 1.5),
            ('mouse', 120, -30),
            ('sleep', 0.5),
            ('click', 0.25, 0.75),
            ('down', 'a'),
            ('up', 'a'),
        ], '执行顺序要和 JSON 里写的一致')

    def test_space_double_tap_sequence(self):
        """用户最常用的那种写法：按一次空格、隔 0.3 秒、再按一次。"""
        steps = [
            {'type': 'key', 'key': 'space', 'seconds': 0.05},
            {'type': 'wait', 'seconds': 0.3},
            {'type': 'key', 'key': 'space', 'seconds': 0.05},
        ]
        run_steps(self.task, steps)
        self.assertEqual(self.calls, [
            ('key', 'space', 0.05),
            ('sleep', 0.3),
            ('key', 'space', 0.05),
        ])

    def test_call_step_invokes_task_method(self):
        called = []
        self.task.my_extra_logic = lambda: called.append('跑了')
        run_steps(self.task, [{'type': 'call', 'method': 'my_extra_logic'}])
        self.assertEqual(called, ['跑了'], 'call 是复杂逻辑的逃生口，要真的调到任务上的方法')

    def test_repeat_nests(self):
        steps = [{'type': 'repeat', 'times': 2, 'steps': [
            {'type': 'key', 'key': 'w', 'seconds': 0.1},
            {'type': 'repeat', 'times': 3, 'steps': [{'type': 'key', 'key': 'd', 'seconds': 0.1}]},
        ]}]
        run_steps(self.task, steps)
        keys = [c[:2] for c in self.calls if c[0] == 'key']
        self.assertEqual(keys, [('key', 'w'), ('key', 'd'), ('key', 'd'), ('key', 'd')] * 2,
                         '外层 2 遍、内层 3 遍')

    def test_errors_point_at_the_step(self):
        with self.assertRaises(ActionScriptError) as ctx:
            run_steps(self.task, [{'type': 'wait', 'seconds': 0}, {'type': '飞起来'}])
        self.assertIn('第 2 步', str(ctx.exception))
        self.assertIn('飞起来', str(ctx.exception))
        with self.assertRaises(ActionScriptError) as ctx:
            run_steps(self.task, [{'type': 'key'}])
        self.assertIn('第 1 步', str(ctx.exception))
        with self.assertRaises(ActionScriptError) as ctx:
            run_steps(self.task, [{'type': 'call', 'method': '根本没有这个方法'}])
        self.assertIn('根本没有这个方法', str(ctx.exception))

    def test_until_combat_holds_key_until_combat(self):
        """until_combat 要按住键、轮询判据、命中后多走 extra 秒，最后一定松手。"""
        probes = {'n': 0}

        def in_combat():
            probes['n'] += 1
            return probes['n'] >= 3

        self.task.is_in_combat = in_combat
        run_steps(self.task, [{'type': 'until_combat', 'key': 'w', 'timeout': 30, 'extra': 0.05}])
        self.assertEqual(self.calls[0], ('down', 'w'))
        self.assertEqual(self.calls[-1], ('up', 'w'), '不管成功失败都要松手')
        self.assertEqual(probes['n'], 3, '前两次没进战斗就继续走，第三次命中')
        self.assertGreater(len([c for c in self.calls if c[0] == 'frame']), probes['n'],
                           '命中后还要按 extra 多走一段（多取几帧）')

    def test_until_combat_times_out(self):
        self.task.is_in_combat = lambda: False
        with self.assertRaises(ActionScriptError) as ctx:
            run_steps(self.task, [{'type': 'until_combat', 'key': 'w', 'timeout': 0.01}])
        self.assertIn('还没进战斗', str(ctx.exception))
        self.assertEqual(self.calls[-1], ('up', 'w'), '超时也要松手')

    def test_every_step_type_has_a_handler(self):
        for kind in ('log', 'key', 'key_down', 'key_up', 'wait', 'mouse_move', 'click',
                     'until_combat', 'repeat', 'call'):
            self.assertIn(kind, STEP_HANDLERS, f'文档里写了的 {kind} 要有实现')


if __name__ == '__main__':
    unittest.main()

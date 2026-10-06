# 快捷启动键：按键 -> 启动 / 停止 / 忽略 的判断
#
# 这一层不碰 Qt / ok / 真机：TaskHotkey 只做判断和回调，这里用几个假对象把它钉住。
# 真正接线的地方（Globals.on_press）只负责把 og.executor / og.app.start_controller 传进来。
import unittest
from types import SimpleNamespace

from pynput import keyboard

from src.tasks import TaskHotkey
from src.tasks.TaskHotkey import (
    CONFIG_KEY,
    DEFAULT_KEY,
    DISABLED,
    action_for,
    handle,
    hotkey_of,
    key_name,
    reset_debounce,
)


class FakeExecutor:
    def __init__(self, current=None):
        self.current_task = current
        self.stopped = []

    def stop_current_task(self):
        self.stopped.append(self.current_task)


class FakeController:
    def __init__(self):
        self.started = []

    def start(self, task, **kwargs):
        self.started.append(task)


class BadConfigTask(SimpleNamespace):
    @property
    def config(self):
        raise RuntimeError("配置读不了")


def make_task(name="行动逻辑脚本测试", key=DEFAULT_KEY):
    return SimpleNamespace(name=name, config={CONFIG_KEY: key})


class TestTaskHotkey(unittest.TestCase):

    def setUp(self):
        reset_debounce()

    # ---- 按键名 ----

    def test_key_name(self):
        self.assertEqual(key_name(keyboard.Key.f8), 'f8')
        self.assertEqual(key_name(keyboard.KeyCode.from_char('A')), 'a')
        self.assertIsNone(key_name(None))
        self.assertIsNone(key_name(SimpleNamespace()), '认不出来的对象要返回 None，别抛')

    # ---- 配置里的键 ----

    def test_hotkey_of(self):
        self.assertEqual(hotkey_of(make_task(key="F8")), 'f8', '统一小写比较')
        self.assertEqual(hotkey_of(SimpleNamespace(config={})), DEFAULT_KEY.lower(), '没配就退回默认键')
        self.assertIsNone(hotkey_of(make_task(key=DISABLED)), '选「关闭」就不响应')
        self.assertIsNone(hotkey_of(make_task(key=None)), '显式空值也当关闭（老配置缺键才会走默认值）')
        self.assertIsNone(hotkey_of(make_task(key='')), '空值也不响应')
        self.assertIsNone(hotkey_of(None), '找不到任务就不响应')
        self.assertEqual(hotkey_of(BadConfigTask()), DEFAULT_KEY.lower(), '配置读不了就退回默认键')

    # ---- 该干什么 ----

    def test_action_for(self):
        task = make_task()
        self.assertEqual(action_for(FakeExecutor(None), task), 'start', '空闲就启动')
        self.assertEqual(action_for(FakeExecutor(task), task), 'stop', '正在跑的就是它就停止')
        self.assertEqual(action_for(FakeExecutor(make_task('别的任务')), task), 'ignore',
                         '别的任务在跑就不插手')

    # ---- 一次按键 ----

    def test_handle_ignores_other_keys_and_disabled(self):
        task = make_task()
        executor, controller = FakeExecutor(None), FakeController()
        self.assertEqual(handle(executor, controller, task, keyboard.Key.f7, now=10), '')
        self.assertEqual(handle(executor, controller, make_task(key=DISABLED),
                                keyboard.Key.f8, now=10), '')
        self.assertEqual(controller.started, [], '不是这个键就什么都不做')

    def test_handle_starts_when_idle(self):
        task = make_task()
        executor, controller = FakeExecutor(None), FakeController()
        told = []
        self.assertEqual(handle(executor, controller, task, keyboard.Key.f8,
                                tell=told.append, now=10), 'start')
        self.assertEqual(controller.started, [task], '空闲时走 start_controller.start')
        self.assertEqual(len(told), 1)
        self.assertIn('启动', told[0])

    def test_handle_stops_when_it_is_running(self):
        task = make_task()
        executor, controller = FakeExecutor(task), FakeController()
        told = []
        self.assertEqual(handle(executor, controller, task, keyboard.Key.f8,
                                tell=told.append, now=10), 'stop')
        self.assertEqual(executor.stopped, [task])
        self.assertEqual(controller.started, [])
        self.assertIn('停止', told[0])

    def test_handle_ignores_while_other_task_runs(self):
        task = make_task()
        other = make_task('别的任务')
        executor, controller = FakeExecutor(other), FakeController()
        told = []
        self.assertEqual(handle(executor, controller, task, keyboard.Key.f8,
                                tell=told.append, now=10), 'ignore')
        self.assertEqual(executor.stopped, [], '不去停别人的任务')
        self.assertEqual(controller.started, [], '也不排队启动')
        self.assertIn('忽略', told[0])

    def test_handle_debounces_held_key(self):
        """按住 F8 会连发，只认第一下：否则会启动->停止->启动地抖。"""
        task = make_task()
        executor, controller = FakeExecutor(None), FakeController()
        self.assertEqual(handle(executor, controller, task, keyboard.Key.f8, now=10.0), 'start')
        self.assertEqual(handle(executor, controller, task, keyboard.Key.f8, now=10.2), '')
        self.assertEqual(len(controller.started), 1)
        # 去抖窗口之外（这里任务当作已经结束）就又能触发
        executor.current_task = None
        self.assertEqual(handle(executor, controller, task, keyboard.Key.f8,
                                now=10.0 + TaskHotkey.DEBOUNCE_SECONDS + 0.01), 'start')
        self.assertEqual(len(controller.started), 2)


if __name__ == '__main__':
    unittest.main()

from ok import TriggerTask, Logger
from src.tasks.BaseCombatTask import BaseCombatTask, NotInCombatException, CharDeadException
from src.tasks.BaseListenerTask import BaseListenerTask
from src.scene.DNAScene import DNAScene

from pynput import mouse

logger = Logger.get_logger(__name__)


class AutoCombatTask(BaseListenerTask, BaseCombatTask, TriggerTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "自动战斗"
        self.description = "需主动激活"
        self.scene: DNAScene | None = None
        self.setup_listener_config()
        self.default_config.update({
            "技能": "普攻",
            "释放间隔": 0.1,
        })
        self.config_type["技能"] = {"type": "drop_down", "options": ["普攻", "按住普攻", "战技", "终结技"]}

    def disable(self):
        """禁用任务时，断开信号连接。"""
        self.try_disconnect_listener()
        return super().disable()
    
    def enable(self):
        """启用任务时，信号连接。"""
        self.try_connect_listener()
        return super().enable()

    def run(self):
        ret = False
        if not self.scene.in_team(self.in_team_and_world):
            return ret
        
        _mouse_down = False
        while self.in_combat():
            if not ret:
                n = self.config.get("释放间隔", 0.1)
                interval = 0.1 if n < 0.1 else n
                char = self.get_current_char()
                ret = True
            try:
                skill = self.config.get("技能", "普攻")
                if skill == "战技":
                    char.send_combat_key()
                elif skill == "终结技":
                    char.send_ultimate_key()
                elif skill == "按住普攻" and not _mouse_down:
                    _mouse_down = True
                    self.hotkey_down(self.get_normal_attack_key())
                elif skill == "普攻":
                    self.press_hotkey(self.get_normal_attack_key())
                self.sleep(interval)
            except CharDeadException:
                self.log_error("Characters dead", notify=True)
                break
            except NotInCombatException as e:
                logger.info(f"auto_combat_task_out_of_combat {e}")
                break

        if ret:
            if _mouse_down:
                self.hotkey_up(self.get_normal_attack_key())
            self.combat_end()
        return ret

    def on_global_click(self, x, y, button, pressed):
        if self._executor.paused:
            return
        if self.config.get('激活键', 'x2') == '使用键盘':
            return
        if self.config.get("激活键", "x2") == "x1":
            btn = mouse.Button.x1
        else:
            btn = mouse.Button.x2
        if pressed and button == btn:
            self.manual_in_combat = not self.manual_in_combat

    def on_global_press(self, key):
        if self._executor.paused or self.config.get('激活键', 'x2') != '使用键盘':
            return
        lower = self.config.get('键盘', 'ctrl_r').lower()
        hot_key = self.normalize_hotkey(lower)
        if self.key_equal(key, hot_key):
            self.manual_in_combat = not self.manual_in_combat

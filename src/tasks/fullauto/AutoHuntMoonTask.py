# -*- coding: utf-8 -*-
"""全自动「狩月人之阶」（巅峰赛活动，**仅限巅峰赛**）。

一轮的流程（按用户给的实拍图与口述）：
  活动界面点「开始挑战」-> 进本加载（委托那套 in_team 判据）-> 走位（固定按键时序）
  -> 走完直接按「主控角色」的手法放技能 -> 结算页（「挑战成功」/「挑战结束」两屏都有「重新开始」）
  -> 点「重新开始」继续下一轮。

起手有讲究：本模块**只在「狩月人之阶」活动界面才能开始**。进任务先给
ACTIVITY_INTERFACE_TIMEOUT 秒缓冲去找「开始挑战」左边那颗城堡/门形图标（图形、不带文字，
六种语言通用），找不到就带系统提示停止（“请进入狩月人之阶的活动界面”），不会乱点。

主控角色只决定“放什么技能”：走位是共用的一段固定时序，和选哪个角色无关，所以角色之间
只差一张技能手法表（和「自动迷津」一样的写法）。

超时：「超时时间」默认 90 秒，一轮打太久就按 ESC 退本、回到结算页点「重新开始」重开；
局数只计数、不设上限。
"""

from qfluentwidgets import FluentIcon
import re
import time

from ok import Logger, TaskDisabledException
from src.dna_ui.Defs import COORD, Ui
from src.tasks.DNAOneTimeTask import DNAOneTimeTask
from src.tasks.CommissionsTask import CommissionsTask
from src.tasks.BaseCombatTask import BaseCombatTask

logger = Logger.get_logger(__name__)

# 「主控角色」-> 该角色的技能手法：
#   steps: ((动作, 放完之后等几秒), ...)，动作取值沿用「全局技能设定」那套
#          （短按战技 / 长按战技 / 终结技 / 魔灵支援 / 普攻 / 重击）
#   loop:  True  = 一直循环放；循环型每进一次主循环只走一步，循环期间还能继续判界面
#          False = 进本整串放一遍就停
# 目前只加了用户点名的「松露」：只放终结技。以后新增角色往这张表里加就行。
CHARACTER_ROTATIONS = {
    # 松露：进本只放一次终结技（不循环）
    "松露": {"loop": False, "steps": (("终结技", 1.0),)},
    # 法露茜：2eeee1 + eeee1 = 终结技 -> 普攻 x4 -> 战技 -> 普攻 x4 -> 战技，进本放一遍
    # 间隔：终结技到第一次普攻 1 秒，其余每个操作之间 0.5 秒
    "法露茜": {"loop": False, "steps": (("终结技", 1.0), ("普攻", 0.5), ("普攻", 0.5),
                                        ("普攻", 0.5), ("普攻", 0.5), ("短按战技", 0.5),
                                        ("普攻", 0.5), ("普攻", 0.5), ("普攻", 0.5),
                                        ("普攻", 0.5), ("短按战技", 0.5))},
}

# 默认主控角色 = 表里的第一个
DEFAULT_CHARACTER = next(iter(CHARACTER_ROTATIONS))
# 「自定义」：技能与等待全由用户自己写（见「自定义序列」）
CUSTOM_CHARACTER = "自定义"
CUSTOM_SEQUENCE_KEY = "自定义序列"
DEFAULT_CUSTOM_SEQUENCE = "终结技:1"
# 自定义序列里允许的动作名（战技 = 短按），和 release_character_action 的分支一一对应
CUSTOM_ACTIONS = {
    "战技": "短按战技",
    "短按战技": "短按战技",
    "长按战技": "长按战技",
    "终结技": "终结技",
    "魔灵支援": "魔灵支援",
    "普攻": "普攻",
    "重击": "重击",
}
# 「长按战技」按住的秒数、「重击」按住左键的秒数（和「全局技能设定」的默认值一致）
COMBAT_LONG_PRESS = 1.0
HEAVY_ATTACK_HOLD = 1.5

# 起手判据的缓冲（秒）：进任务后最多找这么久，还没在「狩月人之阶」活动界面就提示停止
ACTIVITY_INTERFACE_TIMEOUT = 2.0
# 进本后先稳这么久再走位（照「自动沉浸式戏剧」的 FIRST_LAYER_SETTLE）：判据刚成立时
# 角色还在落地/过场收尾，这时候按走位键会被吃掉前面一段（表现就是走位变短、走不到位置）
ENTER_SETTLE_SECONDS = 1.0
# 走位：进本后按顺序按这些键 (key, 按住秒数)。走完就直接进技能序列，不再"前进到开战"
WALK_SEQUENCE = (("w", 4.5), ("d", 2.2), ("w", 3.6))
# 「超时时间」配置：一轮（点「开始挑战」/「重新开始」到进结算页）最多打多少秒；超了就按
# ESC 退本（和「自动迷津」等任务超时的做法一样），回到结算页再点「重新开始」重开
TIMEOUT_KEY = "超时时间"
TIMEOUT_DEFAULT = 90
# 超时后按 ESC 的重试间隔（秒）：云游戏丢键时那一脚可能没生效，隔几秒再补一脚
TIMEOUT_ESC_INTERVAL = 5.0
# 结算页判据：左下「重新开始」按钮左侧那颗金色环形箭头图标（图形判据，不依赖 OCR）


class AutoHuntMoonTask(DNAOneTimeTask, CommissionsTask, BaseCombatTask):
    """全自动「狩月人之阶」：活动界面点开始 -> 走位开战 -> 按主控角色放技能 -> 结算重开。

    只在「狩月人之阶」活动界面才启动（起手判据见 ensure_activity_interface）；
    一局打完（结算页出现「重新开始」）点它继续，局数只计数、不设上限。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.icon = FluentIcon.FLAG
        self.name = "自动狩月人之阶"
        self.description = "不凹分，仅刷本"
        self.group_name = "全自动（特殊）"
        self.group_icon = FluentIcon.GAME

        self.default_config.update({
            TIMEOUT_KEY: TIMEOUT_DEFAULT,
            "主控角色": DEFAULT_CHARACTER,
            CUSTOM_SEQUENCE_KEY: DEFAULT_CUSTOM_SEQUENCE,
        })
        self.config_type["主控角色"] = {
            "type": "drop_down",
            "options": list(CHARACTER_ROTATIONS) + [CUSTOM_CHARACTER],
        }
        self.config_description.update({
            "主控角色": "选哪个主控角色，就按它的手法放技能（走位和角色无关，所有角色一样）",
            CUSTOM_SEQUENCE_KEY: "选「自定义」时用：每一步写成「技能:等待秒数」，逗号分隔。"
                                 "例：终结技:1, 战技:1",
            TIMEOUT_KEY: "超时后将重启任务",
        })

        # 云游戏实拍帧糊、模板分低，给足重试轮次
        self.action_timeout = 20
        self.character_steps = None
        self.character_loops = False
        self.fallback_skill_tick = None
        self.step_index = 0
        self.sequence_done = False
        self.walked = False
        self.rounds = 0
        self.result_handled = False
        self.round_start_time = 0.0
        self.next_timeout_esc = 0.0

    def run(self):
        DNAOneTimeTask.run(self)
        self.move_mouse_to_safe_position(save_current_pos=False)
        self.set_check_monthly_card()
        try:
            return self.do_run()
        except TaskDisabledException:
            pass
        except Exception as e:
            logger.error("AutoHuntMoonTask error", e)
            raise

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------

    def do_run(self):
        self.load_char()
        if not self.ensure_activity_interface():
            self.log_info_notify("请进入狩月人之阶的活动界面")
            self.soundBeep()
            raise TaskDisabledException
        self.setup_character()
        self.rounds = 0
        self.result_handled = False
        # 停一次再开就是全新一轮：超时计时从 0 起（任务实例是复用的，别留上一轮的账）
        self.round_start_time = 0.0
        self.next_timeout_esc = 0.0
        self.reset_mission_state()
        self.info_set("局数", "0")
        while True:
            self.next_frame()
            if self.round_timed_out():
                # 一轮打太久（卡住/云游戏丢键）：按 ESC 退本，回结算页再点「重新开始」重开
                self.handle_timeout()
                continue
            if self.find_result_interface():
                # 结算页：这一局打完了（只处理一次，免得同一屏被数成好几局）
                if not self.result_handled:
                    self.handle_result()
            elif self.find_activity_interface():
                self.result_handled = False
                self.handle_start_challenge()
            elif self.in_team():
                self.result_handled = False
                self.handle_in_mission()
            else:
                # 加载中 / 过场动画：等下一轮
                self.sleep(0.3)

    def handle_start_challenge(self):
        """活动界面：点「开始挑战」开一局。"""
        self.log_info("在「狩月人之阶」活动界面，点「开始挑战」")
        self.reset_mission_state()
        self.round_start_time = time.time()
        self.click_ui_coord(COORD.HUNT_START_CHALLENGE, name="hunt_moon_start",
                            after_sleep=1.0)

    def handle_result(self):
        """结算页：点「重新开始」继续下一轮，局数 +1。"""
        self.result_handled = True
        self.rounds += 1
        self.info_set("局数", str(self.rounds))
        self.log_info("第 %d 局结束（出现「重新开始」），点它继续" % self.rounds)
        self.reset_mission_state()
        self.round_start_time = time.time()
        self.click_ui_coord(COORD.HUNT_RESULT_RESTART, name="hunt_moon_restart",
                            after_sleep=1.0)

    def handle_in_mission(self):
        """局内：先走位（一局一次），再按「主控角色」的手法放技能。"""
        if not self.walked:
            self.walked = True
            # 进本判据刚成立时人还在落地/过场收尾，先稳住再走位（照自动沉浸式戏剧）
            self.log_info("进本稳定 %.1f 秒后开始走位" % ENTER_SETTLE_SECONDS)
            self.sleep(ENTER_SETTLE_SECONDS)
            self.walk_current_mission()
        if self.character_steps is None:
            # 配置里的角色名没有对应手法：退回全局技能计时器，保证任务还能跑起来
            if self.fallback_skill_tick is not None:
                self.fallback_skill_tick()
            return
        self.run_character_skill()

    def reset_mission_state(self):
        """一局的局内状态：走位跑过没、技能序列放过没。"""
        self.walked = False
        self.sequence_done = False
        self.step_index = 0

    # ------------------------------------------------------------------
    # 起手判据 / 局内判据
    # ------------------------------------------------------------------

    def find_activity_interface(self):
        """是不是在「狩月人之阶」活动界面（认「开始挑战」左边那颗城堡/门形图标）。"""
        return self.find_ui(Ui.HUNT_MOON_START, threshold=0.8) is not None

    def ensure_activity_interface(self):
        """起手：给 ACTIVITY_INTERFACE_TIMEOUT 秒缓冲找活动界面，找不到返回 False。"""
        deadline = time.time() + ACTIVITY_INTERFACE_TIMEOUT
        while True:
            self.next_frame()
            if self.find_activity_interface():
                self.log_info("已在「狩月人之阶」活动界面，开始执行")
                return True
            if time.time() >= deadline:
                return False
            self.sleep(0.2)

    def find_result_interface(self):
        """结算页判据：左下「重新开始」按钮左侧那颗金色环形箭头图标。

        「挑战成功」和「挑战结束」两屏用的是同一个按钮，所以一个判据管两屏。
        """
        return self.find_ui(Ui.HUNT_RESTART, threshold=0.8) is not None

    # ------------------------------------------------------------------
    # 超时兜底
    # ------------------------------------------------------------------

    def round_timeout(self):
        """「超时时间」配置：一轮最多打多少秒。"""
        try:
            return max(1, int(self.config.get(TIMEOUT_KEY, TIMEOUT_DEFAULT)))
        except (TypeError, ValueError):
            return TIMEOUT_DEFAULT

    def round_timed_out(self):
        """这一轮是不是打太久了（「超时时间」秒内还没进结算页）。"""
        if not self.round_start_time:
            return False
        return time.time() - self.round_start_time >= self.round_timeout()

    def handle_timeout(self):
        """超时兜底：按 ESC 退本（和「自动迷津」等任务一样），再回结算页点「重新开始」。

        云游戏丢键时那一脚 ESC 可能没生效，所以每 TIMEOUT_ESC_INTERVAL 秒重试一次，
        直到这一轮真的结束（结算页出现 -> handle_result 重新计时）。
        """
        now = time.time()
        if now < self.next_timeout_esc:
            return
        self.next_timeout_esc = now + TIMEOUT_ESC_INTERVAL
        self.log_info("本轮已打 %d 秒（超时时间 %d 秒），按 ESC 退本重开"
                      % (now - self.round_start_time, self.round_timeout()))
        self.soundBeep()
        self.send_key("esc", after_sleep=0.5)

    # ------------------------------------------------------------------
    # 走位（所有主控角色共用同一段）
    # ------------------------------------------------------------------

    def walk_current_mission(self):
        """进本走位：按 WALK_SEQUENCE 的固定时序走一遍就结束（不再「前进到开战」）。

        这段和主控角色无关（用户要求），所以不放进角色表里；走完直接进技能序列。
        """
        self.log_info("开始走位")
        for key, seconds in WALK_SEQUENCE:
            self.send_key(key, down_time=seconds)
        self.log_info("走位结束")

    # ------------------------------------------------------------------
    # 主控角色手法（和「自动迷津」同一套写法）
    # ------------------------------------------------------------------

    def current_character(self):
        return self.config.get("主控角色", DEFAULT_CHARACTER)

    def setup_character(self):
        """按「主控角色」取技能序列；取不到就退回全局技能计时器。"""
        name = self.current_character()
        if name == CUSTOM_CHARACTER:
            steps = self.parse_custom_steps()
            if steps:
                self.log_info("自定义技能序列: %s"
                              % " -> ".join("%s后等%.1f秒" % step for step in steps))
                self.character_steps = steps
                self.character_loops = False
                self.fallback_skill_tick = None
                return
            self.log_info("「%s」没解析出任何步骤，改用「%s」"
                          % (CUSTOM_SEQUENCE_KEY, DEFAULT_CHARACTER))
            name = DEFAULT_CHARACTER
        rotation = CHARACTER_ROTATIONS.get(name)
        if rotation is None:
            self.log_info("没有「%s」的技能手法，退回全局技能计时器" % name)
            self.character_steps = None
            self.character_loops = False
            self.fallback_skill_tick = self.create_skill_ticker()
        else:
            self.character_steps = rotation["steps"]
            self.character_loops = bool(rotation.get("loop", False))
            self.fallback_skill_tick = None

    def parse_custom_steps(self):
        """把「自定义序列」解析成 ((动作, 等待秒数), ...)；解析不出任何一步就返回空。

        格式：每一步用中英文逗号、分号、顿号或换行分隔，写成「技能」或「技能:等待秒数」。
        技能名写「战技」按短按处理，「长按战技」按住 COMBAT_LONG_PRESS 秒。
        """
        raw = str(self.config.get(CUSTOM_SEQUENCE_KEY, DEFAULT_CUSTOM_SEQUENCE) or "")
        steps = []
        for part in re.split(r"[,;，；、\n\r]+", raw):
            part = part.strip()
            if not part:
                continue
            action, _, wait_text = part.partition(":")
            action = CUSTOM_ACTIONS.get(action.strip())
            if action is None:
                self.log_info("自定义序列第 %d 步技能名不认识，已跳过: %s"
                              % (len(steps) + 1, part))
                continue
            try:
                wait = float(wait_text) if wait_text.strip() else 1.0
            except ValueError:
                wait = 1.0
            steps.append((action, max(0.0, wait)))
        return tuple(steps)

    def run_character_skill(self):
        """按「主控角色」的手法放技能。

        一次性角色：整串按顺序放一遍，每步放完等这一步配置的秒数。
        循环角色：每次主循环只走一步，靠主循环不断回来接下一步 —— 循环期间还能继续判界面。
        """
        if not self.character_loops:
            if self.sequence_done:
                return
            self.sequence_done = True
            self.log_info("释放「%s」技能序列: %s"
                          % (self.current_character(), self.describe_steps()))
            for action, wait in self.character_steps:
                self.release_character_action(action)
                self.sleep(wait)
            return

        if not self.sequence_done:
            self.sequence_done = True
            self.log_info("开始循环「%s」技能手法: %s"
                          % (self.current_character(), self.describe_steps()))
        action, wait = self.character_steps[self.step_index % len(self.character_steps)]
        self.step_index += 1
        self.log_info("循环技能第 %d 步: %s" % (self.step_index, action))
        self.release_character_action(action)
        self.sleep(wait)

    def describe_steps(self):
        return " -> ".join("%s后等%.0f秒" % (action, wait)
                           for action, wait in self.character_steps)

    def release_character_action(self, action):
        """放一次角色序列里的动作。

        直接按键，不走角色对象；键值一律取「游戏快捷键设置」里的战技 / 终结技 / 魔灵支援，
        所以游戏里改过键，只要 App 里这份设置跟着改就一致。
        """
        if action == "长按战技":
            self.log_info("放技能: 长按战技（键 %s，按住 %.1f 秒）"
                          % (self.get_combat_key(), COMBAT_LONG_PRESS))
            self.send_key(self.get_combat_key(), down_time=COMBAT_LONG_PRESS)
        elif action == "短按战技":
            self.log_info("放技能: 短按战技（键 %s）" % self.get_combat_key())
            self.send_key(self.get_combat_key())
        elif action == "终结技":
            self.log_info("放技能: 终结技（键 %s）" % self.get_ultimate_key())
            self.send_key(self.get_ultimate_key())
        elif action == "魔灵支援":
            self.log_info("放技能: 魔灵支援（键 %s）" % self.get_geniemon_key())
            self.send_key(self.get_geniemon_key())
        elif action == "普攻":
            self.log_info("放技能: 普攻（键 %s）" % self.get_normal_attack_key())
            self.press_hotkey(self.get_normal_attack_key())
        elif action == "重击":
            self.log_info("放技能: 重击（按住 %.1f 秒）" % HEAVY_ATTACK_HOLD)
            self.mouse_down()
            try:
                self.sleep(HEAVY_ATTACK_HOLD)
            finally:
                self.mouse_up()
        else:
            raise ValueError("未知技能动作: %s" % action)

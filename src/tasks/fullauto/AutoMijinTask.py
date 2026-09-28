from qfluentwidgets import FluentIcon
import re
import time

from ok import Logger, TaskDisabledException
from src.dna_ui.Defs import COORD
from src.tasks.DNAOneTimeTask import DNAOneTimeTask
from src.tasks.BaseCombatTask import BaseCombatTask
from src.tasks.CommissionsTask import CommissionsTask

logger = Logger.get_logger(__name__)


# 「使用角色」-> 该角色这一轮的技能手法：
#   steps: ((动作, 放完之后等几秒), ...)，动作见 release_character_action，
#          取值沿用「全局技能设定」那套：长按战技 / 短按战技 / 终结技 / 魔灵支援 / 普攻 / 重击
#   loop:  False = 进本后整串按顺序放一遍就停（每开始新一轮再放一次）
#          True  = 一直循环放；循环型每进一次主循环只走一步，这样循环期间还能继续判界面
CHARACTER_ROTATIONS = {
    # 止流：长按战技(2秒) -> 停1秒 -> 战技 -> 停1秒 -> 终结技，放一遍
    "止流": {
        "loop": False,
        "steps": (("长按战技", 1.0), ("短按战技", 1.0), ("终结技", 1.0)),
    },
    # 伊薇：战技*5（每个后面停1秒）-> 终结技，放一遍
    "伊薇": {
        "loop": False,
        "steps": (("短按战技", 1.0), ("短按战技", 1.0), ("短按战技", 1.0),
                  ("短按战技", 1.0), ("短按战技", 1.0), ("终结技", 1.0)),
    },
}

# 角色的默认选择：取第一个角色配置
DEFAULT_CHARACTER = next(iter(CHARACTER_ROTATIONS))

# 「使用角色」里额外的一项：技能与等待全由用户自己写（见下面的「自定义序列」）
CUSTOM_CHARACTER = "自定义"
# 自定义序列的配置项与默认值
CUSTOM_SEQUENCE_KEY = "自定义序列"
DEFAULT_CUSTOM_SEQUENCE = "长按战技:1, 战技:1, 终结技:1"
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

# 「长按战技」按住的秒数
COMBAT_LONG_PRESS = 2.0
# 一轮最多打多久（秒）：超了就主动退本、重开一轮（「超时时间」配置的默认值）
ROUND_TIMEOUT_SECONDS = 180
# 进本之后、放技能序列之前先稳这么久：进关动画/落地收尾期间按键会被吃掉
MISSION_SETTLE = 0.6
# 角色手法里用到「重击」时的长按秒数（和「全局技能设定」的默认值保持一致）
HEAVY_ATTACK_HOLD = 1.5

# ---- 迷津各页面的文案 ----
# 整屏 OCR 后按子串判断。这几句在各自页面上唯一、互不重叠，所以就是最省事的界面判据。
TEXT_ENTER = "坠入深渊"            # 模式首页 -> 进本（点它开始一轮）
TEXT_START = "开始探索"            # 难度选择页 -> 开始探索
TEXT_ESC_EXIT = "退出结算"         # 局内 ESC 菜单 -> 退出结算（优先按这几个字点）
# 同一套 ESC 菜单的其它按钮：万一「退出结算」这四个字没被 OCR 认出来，
# 靠这几个字也能判定"菜单开了"，再去点「退出结算」的位置（固定坐标兜底）。
TEXT_ESC_MENU = ("继续游戏", "角色技能", "暂离")
TEXT_CONFIRM_TITLE = "退出委托"    # 「退出委托」二次确认弹窗
TEXT_CONFIRM_HINT = "是否结束当前探索并结算"
TEXT_CLOSE_HINT = "点击空白处关闭"  # 道具弹窗 / 「确定」之后的过场 / 结算页：点空白处关闭
# 打完一关：「获得烛芯」的弹窗就是打完一关那一刻；弹窗点掉之后目标栏会变成
# 「前往下一层深渊」，两个都当判据（弹窗是短命的，只看它容易漏）。
# 进本画面上也会出现「前往下一层深渊」，所以真正的闸门是下面的
# WAVE_DONE_MIN_ROUND_SECONDS + 已经放过技能序列（见 wave_done_now）。
TEXT_WAVE_DONE = ("获得烛芯", "前往下一层深渊")
# 打完一关至少要等进本这么久才认（一波怎么都要打几十秒）：防止进本过渡画面上的
# 零碎文字触发误判。另外还必须已经进本放过技能序列（sequence_done）。
WAVE_DONE_MIN_ROUND_SECONDS = 3.0

# 局内判据：左下角的角色等级 LV.xx（难度选择页的 Lv.30~80 在右上列表、ESC 菜单里的
# LV.80 在中部，都不在左下角这个区域里）
LV_PATTERN = re.compile(r"^[Ll][Vv]\s*\.?\s*\d+$")
LV_MAX_X_RATIO = 0.2      # 框左边要落在屏宽左侧 20% 以内
LV_MIN_BOTTOM_RATIO = 0.9  # 框底要落在屏高下面 10% 以内

# 整屏 OCR 的节流间隔（秒）：OCR 本身比这慢时以 OCR 为准
OCR_INTERVAL = 0.5
# 认不出界面时，隔多久打一次"这一屏都有哪些字"的日志
UNKNOWN_LOG_INTERVAL = 3.0


class AutoMijinTask(DNAOneTimeTask, CommissionsTask, BaseCombatTask):
    """全自动「迷津」（肉鸽模式）。

    一轮的流程（按用户给的实拍图）：
      模式首页「坠入深渊」-> 难度选择页「开始探索」-> 进本稳定 0.6 秒后放一次角色技能序列
      -> 道具弹窗点空白处关闭 -> 打完一波按 ESC -> 菜单点「退出结算」
      -> 二次确认点「确定」-> 再点一次空白处关闭 -> 结算页点空白处关闭 -> 回到模式首页

    兜底：一轮打超过「超时时间」秒还没结束，就主动退本重开（走同一套退出流程）。
    「点击空白处关闭」不止一屏（结算、道具弹窗，以及点完「确定」之后还会再出一屏），
    所以这条判据是"见到就点"，连续几屏都会一屏一次地被接住。

    技能不走「全局技能计时器」，而是按「使用角色」选中的角色序列释放（一轮只放一次）。
    界面判据全部用整屏 OCR 的文案（见上面的 TEXT_*），点击坐标放在 src/dna_ui/Defs.py 的 COORD。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.icon = FluentIcon.FLAG
        self.name = "自动迷津"
        self.description = "全自动"
        self.group_name = "全自动"
        self.group_icon = FluentIcon.CAFE

        # 一轮打太久的兜底：超时就主动退本、重开一轮。
        # 放在最前面，界面上这一项就排在「挂机模式」之前（配置顺序 = default_config 的插入顺序）
        self.default_config.update({"超时时间": ROUND_TIMEOUT_SECONDS})
        self.config_description.update({"超时时间": "超时后将重启任务"})

        self.setup_mission_start_config()
        # 肉鸽里没有站在原地的空间，去掉「随机游走」这条用不上的配置
        self.default_config.pop("随机游走", None)
        self.config_description.pop("随机游走", None)

        # 角色手法：每个角色一套自己的技能序列，和「全局技能设定」无关
        self.default_config.update({
            "使用角色": DEFAULT_CHARACTER,
            CUSTOM_SEQUENCE_KEY: DEFAULT_CUSTOM_SEQUENCE,
        })
        self.config_type["使用角色"] = {
            "type": "drop_down",
            "options": list(CHARACTER_ROTATIONS) + [CUSTOM_CHARACTER],
        }
        self.config_description.update({
            "使用角色": "选择角色后按该角色的手法释放技能，不走全局技能计时器",
            CUSTOM_SEQUENCE_KEY: "每一步写成「技能:等待秒数」，逗号分隔。例：长按战技:1, 战技:1, 终结技:1",
        })

        # 云游戏实拍帧糊、模板分低，识别弹窗会有假阴性，给足重试轮次
        self.action_timeout = 20
        self.character_steps = None
        self.character_loops = False
        self.step_index = 0
        self.fallback_skill_tick = None
        self.screen_boxes = []
        self.screen_texts = []
        self.next_ocr = 0.0
        self.next_unknown_log = 0.0
        self.pending_esc = False
        self.round_start_time = 0.0
        self.next_timeout_esc = 0.0
        self.sequence_settled = False

    def run(self):
        DNAOneTimeTask.run(self)
        self.move_mouse_to_safe_position(save_current_pos=False)
        self.set_check_monthly_card()
        # 每次开跑重新按当前「使用角色」取序列，改了配置不用重启程序
        self.setup_character()
        try:
            return self.do_run()
        except TaskDisabledException:
            pass
        except Exception as e:
            logger.error("AutoMijinTask error", e)
            raise

    def do_run(self):
        """主循环：读一次屏，按当前页面推进；认不出就等下一轮再读。"""
        self.load_char()
        self.reset_round_state()
        while True:
            self.update_screen_text()
            if self.find_text(TEXT_ENTER):
                self.handle_enter()
            elif self.find_text(TEXT_START):
                self.handle_start()
            elif self.find_text(TEXT_ESC_EXIT) or self.find_any(TEXT_ESC_MENU):
                self.handle_esc_exit()
            elif self.find_text(TEXT_CONFIRM_TITLE) or self.find_text(TEXT_CONFIRM_HINT):
                self.handle_exit_confirm()
            elif self.wave_done_now():
                self.handle_wave_cleared()
            elif self.pending_esc:
                # 「获得烛芯」弹窗刚点掉，补上那一脚 ESC
                self.press_esc()
            elif self.find_text(TEXT_CLOSE_HINT):
                self.handle_close_popup()
            elif self.round_timed_out():
                self.handle_timeout()
            elif self.in_mijin_mission():
                self.handle_in_mission()
            else:
                self.log_unknown_screen()
                self.sleep(0.3)
            self.sleep(0.1)

    # ------------------------------------------------------------------
    # 各页面
    # ------------------------------------------------------------------

    def handle_enter(self):
        """模式首页：点「坠入深渊」，一轮从这里开始。"""
        self.reset_round_state()
        self.log_info("进本：点击「坠入深渊」")
        self.click_text(COORD.MIJIN_ENTER, "mijin_enter", TEXT_ENTER)

    def handle_start(self):
        """难度选择页：点「开始探索」。"""
        self.log_info("点击「开始探索」")
        self.click_text(COORD.MIJIN_START_EXPLORE, "mijin_start", TEXT_START)

    def handle_in_mission(self):
        """局内：先按「挂机模式」处理一次位置（默认原地不动），再按角色手法放技能。"""
        if not self.move_on_begin():
            return
        if self.character_steps is None:
            # 配置里的角色名没有对应手法：退回全局技能计时器，保证任务还能跑起来
            self.fallback_skill_tick()
            return
        self.settle_before_sequence()
        self.run_character_skill()

    def settle_before_sequence(self):
        """进本后先等 MISSION_SETTLE 秒再放序列（一轮只等一次）。"""
        if self.sequence_settled:
            return
        self.sequence_settled = True
        self.log_info("进本稳定 %.1f 秒后开始放技能" % MISSION_SETTLE)
        self.sleep(MISSION_SETTLE)

    def round_timeout(self):
        """「超时时间」配置：一轮最多打多少秒。"""
        try:
            return max(1, int(self.config.get("超时时间", ROUND_TIMEOUT_SECONDS)))
        except (TypeError, ValueError):
            return ROUND_TIMEOUT_SECONDS

    def round_timed_out(self):
        """这一轮是不是打太久了（只在已经进本放过技能、还没退出这一轮时为真）。"""
        if not self.sequence_done or not self.round_start_time:
            return False
        return time.time() - self.round_start_time >= self.round_timeout()

    def handle_timeout(self):
        """超时兜底：主动退本重开（走和"打完一关"一样的退出流程）。

        云游戏丢点击时那一脚 ESC 可能没生效，所以每 5 秒重试一次，直到这一轮真的结束。
        """
        now = time.time()
        if now < self.next_timeout_esc:
            return
        self.next_timeout_esc = now + 5.0
        self.log_info("本轮已打 %d 秒（超时时间 %d 秒），主动退本重开"
                      % (now - self.round_start_time, self.round_timeout()))
        self.press_esc()
    def wave_done_now(self):
        """打完一关：整屏出现「获得烛芯」，且这一轮确实已经进本开打了一段时间。"""
        if not self.sequence_done or not self.find_any(TEXT_WAVE_DONE):
            return False
        if self.round_start_time and time.time() - self.round_start_time < WAVE_DONE_MIN_ROUND_SECONDS:
            return False
        return True

    def handle_wave_cleared(self):
        """打完一关：弹窗还在就先点「点击空白处关闭」，关掉之后再按 ESC 打开局内菜单。"""
        if self.find_text(TEXT_CLOSE_HINT):
            # 弹窗（「获得烛芯」）挡住了后面的界面，先点掉；ESC 留到弹窗没了再按
            self.pending_esc = True
            self.handle_close_popup()
            return
        self.press_esc()

    def press_esc(self):
        self.pending_esc = False
        self.log_info("打完一关，按 ESC 打开菜单")
        self.send_key("esc", after_sleep=0.5)
        self.next_ocr = 0.0

    def handle_esc_exit(self):
        """局内菜单：点「退出结算」。"""
        self.log_info("点击「退出结算」")
        self.click_text(COORD.MIJIN_ESC_EXIT, "mijin_esc_exit", TEXT_ESC_EXIT)

    def handle_exit_confirm(self):
        """「退出委托」二次确认弹窗：点「确定」。"""
        self.log_info("点击「确定」")
        self.click_text(COORD.MIJIN_EXIT_CONFIRM, "mijin_exit_confirm", "确定")

    def handle_close_popup(self):
        """道具弹窗 / 结算页：点「点击空白处关闭」这几个字所在的位置。"""
        self.log_info("点「点击空白处关闭」")
        self.click_text(COORD.MIJIN_CLOSE_POPUP, "mijin_close", TEXT_CLOSE_HINT)

    def click_text(self, fallback_coord, name, *needles):
        """点 OCR 到的这串文字本身（框内随机点）；没认出来再退回固定坐标。"""
        box = self.find_box(*needles)
        if box is not None:
            self._click_detected(box, name=name, after_sleep=0.5)
        else:
            self.click_ui_coord(fallback_coord, name=name, after_sleep=0.5)
        self.next_ocr = 0.0

    # ------------------------------------------------------------------
    # 界面文案判据（整屏 OCR）
    # ------------------------------------------------------------------

    def update_screen_text(self):
        """按 OCR_INTERVAL 节流做一次整屏 OCR，结果缓存给本轮所有判断用。"""
        if time.time() < self.next_ocr:
            return
        boxes = self.ocr(frame=self.next_frame())
        self.screen_boxes = list(boxes) if boxes else []
        self.screen_texts = [box.name for box in self.screen_boxes]
        self.next_ocr = time.time() + OCR_INTERVAL

    def find_text(self, needle):
        return self.find_box(needle) is not None

    def find_any(self, needles):
        return any(self.find_text(needle) for needle in needles)

    def find_box(self, *needles):
        """返回第一个名字里含任一关键字的 OCR 框（返回 None 表示这屏没认出来）。"""
        for box in self.screen_boxes:
            for needle in needles:
                if needle in box.name:
                    return box
        return None

    def log_unknown_screen(self):
        """认不出界面时，节流地把这一屏认到的文字写进日志，方便对着实机排查。"""
        now = time.time()
        if now < self.next_unknown_log:
            return
        self.next_unknown_log = now + UNKNOWN_LOG_INTERVAL
        self.log_info("认不出当前界面，这一屏认到的文字: %s"
                      % (" | ".join(self.screen_texts) if self.screen_texts else "(空)"))

    def reset_round_state(self):
        """一轮的状态：开局处理跑过没、技能序列放过没。"""
        self._mission_started = False
        self.sequence_done = False
        self.pending_esc = False
        self.round_start_time = 0.0
        self.next_timeout_esc = 0.0
        self.sequence_settled = False
        self.step_index = 0

    def in_mijin_mission(self):
        """局内判据：左下角出现角色等级 LV.xx。"""
        width, height = self.width, self.height
        for box in self.screen_boxes:
            if not LV_PATTERN.match(box.name.strip()):
                continue
            if box.x < width * LV_MAX_X_RATIO and box.y + box.height > height * LV_MIN_BOTTOM_RATIO:
                return True
        return False

    # ------------------------------------------------------------------
    # 角色手法（不走全局技能计时器，一轮只放一次）
    # ------------------------------------------------------------------

    def current_character(self):
        return self.config.get("使用角色", DEFAULT_CHARACTER)

    def setup_character(self):
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
            self.log_info("没有「%s」的角色手法，退回全局技能计时器" % name)
            self.character_steps = None
            self.character_loops = False
            self.fallback_skill_tick = self.create_skill_ticker()
        else:
            self.character_steps = rotation["steps"]
            self.character_loops = bool(rotation.get("loop", False))
            self.fallback_skill_tick = None

    def parse_custom_steps(self):
        """把「自定义序列」解析成 ((动作, 等待秒数), ...)；解析不出任何一步就返回空。

        格式：每一步用英文/中文逗号、分号、顿号或换行分隔，写成「技能」或「技能:等待秒数」。
        技能名同「全局技能设定」那套：写「战技」按短按处理，「长按战技」按住 COMBAT_LONG_PRESS 秒。
        例：长按战技:1, 战技:1, 终结技:1
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
        """按「使用角色」的手法放技能。

        一次性角色（止流）：整串按顺序放一遍，每步放完等这一步配置的秒数。
        循环角色（伊薇）：每次主循环只走一步，靠主循环不断回来接下一步 —— 这样循环期间
        还能继续整屏 OCR 判界面（打完一关的弹窗、退出结算…），不会卡死在技能循环里。
        """
        if not self.character_loops:
            if self.sequence_done:
                return
            self.sequence_done = True
            self.round_start_time = time.time()
            self.log_info("释放「%s」技能序列: %s"
                          % (self.current_character(), self.describe_steps()))
            for action, wait in self.character_steps:
                self.release_character_action(action)
                self.sleep(wait)
            return

        if not self.sequence_done:
            self.sequence_done = True
            self.round_start_time = time.time()
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

        直接按键，不走角色对象（角色对象拿不到就整段静默跳过，表现就是"点了没反应"）；
        键值一律取「游戏快捷键设置」（Game Hotkey Config）里的战技 / 终结技 / 魔灵支援，
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
            self.log_info("放技能: 普攻")
            self.click()
        elif action == "重击":
            self.log_info("放技能: 重击（按住 %.1f 秒）" % HEAVY_ATTACK_HOLD)
            self.mouse_down()
            try:
                self.sleep(HEAVY_ATTACK_HOLD)
            finally:
                self.mouse_up()
        else:
            raise ValueError("未知技能动作: %s" % action)

    def advance_failed(self):
        """「自动前进到开战」在这里超时：这个模式没到结算页就不该主动放弃，继续挂机。"""
        self.log_info("自动前进到开战超时，不再前进，继续挂机")
        return True

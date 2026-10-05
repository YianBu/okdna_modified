from qfluentwidgets import FluentIcon
import re
import time

from ok import Logger, TaskDisabledException

from src.tasks.AutoExpulsion import AutoExpulsion
from src.tasks.CommissionsTask import Mission
from src.dna_ui.Defs import COORD, LETTER_BOARD_COLUMN_X

logger = Logger.get_logger(__name__)

# 委托密函列表（图1）的三个栏目，从左到右。下标要和 LETTER_BOARD_COLUMN_X 对齐。
COLUMN_NAMES = ("角色", "武器", "魔之楔")
# 「持有数35」和「持有数：815」两种形态都只取数字。
COUNT_RE = re.compile(r'持有数\s*[:：]?\s*(\d+)')
# 图1 的「24分34秒刷新密函委托」和图2 的「刷新密函委托21分47秒」共用这一条。
REFRESH_RE = re.compile(r'(\d+)\s*分\s*(\d+)\s*秒')
# 只要数字（密函卡上的持有数）。
DIGIT_RE = re.compile(r'[0-9]+')
# 「Lv.40」这类等级文字，记录"这一栏有哪些任务"时要排掉（OCR 大小写不稳，忽略大小写）
LEVEL_RE = re.compile(r'^l?v?\.?\s*\d+$', re.IGNORECASE)
# 刷新容错：流程是"先读刷新倒计时 xx分xx秒，再一直跑这段时间，然后回图1 重读"。
# 实际跑的时长比读到的多 1 分钟（xx+1分xx秒），保证回到图1 时刷新确实发生过、委托已重roll。
REFRESH_TOLERANCE_SECONDS = 60
# 图2 里连续这么多秒认不出任何「密函流程界面」，就当这一栏打不下去了（密函开完、
# 或刷新后当前委托失效），回图1 重新选。
LETTER_FLOW_STALL_TIME_OUT = 45


class AutoLetterOpenTask(AutoExpulsion):
    """全自动「自动开密函」：在委托密函列表里挑「驱离」任务，一直打到不能再打。

    图1 = 委托密函列表（角色 / 武器 / 魔之楔 三栏，每栏一行「持有数N」+ 任务槽）；
    图2 = 某个密函任务的开始界面，也就是「自动驱离」平时开工的那个界面。

    流程：
      1) 图1：读三栏的「持有数」，只在 持有数>0 且该栏有「驱离」 时点那个「驱离」进图2；
         （图2 只有从图1 点「驱离」才进得去，别处到不了）
      2) 图2：点「选择密函」开打。打完一把游戏给的是**结算界面**（委托完成 / 再次进行 /
         退出委托），所以内层循环就在结算界面点「再次进行」-> 密函选择 -> 打 -> 密函奖励
         -> 结算，一直重复打这一栏，中途不主动回列表；
      3) 出现下面任一种情况才点「退出委托」/按 ESC 回图1，重新扫描换任务：
           - 密函选择弹窗里能选的密函卡都没了（只剩「⊘ 不使用」，卡牌那一条读不到持有数）
             -> 这一栏的密函开完了；
           - 跑满了"刷新倒计时 + 1 分钟容错"这段时间（见下面的计时说明）；
           - 连续 LETTER_FLOW_STALL_TIME_OUT 秒认不出任何密函流程界面（当前委托失效等）；
           - 游戏自己把我们踢回了图1 列表。
      4) 三栏都没有可打的「驱离」时，读图1 右下角倒计时等刷新再扫一遍；
         「等待刷新」关掉则直接结束任务。

    计时（先检测、再按检测到的时长跑，跑完回图1 重新检测）：
      进这一栏之前先在**图1** 读一次「xx分xx秒刷新密函委托」兜底，进图2 后再读一次
      「刷新密函委托xx分xx秒」（图2 优先）。跑的时间 = 读到的 xx分xx秒 **再加 1 分钟容错**，
      也就是界面上写 xx分xx秒 就跑 xx+1分xx秒。到点回图1，重新读、重新算、再跑下一轮。
      到点时如果人还在本里，就先打完这一局（不半路硬拽出来），一离开局内马上回图1
      —— 最多多打一局；每局本身还有「超时时间」上限兜底。
      至少要已经打过一局才认这个时间，避免单次 OCR 读错就在两屏之间空转。

    实现上直接继承 AutoExpulsion：局内的走位/技能/密函选择/密函奖励完全复用，
    这里只加"图1 选任务"和"图1 <-> 图2 的往返判断"。界面判据与坐标见 src/dna_ui/Defs.py。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.icon = FluentIcon.FLAG
        self.name = "自动开密函"
        self.description = "全自动"
        self.group_name = "全自动"
        self.group_icon = FluentIcon.CAFE

        self.default_config.update({
            "等待刷新": True,
        })
        self.config_description.update({
            "等待刷新": "列表里暂时没有可打的「驱离」时，等它下次刷新后再扫一遍；关掉则直接结束任务",
        })

        # 有没有真正进过局内 —— 图2 和"打完一局又回到图2"是同一个界面，靠它区分
        self._entered_mission = False
        # 列表 OCR 的短缓存，避免主循环每 0.1 秒都跑一次整块 OCR
        self._board_cache = None
        self._board_cache_time = 0
        # 图1 上读到的刷新时刻（进图2 前先读一次，图2 那串读不到时用它兜底）
        self._board_deadline = None
        # 「自动驱离」在自己 do_run 里初始化这个计数器，这里覆盖了 do_run 就得自己补上，
        # 否则继承来的 handle_in_mission 执行 self.count += 1 时会 AttributeError。
        self.count = 0

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------
    def do_run(self):
        self.init_all()
        self.load_char()
        self.wait_for_start_state()
        while True:
            if self.in_team():
                self._entered_mission = True
                self.handle_in_mission()
                self.sleep(0.1)
                continue

            # 图1：列表上就选任务（放在最前面判：万一同位置还有其他按钮也不能抢到这条分支）
            if self.is_letter_board():
                self._entered_mission = False
                if not self.pick_drive_away():
                    self.handle_no_drive_away()
                self.sleep(0.2)
                continue

            self.run_letter_missions()
            self.sleep(0.1)

    def wait_for_start_state(self, time_out=300):
        """等界面处于能开工的状态：图1 列表、图2 开始界面，或结算界面（这一局还没退）。

        从大世界/主菜单怎么打开委托密函列表不由本任务管（用户会先自己打开列表），
        所以启动时如果三个界面都认不到，就提示用户先打开列表再启动。
        """
        if self.is_letter_board() or self.find_start_interface() or self.find_result_again_btn():
            return True
        self.log_info_notify("请先打开「委托密函」列表（角色 / 武器 / 魔之楔 三栏）再启动本任务")
        self.soundBeep()
        if not self.wait_until(lambda: self.is_letter_board() or self.find_start_interface()
                               or self.find_result_again_btn(),
                               time_out=time_out, raise_if_not_found=False):
            raise Exception("等待「委托密函」列表超时，请先打开该界面再启动任务")
        return True

    # ------------------------------------------------------------------
    # 图2：一直重复打当前这一栏
    # ------------------------------------------------------------------
    def run_letter_missions(self):
        """在图2 里一直重复打当前这一栏，直到刷新 / 打不下去 / 被游戏踢回列表。"""
        # 先检测刷新倒计时，再跑这段时间：图2 的倒计时优先（进这一栏时刚读的），
        # 读不到就用点「驱离」前在图1 读到的那个。
        deadline = self.start_screen_refresh_deadline() or self._board_deadline
        self.log_info("本次预计运行到刷新后 1 分钟：%s" % self.format_deadline(deadline))
        last_flow_time = time.time()
        deadline_hit_logged = False
        while True:
            if self.in_team():
                self._entered_mission = True
                last_flow_time = time.time()
                # 到点了但人还在本里：不半路硬拽出来（本局奖励还在），打完这一局、
                # 一离开局内上面的分支就让位给下面那条"到点回列表"，最多多打一局。
                if deadline and not deadline_hit_logged and time.time() >= deadline:
                    deadline_hit_logged = True
                    self.log_info("已到刷新时间但还在本内，等本局结束就回列表重新选择")
                self.handle_in_mission()
                self.sleep(0.1)
                continue

            # 游戏自己把我们踢回列表了（刷新后当前委托失效等）
            if self.is_letter_board():
                self._entered_mission = False
                self.log_info("已经回到委托密函列表")
                return

            # 密函选择弹窗：能选的密函卡都没了（只剩 ⊘ 不使用）-> 这一栏开完了
            if self._entered_mission and self.find_letter_interface() and self.letter_exhausted():
                self.log_info("这一栏的密函已经开完，回列表重新选择")
                self.leave_letter_start()
                return

            now = time.time()
            # 至少要打过一局才认这个刷新时间：图2 那串倒计时只读得到一次，读错了不至于空转
            if deadline and now >= deadline and self._entered_mission:
                self.log_info("密函委托已到刷新时间，回列表重新选择")
                self.leave_letter_start()
                return

            if self.in_letter_flow_screen():
                last_flow_time = now
            elif now - last_flow_time > LETTER_FLOW_STALL_TIME_OUT:
                self.log_info("密函任务无法继续进行，回列表重新选择")
                self.leave_letter_start()
                return

            status = self.handle_mission_interface(stop_func=lambda: False)
            if status == Mission.START:
                self.wait_until(self.in_team, time_out=30)
                self.init_all()
                self._entered_mission = True
                self.handle_mission_start()
                # 顺手重读一次刷新倒计时（只有回到图2 时才读得到，读不到就沿用原来的）
                fresh_deadline = self.start_screen_refresh_deadline()
                if fresh_deadline:
                    deadline = fresh_deadline
            self.sleep(0.1)

    def letter_exhausted(self):
        """密函选择弹窗里还有没有可选的密函卡。

        判据：卡牌矩阵那一行本来每张密函卡都印着持有数（实拍 100 / 85 / 85 ...），
        「⊘ 不使用」那一格没有数字；密函开完后只剩「不使用」，这一行就读不到任何数字了。
        只在密函选择弹窗上调用。
        """
        box = self.screen_box('LETTER_CARD_ROW')
        self.draw_boxes(box.name, box, 'blue')
        return not self.ocr(box=box, match=DIGIT_RE)

    def leave_letter_start(self, time_out=20):
        """从图2 离开回图1：结算界面点「退出委托」，其它情况按 ESC 返回。"""
        if self.is_letter_board(force=True):
            self._entered_mission = False
            return True
        deadline = time.time() + time_out
        while time.time() < deadline:
            if self.find_result_again_btn():
                self.click_ui_coord(COORD.RESULT_QUIT, name="letter_result_quit", after_sleep=1)
            else:
                self.send_key("esc")
            if self.wait_until(self.is_letter_board, time_out=2, raise_if_not_found=False):
                self._entered_mission = False
                return True
        self.log_info_notify("没能返回委托密函列表，请检查界面是否正常")
        return False

    def in_letter_flow_screen(self):
        """当前是不是密函流程里某个能认出来的界面（用来判断这一栏还打不打得了）。"""
        return bool(self.find_start_interface()
                    or self.find_result_again_btn()
                    or self.find_letter_interface()
                    or self.find_manual_select_btn()
                    or self.find_letter_reward_btn()
                    or self.find_action_dialog_continue()
                    or self.find_action_dialog_retreat()
                    or self.find_esc_menu())

    def start_screen_refresh_deadline(self):
        """读图2 右上角「刷新密函委托xx分xx秒」，换算成"跑完该跑的时间"的绝对时刻。"""
        box = self.screen_box('LETTER_START_REFRESH')
        self.draw_boxes(box.name, box, 'blue')
        found = self.ocr(box=box, match=REFRESH_RE)
        if not found:
            return None
        match = REFRESH_RE.search(found[0].name)
        if not match:
            return None
        return self.refresh_deadline(int(match.group(1)) * 60 + int(match.group(2)))

    @staticmethod
    def refresh_deadline(seconds):
        """把"还剩多少秒刷新"换算成绝对时刻：读到的时长 + 1 分钟容错。

        读到的倒计时是"距离刷新还剩多久"，容错加 1 分钟后再回图1，能保证刷新真发生过了。
        """
        return time.time() + seconds + REFRESH_TOLERANCE_SECONDS

    @staticmethod
    def format_deadline(deadline):
        if not deadline:
            return "没读到刷新倒计时"
        return time.strftime("%H:%M:%S", time.localtime(deadline))

    # ------------------------------------------------------------------
    # 图1：读列表、点「驱离」
    # ------------------------------------------------------------------
    def is_letter_board(self, force=False):
        return self.scan_letter_board(force=force)["on_board"]

    def scan_letter_board(self, force=False, ttl=1.0):
        """OCR 委托密函列表，解析出每栏的「持有数」和「驱离」位置。

        返回 {"on_board": bool, "counts": [int|None]x3, "drive_away": [Box|None]x3}。
        整块列表一次 OCR，再按 x 把文字归到对应栏目 —— 比每个元素单独开一次 OCR
        少跑很多趟，也不怕文字被检测器切成两段。
        """
        now = time.time()
        if not force and self._board_cache is not None and now - self._board_cache_time < ttl:
            return self._board_cache

        box = self.screen_box('LETTER_BOARD')
        self.draw_boxes(box.name, box, 'blue')
        results = self.ocr(box=box, match=None)

        data = {"on_board": False, "counts": [None, None, None],
                "drive_away": [None, None, None], "tasks": [[], [], []]}
        opened = 0
        headers = 0
        for item in results:
            index = self.column_index(item.x)
            if index is None:
                continue
            name = item.name.strip()
            if '当前开放' in name:
                opened += 1
                continue
            if name in COLUMN_NAMES:
                headers += 1
                continue
            count_match = COUNT_RE.search(name)
            if count_match:
                data["counts"][index] = int(count_match.group(1))
                continue
            # 只认「驱离」：界面上还有个形近的「驱逐」，是另一种任务，所以别按「驱」前缀匹配
            if '驱离' in name and data["drive_away"][index] is None:
                data["drive_away"][index] = item
            if not LEVEL_RE.match(name):
                data["tasks"][index].append(name)

        # 「当前开放」每栏一行、「角色/武器/魔之楔」每栏一个标题：两个信号都只在列表上出现，
        # 阈值放到 2/3 是为了容 OCR 漏一两个，同时避开密函奖励界面（那里也有「持有数」，
        # 但没有这两个词，所以不会被误判成列表）。
        data["on_board"] = opened >= 2 or headers >= 3
        self._board_cache = data
        self._board_cache_time = now
        return data

    @staticmethod
    def column_index(x):
        """文字左边缘 x 落在哪个栏目区间里；不在任何一栏就返回 None。"""
        for index, (left, right) in enumerate(LETTER_BOARD_COLUMN_X):
            if left <= x < right:
                return index
        return None

    def pick_drive_away(self):
        """挑一个「持有数>0 且该栏有驱离」的任务点进去，成功返回 True。"""
        data = self.scan_letter_board(force=True)
        if not data["on_board"]:
            return False

        for index, column in enumerate(COLUMN_NAMES):
            target = data["drive_away"][index]
            if target is None:
                continue
            count = data["counts"][index]
            if count is None:
                self.log_info(f"[{column}] 有「驱离」但持有数没认出来，跳过这一栏")
                continue
            if count <= 0:
                self.log_info(f"[{column}] 持有数 {count}，没有密函可开")
                continue
            self.log_info(f"[{column}] 持有数 {count}，有「驱离」，进去一直开密函")
            # 点完就离开列表：缓存作废，避免下一圈还当成"在列表上"再点一次
            self._board_cache = None
            self._entered_mission = False
            # 进图2 之前先在图1 读一次刷新倒计时，图2 那串读不到时拿它兜底
            seconds = self.read_refresh_countdown()
            self._board_deadline = self.refresh_deadline(seconds) if seconds else None
            self._click_detected(target, name="letter_board_drive_away", after_sleep=0.5)
            # 等界面真的切到图2 再回主循环：列表淡出/图2 淡入那一两秒里 OCR 还会认到列表，
            # 不等的话下一圈会以为"还在列表上"又点一次。
            self.wait_until(self.find_start_interface, time_out=5, raise_if_not_found=False)
            return True
        return False

    def handle_no_drive_away(self):
        """三栏都没有可打的「驱离」。等下一次刷新，或者按配置直接收工。"""
        data = self.scan_letter_board(force=True)
        detail = "  ".join("%s: 持有数=%s 任务=%s" % (column, data["counts"][index], data["tasks"][index])
                           for index, column in enumerate(COLUMN_NAMES))
        self.log_info("三栏现状 -> " + detail)
        if not self.config.get("等待刷新", True):
            self.log_info_notify("委托密函列表里没有可打的「驱离」，任务结束")
            self.soundBeep()
            raise TaskDisabledException
        seconds = self.read_refresh_countdown()
        wait = seconds + REFRESH_TOLERANCE_SECONDS if seconds else 65
        self.log_info_notify(f"暂时没有可打的「驱离」，等 {int(wait)} 秒刷新后重试")
        self.soundBeep()
        self.sleep(wait)

    def read_refresh_countdown(self):
        """读图1 右下角「xx分xx秒刷新密函委托」的倒计时，返回秒数；读不到返回 None。"""
        box = self.screen_box('LETTER_REFRESH')
        self.draw_boxes(box.name, box, 'blue')
        found = self.ocr(box=box, match=REFRESH_RE)
        if not found:
            return None
        match = REFRESH_RE.search(found[0].name)
        if not match:
            return None
        return int(match.group(1)) * 60 + int(match.group(2))

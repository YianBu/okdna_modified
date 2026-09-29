from qfluentwidgets import FluentIcon
import time
import win32con

from ok import Logger, TaskDisabledException
from src.tasks.DNAOneTimeTask import DNAOneTimeTask
from src.tasks.CommissionsTask import CommissionsTask, Mission, AUTO_ADVANCE_TIME_OUT
from src.tasks.BaseCombatTask import BaseCombatTask

from src.tasks.AutoDefence import AutoDefence

logger = Logger.get_logger(__name__)

# 开局走位：按住 W 一直走到开战（目标栏出现保护目标的波次计数），再往前走
# WALK_EXTRA_TIME 秒 —— 判据出现时人往往还差一点才真正走进交战区。
# 走满 WALK_TIME_OUT 秒还没开战就松手，交给 handle_mission_start 里那段
# 「等待战斗开始」超时去放弃重开，而不是无限往前走。
WALK_EXTRA_TIME = 1.0
WALK_TIME_OUT = AUTO_ADVANCE_TIME_OUT


class Auto65ArtifactTask_Fast(DNAOneTimeTask, CommissionsTask, BaseCombatTask):
    """
    移动更快的自动30/65级mod，路径参考EMT
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.icon = FluentIcon.FLAG
        self.name = "自动防御"
        self.description = "全自动"
        self.group_name = "全自动"
        self.group_icon = FluentIcon.CAFE

        self.setup_commission_config()

        self.action_timeout = 10
        # 走位时借「自动扼守」的开战判据（见 _combat_started）
        self._mission_task = None

    def run(self):
        """主运行方法"""
        DNAOneTimeTask.run(self)
        self.move_mouse_to_safe_position(save_current_pos=False)
        self.set_check_monthly_card()
        try:
            _to_do_task = self.get_task_by_class(AutoDefence)
            self._mission_task = _to_do_task
            _to_do_task.config_external_movement(self.walk_to_aim, self.config)
            original_info_set = _to_do_task.info_set
            _to_do_task.info_set = self.info_set
            return _to_do_task.do_run()
        except TaskDisabledException:
            pass
        except Exception as e:
            logger.error("AutoMyDungeonTask error", e)
            raise
        finally:
            if _to_do_task is not self:
                _to_do_task.info_set = original_info_set

    # def do_run(self):
    #     """执行任务的核心逻辑"""
    #     # 加载角色信息
    #     self.load_char()

    #     # 初始化变量
    #     _start_time = 0  # 任务开始时间
    #     _skill_time = 0  # 上次释放技能的时间
    #     _count = 0  # 完成次数计数器

    #     # 如果已经在队伍中，先放弃当前任务
    #     if self.in_team():
    #         self.log_info("检测到已在队伍中，先放弃当前任务")
    #         self.give_up_mission()
    #         self.wait_until(lambda: not self.in_team(), time_out=30, settle_time=1)

    #     # 主循环
    #     while True:
    #         # 在队伍中时的逻辑（战斗中）
    #         if self.in_team():
    #             # 第一次进入队伍时记录开始时间
    #             if _start_time == 0:
    #                 _start_time = time.time()
    #                 self.log_info(f"开始第 {_count + 1} 次任务")

    #             # 持续释放技能
    #             _skill_time = self.use_skill(_skill_time)

    #             # 检查是否超时
    #             elapsed = time.time() - _start_time
    #             if elapsed >= self.config.get("超时时间", 180):
    #                 logger.warning(f"任务超时 ({elapsed:.1f}秒)，重新开始...")
    #                 self.give_up_mission()
    #                 self.wait_until(lambda: not self.in_team(), time_out=30, settle_time=1)
    #                 _start_time = 0  # 重置计时器

    #         # 处理任务界面
    #         _status = self.handle_mission_interface()

    #         if _status == Mission.START:
    #             # 任务完成
    #             elapsed = time.time() - _start_time if _start_time > 0 else 0
    #             _count += 1
    #             self.log_info(
    #                 f"任务完成 [{_count}/{self.config.get('刷几次', 999)}] 用时: {elapsed:.1f}秒"
    #             )

    #             # 检查是否达到目标次数
    #             if _count >= self.config.get("刷几次", 999):
    #                 self.log_info(f"已完成全部 {_count} 次任务")
    #                 self.soundBeep()
    #                 return

    #             # 等待重新进入队伍
    #             self.wait_until(self.in_team, time_out=30)

    #             # 重置计时器
    #             _start_time = time.time()

    #             # 走到目标位置
    #             try:
    #                 self.walk_to_aim()
    #             except TaskDisabledException:
    #                 raise
    #             except Exception as e:
    #                 logger.error(f"移动到目标位置失败: {e}")
    #                 self.give_up_mission()
    #                 self.wait_until(lambda: not self.in_team(), time_out=30, settle_time=1)
    #                 _start_time = 0
    #             _skill_time = 0
    #         # 短暂休眠
    #         self.sleep(0.2)

    def _combat_started(self):
        """走位的开战判据：借「自动扼守」那份判据（左侧目标栏出现「保护…波次 x/y」），
        保证走位收尾和外层开战判定用的是同一套逻辑。"""
        return self._mission_task is not None and self._mission_task.is_in_combat()

    def walk_to_aim(self, delay=0):
        """开局走位：走到开战，再多走 WALK_EXTRA_TIME 秒。

        原来写死「按住 W 走 9.5 秒」，不同防御副本的走位距离、刷怪时机都不一样：
        走早了站在原地等，走晚了冲过交战区。改成用开战判据收尾。
        """
        logger.info("开始移动到目标位置")
        move_start = time.time()
        self.sleep(delay)
        self.send_key_down("w")
        try:
            deadline = time.time() + WALK_TIME_OUT
            while time.time() < deadline:
                self.next_frame()
                if self._combat_started():
                    self.log_info(f"已进入战斗，再前进 {WALK_EXTRA_TIME} 秒")
                    # 多走这一段时继续取帧，松手时手里的画面是新的
                    extra_deadline = time.time() + WALK_EXTRA_TIME
                    while time.time() < extra_deadline:
                        self.next_frame()
                    break
            else:
                self.log_info(f"前进 {WALK_TIME_OUT} 秒仍未开战，交给超时重开")
            logger.info(f"移动完成，用时 {time.time() - move_start:.1f}秒")
        except TaskDisabledException:
            raise
        except Exception as e:
            logger.error("移动过程出错", e)
            raise
        finally:
            # 确保释放所有按键
            self.send_key_up("w")
            self.send_key_up("a")
            self.send_key_up("s")
            self.send_key_up("d")
            self.send_key_up(self.get_dodge_key())
            self.send_key_up("lshift")

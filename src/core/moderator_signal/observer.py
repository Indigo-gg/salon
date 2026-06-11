"""第二层：状态观测器（EMA + 映射 + LLM 辅助）。

有状态类，持有 EMA 缓冲和映射逻辑。
将 RawSignals 平滑为 StateVector，再映射为 ControlSignals。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.core.moderator_signal.sensors import RawSignals

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 状态向量：8 维（4 当前值 + 4 变化率）
# ---------------------------------------------------------------------------

@dataclass
class StateVector:
    """对话的 8 维物理状态 + 实体变量。"""
    # 当前值
    direction: float = 0.5       # 话题聚焦度 (0=完全跑偏, 1=紧扣主题)
    height: float = 0.3          # 抽象度 (0=完全具体, 1=极度抽象)
    speed: float = 0.3           # 代谢率 (0=停滞, 1=高速代谢)
    formation: float = 0.5       # 阵型结构化程度 (0=各说各话, 1=紧密交锋)
    # 变化率
    delta_direction: float = 0.0 # 正=正在聚焦, 负=正在跑偏
    delta_height: float = 0.0    # 正=正在上升, 负=正在下降
    delta_speed: float = 0.0     # 正=正在加速, 负=正在减速
    delta_formation: float = 0.0 # 正=正在凝聚, 负=正在松散
    # 实体变量（供注入文本动态引用）
    dominant_speaker: str = ""   # 最近发言最多的人
    silent_speaker: str = ""     # 最近最沉默的人
    last_speaker: str = ""       # 上一轮最后发言的人


# ---------------------------------------------------------------------------
# 控制信号：5 个映射输出
# ---------------------------------------------------------------------------

@dataclass
class ControlSignals:
    """主持人需要关注的 5 个控制维度。"""
    readability_alert: float = 0.0          # 可读性警报 (0-1)
    depth_tide_signal: str = "balanced"     # 深度潮汐: "dive" / "surface" / "balanced"
    topic_focus_alert: float = 0.0          # 话题聚焦警报 (0-1)
    tension_level: str = "moderate"         # 对话张力: "monologue" / "parallel" / "moderate" / "debate" / "heated"
    energy_level: str = "flowing"           # 认知能量: "exhausted" / "cooling" / "flowing" / "surging"

    # LLM 辅助信号（由主持人 LLM 反馈）
    llm_emotional_temperature: float = 0.5  # LLM 感知的情绪温度 (0=冷静, 1=高度情绪化)
    llm_perceived_tension: str = "moderate" # LLM 感知的张力: "low" / "moderate" / "high" / "conflict"


# ---------------------------------------------------------------------------
# EMA 计算器
# ---------------------------------------------------------------------------

class EMA:
    """指数移动平均（Exponential Moving Average）。"""

    def __init__(self, half_life: float, initial_value: float = 0.0):
        """
        Args:
            half_life: 半衰期（轮次），值越大平滑越强
            initial_value: 初始值
        """
        self.alpha = 1.0 - 2.0 ** (-1.0 / half_life)
        self.value = initial_value
        self._initialized = False

    def update(self, new_value: float) -> float:
        """更新并返回 EMA 值。"""
        if not self._initialized:
            self.value = new_value
            self._initialized = True
        else:
            self.value = self.alpha * new_value + (1 - self.alpha) * self.value
        return self.value

    def get(self) -> float:
        return self.value


# ---------------------------------------------------------------------------
# 状态观测器
# ---------------------------------------------------------------------------

class SignalObserver:
    """状态观测器：RawSignals → StateVector → ControlSignals。

    内部维护 EMA 缓冲，计算变化率，执行映射规则。
    """

    def __init__(
        self,
        short_half_life: float = 3.0,
        long_half_life: float = 10.0,
    ):
        self.short_hl = short_half_life
        self.long_hl = long_half_life

        # 短窗口 EMA（捕捉近期趋势）
        self._ema_short = {
            "direction": EMA(short_half_life, 0.5),
            "height": EMA(short_half_life, 0.3),
            "speed": EMA(short_half_life, 0.3),
            "formation": EMA(short_half_life, 0.5),
        }
        # 长窗口 EMA（建立基线）
        self._ema_long = {
            "direction": EMA(long_half_life, 0.5),
            "height": EMA(long_half_life, 0.3),
            "speed": EMA(long_half_life, 0.3),
            "formation": EMA(long_half_life, 0.5),
        }

        # 深度潮汐连续计数
        self._consecutive_dive: int = 0
        self._consecutive_surface: int = 0

        # LLM 辅助信号缓存
        self._llm_emotional_temperature: float = 0.5
        self._llm_perceived_tension: str = "moderate"
        # EMA 平滑的情绪温度（首值直通，避免首轮平滑后值严重偏低）
        self._temp_ema: EMA | None = None

        # 原始信号缓存（用于映射规则中的跨维度查询）
        self._last_raw: RawSignals | None = None

        # 当前状态
        self.state = StateVector()
        self.control = ControlSignals()

        logger.info(f"SignalObserver initialized: short_hl={short_half_life}, long_hl={long_half_life}")

    def update(self, raw: RawSignals) -> ControlSignals:
        """接收原始信号，更新状态向量，返回控制信号。"""
        self._last_raw = raw

        # --- 1. 将原始信号归一化为 0-1 的维度值 ---

        direction = self._normalize_direction(raw)
        height = self._normalize_height(raw)
        speed = self._normalize_speed(raw)
        formation = self._normalize_formation(raw)

        # --- 2. 更新 EMA ---

        for key, value in [("direction", direction), ("height", height),
                           ("speed", speed), ("formation", formation)]:
            self._ema_short[key].update(value)
            self._ema_long[key].update(value)

        # --- 3. 计算状态向量 ---

        self.state = StateVector(
            direction=self._ema_short["direction"].get(),
            height=self._ema_short["height"].get(),
            speed=self._ema_short["speed"].get(),
            formation=self._ema_short["formation"].get(),
            delta_direction=self._ema_short["direction"].get() - self._ema_long["direction"].get(),
            delta_height=self._ema_short["height"].get() - self._ema_long["height"].get(),
            delta_speed=self._ema_short["speed"].get() - self._ema_long["speed"].get(),
            delta_formation=self._ema_short["formation"].get() - self._ema_long["formation"].get(),
            dominant_speaker=raw.dominant_speaker,
            silent_speaker=raw.silent_speaker,
            last_speaker=raw.last_speaker,
        )

        # --- 4. 映射为控制信号 ---

        self.control = self._map_to_control()

        return self.control

    def update_llm_feedback(self, emotional_temperature: float, perceived_tension: str) -> None:
        """接收主持人 LLM 的反馈信号。情绪温度做 EMA 平滑，紧张度仅存储。"""
        # 情绪温度：EMA 平滑（复用已有 EMA 类，首值直通）
        if self._temp_ema is None:
            self._temp_ema = EMA(half_life=3.0, initial_value=emotional_temperature)
        smoothed = self._temp_ema.update(emotional_temperature)
        self._llm_emotional_temperature = smoothed
        self.control.llm_emotional_temperature = smoothed
        # 紧张度：仅存储，由 _map_to_control 中的代码规则主导
        self._llm_perceived_tension = perceived_tension
        self.control.llm_perceived_tension = perceived_tension

    # ----- 归一化函数 -----

    def _normalize_direction(self, raw: RawSignals) -> float:
        """方向：topic_keyword_overlap 直接使用 (0-1)。"""
        return max(0.0, min(1.0, raw.topic_keyword_overlap))

    def _normalize_height(self, raw: RawSignals) -> float:
        """高度：IDF 均值归一化 (典型范围 0.5-6.0 → 0-1) + 锚点密度修正。"""
        # IDF 归一化
        idf_norm = max(0.0, min(1.0, (raw.avg_idf - 0.5) / 5.5))
        # 锚点密度修正：锚点多 → 高度降低
        anchor_penalty = min(1.0, raw.anchor_density * 2.0)
        # 抽象词占比
        abstraction = raw.abstraction_ratio

        # 综合：IDF 为主，锚点和抽象词为修正
        height = idf_norm * 0.5 + abstraction * 0.3 + (1 - anchor_penalty) * 0.2
        return max(0.0, min(1.0, height))

    def _normalize_speed(self, raw: RawSignals) -> float:
        """速度：概念周转 + KL 散度归一化 + 句长。

        当概念注册表为空时（turnover=0），KL 散度和句长的权重自动提升。
        """
        # 概念周转 (0-1 直接使用)
        turnover = max(0.0, min(1.0, raw.concept_turnover))
        # KL 散度归一化 (典型范围 0-3.0 → 0-1)
        kl_norm = max(0.0, min(1.0, raw.kl_divergence / 3.0))
        # 句长归一化 (典型范围 5-80 字 → 0-1)
        length_norm = max(0.0, min(1.0, (raw.avg_sentence_length - 5) / 75))

        # 当 turnover 为 0（概念注册表为空），将权重分配给 KL 和句长
        if turnover < 0.01:
            speed = kl_norm * 0.6 + length_norm * 0.4
        else:
            speed = turnover * 0.4 + kl_norm * 0.4 + length_norm * 0.2
        return max(0.0, min(1.0, speed))

    def _normalize_formation(self, raw: RawSignals) -> float:
        """阵型：引用密度 + 立场分化 + Gini 修正 + 发言人数修正。

        当没有任何标记词被检测到时，用发言人数作为基线：
        多人发言 → 默认假设在正常交流（0.5），
        单人发言 → 默认假设是独白（0.2）。
        """
        # 引用密度高 → 结构化程度高
        ref = max(0.0, min(1.0, raw.reference_density))
        # 立场分化：反驳+赞同 > 0 → 有交锋
        stance = min(1.0, raw.stance_opposition + raw.stance_agreement)
        # Gini 高 → 权力集中 → 结构化程度低
        gini_penalty = raw.gini_coefficient

        # 基于信号的阵型得分
        signal_score = ref * 0.4 + stance * 0.3 + (1 - gini_penalty) * 0.3

        # 基于发言人数的基线：多人=0.5，单人=0.2
        if raw.speaker_count >= 3:
            baseline = 0.55
        elif raw.speaker_count >= 2:
            baseline = 0.45
        else:
            baseline = 0.2

        # 如果有明确的信号（引用/反驳/赞同），以信号为主
        # 如果没有信号（都是 0），以基线为主
        has_signals = raw.reference_density > 0 or raw.stance_opposition > 0 or raw.stance_agreement > 0
        if has_signals:
            formation = signal_score * 0.7 + baseline * 0.3
        else:
            formation = baseline

        return max(0.0, min(1.0, formation))

    # ----- 映射规则引擎 -----

    def _map_to_control(self) -> ControlSignals:
        """将 StateVector 映射为 ControlSignals。"""
        s = self.state
        ctrl = ControlSignals()

        # 1. 可读性警报
        # 高度越高且在上升 → 警报越强
        height_pressure = s.height * (1.0 + max(0.0, s.delta_height))
        ctrl.readability_alert = max(0.0, min(1.0, height_pressure))

        # 2. 深度潮汐
        # dive：高度持续偏高（讨论悬浮在抽象层面）
        # surface：高度持续偏低且速度也低（讨论停留在表面且缺乏推进）
        if s.height > 0.55:
            self._consecutive_dive += 1
            self._consecutive_surface = 0
        elif s.height < 0.35 and s.speed < 0.35:
            self._consecutive_surface += 1
            self._consecutive_dive = 0
        else:
            self._consecutive_dive = 0
            self._consecutive_surface = 0

        if self._consecutive_dive >= 3:
            ctrl.depth_tide_signal = "dive"
        elif self._consecutive_surface >= 3:
            ctrl.depth_tide_signal = "surface"
        else:
            ctrl.depth_tide_signal = "balanced"

        # 3. 话题聚焦警报
        # 跑偏且在加速跑偏 → 警报越强
        drift_pressure = (1.0 - s.direction) * (1.0 + max(0.0, -s.delta_direction))
        ctrl.topic_focus_alert = max(0.0, min(1.0, drift_pressure))

        # 4. 对话张力（代码规则主导，LLM 反馈仅 ±1 级微调）
        # 先由代码规则计算基础张力
        if s.formation < 0.3:
            if self._last_raw:
                if self._last_raw.speaker_count == 0:
                    base_tension = "moderate"
                elif self._last_raw.speaker_count == 1:
                    base_tension = "monologue"
                elif self._last_raw.gini_coefficient > 0.4:
                    base_tension = "monologue"
                else:
                    base_tension = "parallel"
            else:
                base_tension = "moderate"
        elif s.formation > 0.7:
            base_tension = "heated" if self._llm_emotional_temperature > 0.7 else "debate"
        else:
            base_tension = "moderate"

        # LLM 反馈仅允许 ±1 级调整，不能跳级
        tension_order = ["monologue", "parallel", "moderate", "debate", "heated", "conflict"]
        llm_tension = self._llm_perceived_tension
        if llm_tension in tension_order:
            base_idx = tension_order.index(base_tension)
            llm_idx = tension_order.index(llm_tension)
            clamped_idx = max(base_idx - 1, min(base_idx + 1, llm_idx))
            ctrl.tension_level = tension_order[clamped_idx]
        else:
            ctrl.tension_level = base_tension

        # 5. 认知能量
        if s.delta_speed < -0.15 and s.formation < 0.4:
            ctrl.energy_level = "exhausted"
        elif s.delta_speed < -0.1:
            ctrl.energy_level = "cooling"
        elif s.speed > 0.6:
            ctrl.energy_level = "surging"
        elif s.speed > 0.3:
            ctrl.energy_level = "flowing"
        else:
            ctrl.energy_level = "cooling"

        # 传递 LLM 信号
        ctrl.llm_emotional_temperature = self._llm_emotional_temperature
        ctrl.llm_perceived_tension = self._llm_perceived_tension

        return ctrl

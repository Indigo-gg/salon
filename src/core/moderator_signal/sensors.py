"""第一层：原始信号测量（规则 + 统计）。

无状态函数集合，每轮调用一次，输出 RawSignals。
零外部依赖：仅使用 stdlib（re, math, collections）。
如检测到 jieba 可用，自动切换为 jieba 分词以提升精度。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# 可选依赖：jieba（提升中文分词精度）
# ---------------------------------------------------------------------------

try:
    import jieba
    _HAS_JIEBA = True
except ImportError:
    _HAS_JIEBA = False


# ---------------------------------------------------------------------------
# 内置 IDF 表（基于通用中文语料库的词频统计）
# 格式：{词: idf_value}，idf = log(N / df)，N=语料库文档总数，df=包含该词的文档数
# 高 IDF = 低频/专业词汇，低 IDF = 高频/通俗词汇
# ---------------------------------------------------------------------------

# 精简版：~300 个覆盖常见抽象/专业词汇的 IDF 值
# 未收录的词使用默认 IDF（基于词长的启发式估计）
_IDF_TABLE: dict[str, float] = {}


def _init_idf_table():
    """初始化内置 IDF 表。"""
    # 高频通俗词（IDF 低，0.5-2.0）
    _low = [
        "的", "了", "是", "在", "我", "有", "和", "就", "不", "人", "都", "一",
        "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有",
        "看", "好", "自己", "这", "他", "她", "它", "们", "那", "里", "为", "什么",
        "怎么", "如果", "因为", "所以", "但是", "可以", "这个", "那个", "还是",
        "其实", "就是", "已经", "然后", "或者", "而且", "虽然", "不过", "可能",
        "应该", "觉得", "知道", "时候", "现在", "这里", "那里", "一些", "一样",
        "我们", "他们", "你们", "大家", "来说", "真的", "确实", "当然", "其实",
        "认为", "问题", "事情", "情况", "地方", "方面", "意思", "关系", "样子",
    ]
    for w in _low:
        _IDF_TABLE[w] = 0.8

    # 中频词（IDF 中等，2.0-4.0）
    _mid = [
        "讨论", "观点", "角度", "例子", "故事", "概念", "理解", "思考", "分析",
        "逻辑", "事实", "证据", "经验", "理论", "实践", "价值", "意义", "原因",
        "结果", "影响", "过程", "方法", "选择", "判断", "立场", "态度", "感受",
        "自由", "责任", "权利", "道德", "正义", "平等", "公平", "真理", "本质",
        "现象", "规律", "结构", "系统", "机制", "模式", "框架", "背景", "前提",
        "假设", "结论", "论证", "反驳", "支持", "反对", "同意", "补充", "质疑",
        "科学", "哲学", "社会", "文化", "历史", "政治", "经济", "技术", "艺术",
        "生命", "死亡", "意识", "记忆", "情感", "理性", "感性", "直觉", "信仰",
        "语言", "符号", "意义", "解释", "定义", "分类", "比较", "区别", "联系",
    ]
    for w in _mid:
        _IDF_TABLE[w] = 3.0

    # 低频专业词（IDF 高，4.0-7.0）
    _high = [
        "本体论", "认识论", "形而上学", "存在主义", "虚无主义", "现象学",
        "辩证法", "唯物主义", "唯心主义", "二元论", "一元论", "功利主义",
        "实用主义", "结构主义", "解构主义", "后现代", "现代性", "主体性",
        "客体性", "交互性", "超验", "先验", "内在性", "超越性", "偶然性",
        "必然性", "自由意志", "决定论", "兼容论", "因果律", "道德律",
        "绝对命令", "范畴", "理念", "自在之物", "物自体", "此在", "存在者",
        "话语权", "意识形态", "上层建筑", "经济基础", "异化", "物化",
        "商品拜物教", "剩余价值", "生产关系", "生产力", "范式", "范式转换",
        "不可通约性", "科学革命", "常规科学", "涌现", "自组织", "复杂系统",
        "混沌理论", "熵增", "还原论", "整体论", "系统论", "信息论",
        "控制论", "博弈论", "纳什均衡", "帕累托最优", "囚徒困境",
        "认知失调", "确认偏误", "幸存者偏差", "达unning-kruger",
        "哥德尔", "图灵", "维特根斯坦", "海德格尔", "萨特", "加缪",
        "尼采", "康德", "黑格尔", "马克思", "亚里士多德", "柏拉图",
        "苏格拉底", "笛卡尔", "斯宾诺莎", "莱布尼茨", "休谟", "洛克",
        "PMF", "unit economics", "burn rate", "product-market fit",
        "MRR", "ARR", "CAC", "LTV", "churn rate", "runway",
    ]
    for w in _high:
        _IDF_TABLE[w] = 5.5

    # ==========================================
    # 扩充：中高频"沙龙讨论"词汇（IDF 中上，3.5-4.5）
    # 常常用于搭建抽象讨论的脚手架
    # ==========================================
    _mid_high = [
        "语境", "维度", "视角", "边界", "核心", "架构", "策略", "叙事",
        "语态", "机制", "变量", "参数", "载体", "媒介", "受众", "主体",
        "客体", "映射", "张力", "悖论", "闭环", "重构", "赋能", "颗粒度",
        "底层逻辑", "顶层设计", "痛点", "痒点", "爽点", "复盘", "心智",
    ]
    for w in _mid_high:
        _IDF_TABLE[w] = 4.0

    # ==========================================
    # 扩充：低频专业词（IDF 高，5.0-6.5）
    # 涵盖 AI/科技、心理学、社会学、前沿物理等硬核沙龙高频词
    # ==========================================
    _high_tech_ai = [
        "大语言模型", "神经网络", "反向传播", "梯度下降", "强化学习",
        "涌现能力", "幻觉", "奇异点", "图灵测试", "中文房间", "参数量",
        "黑盒", "可解释性", "对齐", "AGI", "Transformer", "注意力机制",
        "摩尔定律", "开源", "闭源", "算力", "token", "embedding",
    ]

    _high_psychology = [
        "认知失调", "锚定效应", "防御机制", "潜意识", "移情", "投射",
        "多巴胺", "内啡肽", "斯金纳箱", "巴甫洛夫", "马斯洛", "原生家庭",
        "习得性无助", "自我效能感", "达克效应", "确认偏误", "幸存者偏差",
        "墨菲定律", "皮格马利翁效应", "心流", "冥想", "正念",
    ]

    _high_sociology_media = [
        "信息茧房", "回音室效应", "零和博弈", "剧场效应", "景观社会",
        "消费主义", "阶层固化", "内卷", "躺平", "原子化", "犬儒主义",
        "乌合之众", "拟像", "赛博朋克", "反乌托邦", "老大哥", "全景监狱",
        "麦克卢汉", "媒介即信息", "鲍德里亚", "福柯", "布迪厄", "哈贝马斯",
    ]

    _high_physics_math = [
        "薛定谔", "量子纠缠", "测不准原理", "海森堡", "相对论", "时空弯曲",
        "热力学第二定律", "奥卡姆剃刀", "斐波那契", "拓扑", "分形",
        "暗物质", "第一性原理", "弦理论", "平行宇宙",
    ]

    for w in _high_tech_ai + _high_psychology + _high_sociology_media + _high_physics_math:
        _IDF_TABLE[w] = 5.5

    # 原有的极高哲学/经济词汇保持最高 IDF
    _IDF_TABLE.update({w: 6.0 for w in _high if w in _IDF_TABLE})
    # 重新覆盖为 6.0
    for w in _high:
        _IDF_TABLE[w] = 6.0


_init_idf_table()

# 默认 IDF 值：基于词长的启发式估计
_DEFAULT_IDF_BY_LENGTH = {
    1: 1.0,   # 单字：极常见
    2: 2.0,   # 双字：常见
    3: 3.5,   # 三字：较不常见
    4: 4.5,   # 四字：可能是成语或专业术语
    5: 5.5,   # 五字以上：大概率是专业术语
}


# ---------------------------------------------------------------------------
# 分词器
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """中文分词：优先使用 jieba，回退到最长匹配词典分词。"""
    if _HAS_JIEBA:
        return [w for w in jieba.lcut(text) if len(w.strip()) > 0]
    # 最长匹配词典分词（MM 分词）
    return _mm_tokenize(text)


def _mm_tokenize(text: str) -> list[str]:
    """基于词典的最长匹配分词（Maximum Matching）。

    使用 _IDF_TABLE + _PERSON_NAMES + _IDIOMS 作为词典，
    从左到右贪心匹配最长的已知词。
    """
    # 构建词典集合（所有已知词）
    _dict: set[str] = set()
    _dict.update(_IDF_TABLE.keys())
    _dict.update(_PERSON_NAMES)
    _dict.update(_IDIOMS)
    # 添加常用停用词（确保它们也能被匹配到）
    _dict.update(_STOPWORDS)

    max_word_len = max((len(w) for w in _dict), default=1)

    tokens: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]

        # 英文/数字序列：直接提取
        if ch.isascii() and (ch.isalpha() or ch.isdigit()):
            j = i
            while j < len(text) and text[j].isascii() and (text[j].isalpha() or text[j].isdigit() or text[j] == '_'):
                j += 1
            if j - i >= 2:
                tokens.append(text[i:j])
            i = j
            continue

        # 中文字符：最长匹配
        if '一' <= ch <= '鿿':
            matched = False
            for length in range(min(max_word_len, len(text) - i), 1, -1):
                candidate = text[i:i + length]
                if candidate in _dict:
                    tokens.append(candidate)
                    i += length
                    matched = True
                    break
            if not matched:
                # 单字：跳过（不作为 token）
                i += 1
            continue

        # 其他字符（标点等）：跳过
        i += 1

    return tokens


def _tokenize_for_keywords(text: str) -> list[str]:
    """提取关键词级别的 token（过滤停用词、口水词和纯数字）。"""
    # 预处理：去掉常见标点符号和特殊字符
    text = re.sub(r'[^\w\s一-龥]', '', text)

    tokens = _tokenize(text)

    # 过滤条件：
    # 1. 不在停用词表中
    # 2. 长度 >= 2（排除单字，因为单字很难承载明确的高级概念）
    # 3. 排除纯数字
    valid_tokens = [
        t for t in tokens
        if len(t) >= 2
        and t not in _STOPWORDS
        and not t.isdigit()
    ]
    return valid_tokens


# 扩展后的高频停用词集合（过滤口水词）
_STOPWORDS = {
    # 基础虚词
    "的", "了", "是", "在", "我", "有", "和", "就", "不", "人", "都", "一",
    "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看",
    "好", "自己", "这", "他", "她", "它", "们", "那", "里", "为", "什么", "怎么",
    # 连词/副词
    "如果", "因为", "所以", "但是", "可以", "这个", "那个", "还是", "其实",
    "就是", "已经", "然后", "或者", "而且", "虽然", "不过", "可能", "应该",
    # 代词/指代
    "觉得", "知道", "时候", "现在", "这里", "那里", "一些", "一样", "我们",
    "他们", "你们", "大家", "来说", "真的", "当然", "认为", "这样", "那样",
    "哪个", "哪些", "每个", "任何", "某些", "某个",
    # 语气助词
    "啊", "哦", "嗯", "哈", "嘛", "呢", "吧", "哎", "呀", "呐", "喔",
    # 口水动词
    "来说", "告诉", "想起", "感觉", "发现", "看看", "想想", "听听",
    # 常见无意义双字词
    "其实", "然后", "就是", "不是", "没有", "已经", "可能", "应该",
    "关于", "通过", "进行", "开始", "结束", "继续", "比较", "非常",
}


# ---------------------------------------------------------------------------
# 原始信号数据结构
# ---------------------------------------------------------------------------

@dataclass
class RawSignals:
    """每轮计算的原始测量值。"""

    # --- 方向（Direction）---
    topic_keyword_overlap: float = 1.0    # 当前轮关键词与初始主题的重叠度 (0-1)
    topic_drift: float = 0.0              # 1 - overlap（越远离主题值越大）

    # --- 高度（Height）---
    avg_idf: float = 0.0                  # 平均 IDF 值（越高越抽象）
    anchor_density: float = 0.0           # 具体锚点密度（数字/日期/引号/人名标记词）
    abstraction_ratio: float = 0.0        # 4 字以上低频词占比

    # --- 速度（Speed）---
    concept_turnover: float = 0.0         # 概念代谢率
    kl_divergence: float = 0.0            # 前后轮 KL 散度
    avg_sentence_length: float = 0.0      # 平均句长

    # --- 阵型（Formation）---
    reference_density: float = 0.0        # 引用他人发言的发言占比
    stance_opposition: float = 0.0        # 反驳标记词密度
    stance_agreement: float = 0.0         # 赞同标记词密度
    gini_coefficient: float = 0.0         # 发言字数基尼系数
    speaker_count: int = 0                # 本轮发言人数

    # --- 实体变量（供注入文本动态引用）---
    dominant_speaker: str = ""            # 本轮发言最多的人（字数最多）
    silent_speaker: str = ""              # 本轮未发言的人（从 participant_ids 中排除）
    last_speaker: str = ""                # 本轮最后发言的人


# ---------------------------------------------------------------------------
# 核心测量函数
# ---------------------------------------------------------------------------

def compute_raw_signals(
    round_num: int,
    recent_messages: list,
    topic: str,
    concept_registry: dict | None = None,
    participant_ids: list[str] | None = None,
    prev_token_dist: dict[str, float] | None = None,
) -> tuple[RawSignals, dict[str, float]]:
    """计算当前轮次的原始信号。

    Args:
        round_num: 当前轮次
        recent_messages: 最近的消息列表（Message 对象）
        topic: 讨论主题
        concept_registry: 概念注册表（来自 RoundMonitor）
        participant_ids: 所有参与者 ID 列表
        prev_token_dist: 上一轮的词频分布（用于 KL 散度计算）

    Returns:
        (RawSignals, current_token_dist) — 当前信号和词频分布（供下轮使用）
    """
    signals = RawSignals()

    # 提取本轮消息（按轮次分组）
    current_round_msgs = []
    all_recent_text = ""
    for msg in recent_messages:
        if hasattr(msg, 'content') and hasattr(msg, 'round'):
            all_recent_text += " " + msg.content
            if msg.round == round_num:
                current_round_msgs.append(msg)

    if not current_round_msgs:
        return signals, prev_token_dist or {}

    current_text = " ".join(m.content for m in current_round_msgs)

    # --- 方向 ---
    _measure_direction(signals, current_text, topic)

    # --- 高度 ---
    _measure_height(signals, current_text)

    # --- 速度 ---
    current_token_dist = _measure_speed(
        signals, current_text, concept_registry or {}, prev_token_dist,
    )

    # --- 阵型 ---
    _measure_formation(signals, current_round_msgs, participant_ids or [])

    return signals, current_token_dist


# ---------------------------------------------------------------------------
# 方向测量
# ---------------------------------------------------------------------------

def _measure_direction(signals: RawSignals, current_text: str, topic: str) -> None:
    """测量话题聚焦度：当前轮关键词与初始主题的重叠度。"""
    # 提取主题关键词
    topic_tokens = set(_tokenize_for_keywords(topic))
    if not topic_tokens:
        signals.topic_keyword_overlap = 1.0
        signals.topic_drift = 0.0
        return

    # 提取当前轮关键词
    current_tokens = set(_tokenize_for_keywords(current_text))
    if not current_tokens:
        signals.topic_keyword_overlap = 0.5
        signals.topic_drift = 0.5
        return

    # Jaccard 相似度的变体：主题关键词在当前轮的覆盖率
    overlap = topic_tokens & current_tokens
    coverage = len(overlap) / len(topic_tokens)

    # 也计算反向覆盖率（当前轮引入了多少主题无关的新词）
    new_words = current_tokens - topic_tokens
    novelty = len(new_words) / max(len(current_tokens), 1)

    # 综合得分：coverage 高且 novelty 低 = 紧扣主题
    signals.topic_keyword_overlap = max(0.0, min(1.0, coverage * 0.7 + (1 - novelty) * 0.3))
    signals.topic_drift = 1.0 - signals.topic_keyword_overlap


# ---------------------------------------------------------------------------
# 高度测量
# ---------------------------------------------------------------------------

def _measure_height(signals: RawSignals, current_text: str) -> None:
    """测量抽象度：IDF 均值 + 锚点密度 + 抽象词占比。

    特殊处理：
    - 成语：虽然 4 字，但作用是降低阅读门槛，IDF 强制压低到 2.0
    - 学者人名：虽然 IDF 极高，但它们是"地面标记物"（具体锚点），
      从 IDF 计算中排除，但计入锚点密度。
    """
    tokens = _tokenize(current_text)
    if not tokens:
        return

    # 1. 平均 IDF（排除人名，修正成语）
    idf_values = []
    person_name_count = 0
    for t in tokens:
        # 学者人名陷阱：高 IDF 词但同时是具体锚点
        # 从 IDF 计算中排除，避免拉高平均值
        if t in _PERSON_NAMES:
            person_name_count += 1
            continue
        # 成语陷阱：4 字词但实际降低阅读门槛
        if t in _IDIOMS:
            idf_values.append(2.0)
            continue
        # 正常 IDF 查表
        if t in _IDF_TABLE:
            idf_values.append(_IDF_TABLE[t])
        else:
            length = len(t)
            default_idf = _DEFAULT_IDF_BY_LENGTH.get(
                min(length, 5), _DEFAULT_IDF_BY_LENGTH[5]
            )
            # 4 字以上未收录词：可能是成语或专业术语
            # 如果不在任何专业词表中，给一个中等偏高的默认值
            idf_values.append(default_idf)

    signals.avg_idf = sum(idf_values) / len(idf_values) if idf_values else 0.0

    # 2. 锚点密度：数字、日期、引号内容、具体标记词、人名
    anchors = 0
    anchors += len(re.findall(r'\d+', current_text))                           # 数字
    anchors += len(re.findall(r'[""「」『』](.*?)[""「」『』]', current_text))  # 引号内容
    anchors += len(re.findall(r'\d{4}年|\d{1,2}月|\d{1,2}日', current_text))  # 日期
    anchors += person_name_count                                                # 学者人名 = 具体锚点
    # 具体标记词
    concrete_markers = ["比如", "例如", "想象", "曾经", "记得", "有一次", "昨天",
                        "小时候", "几年前", "那天", "故事", "案例", "场景"]
    for marker in concrete_markers:
        if marker in current_text:
            anchors += 1
    total_tokens = len(tokens)
    signals.anchor_density = anchors / total_tokens if total_tokens > 0 else 0.0

    # 3. 抽象词占比：IDF > 4.0 的词（已排除人名）
    abstract_count = sum(1 for v in idf_values if v > 4.0)
    signals.abstraction_ratio = abstract_count / len(idf_values) if idf_values else 0.0


# ---------------------------------------------------------------------------
# 学者人名表（具体锚点，不参与 IDF 计算）
# ---------------------------------------------------------------------------

_PERSON_NAMES: set[str] = {
    # 西方哲学
    "苏格拉底", "柏拉图", "亚里士多德", "笛卡尔", "斯宾诺莎", "莱布尼茨",
    "休谟", "洛克", "康德", "黑格尔", "马克思", "尼采", "叔本华",
    "海德格尔", "萨特", "加缪", "维特根斯坦", "胡塞尔", "克尔凯郭尔",
    "雅斯贝尔斯", "伽达默尔", "德里达", "福柯", "鲍德里亚", "哈贝马斯",
    "布迪厄", "阿伦特", "齐泽克", "巴特勒",
    # 东方哲学/思想
    "孔子", "老子", "庄子", "孟子", "荀子", "墨子", "韩非子", "孙子",
    "王阳明", "朱熹", "慧能", "释迦牟尼",
    # 科学家
    "爱因斯坦", "牛顿", "达尔文", "薛定谔", "海森堡", "玻尔", "费曼",
    "霍金", "图灵", "冯诺依曼", "哥德尔", "香农",
    # 心理学
    "弗洛伊德", "荣格", "阿德勒", "皮亚杰", "维果茨基", "斯金纳",
    "马斯洛", "罗杰斯", "卡尼曼", "塞利格曼",
    # 社会学/传播学
    "麦克卢汉", "波兹曼", "芒福德", "鲍曼", "吉登斯", "贝克",
}


# ---------------------------------------------------------------------------
# 成语表（4 字词但降低阅读门槛，IDF 强制压低）
# ---------------------------------------------------------------------------

_IDIOMS: set[str] = {
    "豁然开朗", "理所当然", "顺其自然", "不言而喻", "显而易见",
    "众所周知", "毫无疑问", "毋庸置疑", "一目了然", "迎刃而解",
    "相辅相成", "水到渠成", "自然而然", "循序渐进", "潜移默化",
    "触类旁通", "举一反三", "融会贯通", "深入浅出", "通俗易懂",
    "恰如其分", "恰到好处", "画龙点睛", "锦上添花", "雪中送炭",
    "因噎废食", "削足适履", "南辕北辙", "缘木求鱼", "刻舟求剑",
    "守株待兔", "掩耳盗铃", "亡羊补牢", "未雨绸缪", "居安思危",
    "物极必反", "否极泰来", "塞翁失马", "因祸得福", "乐极生悲",
    "殊途同归", "异曲同工", "不谋而合", "不约而同", "如出一辙",
    "见仁见智", "众说纷纭", "莫衷一是", "各抒己见", "百家争鸣",
    "求同存异", "兼收并蓄", "博采众长", "集思广益", "群策群力",
}


# ---------------------------------------------------------------------------
# 速度测量
# ---------------------------------------------------------------------------

def _measure_speed(
    signals: RawSignals,
    current_text: str,
    concept_registry: dict,
    prev_token_dist: dict[str, float] | None,
) -> dict[str, float]:
    """测量代谢率：概念周转 + KL 散度 + 句长。"""
    tokens = _tokenize(current_text)

    # 1. 概念代谢率
    if concept_registry:
        active_concepts = [c for c in concept_registry.values()
                          if hasattr(c, 'status') and c.status == "active"]
        if active_concepts:
            # 最近一轮新引入的概念占比
            referenced = sum(1 for c in active_concepts
                           if hasattr(c, 'name') and c.name in current_text)
            signals.concept_turnover = 1.0 - (referenced / len(active_concepts)) if active_concepts else 0.0

    # 2. KL 散度
    current_dist = _build_token_dist(tokens)
    if prev_token_dist:
        signals.kl_divergence = _kl_divergence(current_dist, prev_token_dist)

    # 3. 平均句长
    sentences = re.split(r'[。！？.!?\n]', current_text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if sentences:
        signals.avg_sentence_length = sum(len(s) for s in sentences) / len(sentences)

    return current_dist


def _build_token_dist(tokens: list[str]) -> dict[str, float]:
    """构建归一化的词频分布。"""
    counter = Counter(tokens)
    total = sum(counter.values())
    if total == 0:
        return {}
    return {word: count / total for word, count in counter.items()}


def _kl_divergence(p: dict[str, float], q: dict[str, float], smoothing: float = 1e-10) -> float:
    """计算 KL(P || Q)，带 Laplace 平滑。"""
    all_keys = set(p.keys()) | set(q.keys())
    if not all_keys:
        return 0.0

    kl = 0.0
    for key in all_keys:
        p_val = p.get(key, smoothing)
        q_val = q.get(key, smoothing)
        if p_val > 0:
            kl += p_val * math.log(p_val / q_val)
    return max(0.0, kl)


# ---------------------------------------------------------------------------
# 阵型测量
# ---------------------------------------------------------------------------

# 引用检测模式
_REFERENCE_PATTERNS_ZH = [
    # ---- 明确指名道姓/直接引用 ----
    r'你说的', r'你的意思是', r'正如.{1,8}(?:提到|说|指出|讲|认为)',
    r'关于.{1,8}(?:的观点|的看法|的发言|提到的)',
    r'(?:回应|针对|回复).{1,8}(?:的话|的问题|的观点)',
    r'.{1,8}刚才(?:提到|说|指出|讲|的意思)',

    # ---- 上下文无名指代（常用于多人交替发言） ----
    r'(?:刚才|前面|上一位).{0,6}(?:提到|说|指出|讲)',
    r'顺着.{1,8}(?:的话|的思路|的逻辑)接着说',
    r'沿着.{1,8}(?:的思路|的脉络)',
    r'接着.{1,8}(?:的话|的观点)',

    # ---- 总结与确认式引用 ----
    r'如果我没理解错(?:的话)?，.{1,6}的意思是',
    r'.{1,8}给我的启发是',
    r'借用.{1,8}的话',
    r'同意.{1,8}的',  # 既是引用也是赞同
]

# 反驳检测模式
_OPPOSITION_MARKERS = [
    # ---- 强反驳/直接否定 ----
    "但是", "然而", "不过", "恰恰相反", "我不认为", "问题是",
    "不对", "并非如此", "并不完全", "不见得", "其实不是", "恰恰是",
    "质疑", "反驳", "反对", "不敢苟同", "站不住脚", "有失偏颇",

    # ---- 弱反驳/委婉表达/视角切换（非常高频） ----
    "我倒觉得", "有没有一种可能", "换个角度", "另一方面",
    "可能还需要考虑", "值得商榷", "有待商榷", "未必", "不一定",
    "这只是其中一面", "话虽如此", "我不完全认同", "保留意见",
    "忽略了", "局限性在于", "过于绝对",

    # ---- 让步后反驳（"先同意后反对"模式） ----
    "就算", "退一步讲", "诚然", "虽然",

    # ---- 英文/中英夹杂高频词 ----
    "but", "however", "yet", "on the contrary", "I disagree",
    "not necessarily", "make sense but", "on the other hand",
]

# 赞同检测模式
_AGREEMENT_MARKERS = [
    # ---- 直接/情绪化赞同 ----
    "确实", "同意", "没错", "有道理", "说得对", "赞同", "认可",
    "完全同意", "非常赞同", "双手赞成", "没毛病", "太对了",
    "就是这个理", "英雄所见略同", "确实如此", "毋庸置疑",
    "深有同感", "所言极是", "深以为然", "一针见血", "说到点子上了",
    "+1", "绝了", "顶",

    # ---- 建设性赞同 / 延展补充（高认知能量信号） ----
    "补充", "不仅如此", "更重要的是", "除此之外",
    "延展一下", "进一步说", "顺着这个思路", "我很受启发",
    "醍醐灌顶", "学到了",

    # ---- 英文/中英夹杂高频词 ----
    "I agree", "exactly", "good point", "indeed",
    "totally", "100%", "make sense", "spot on",
]


def _measure_formation(
    signals: RawSignals,
    current_round_msgs: list,
    participant_ids: list[str],
) -> None:
    """测量阵型：引用密度 + 立场检测 + Gini 系数 + 实体变量。"""
    if not current_round_msgs:
        return

    total_msgs = len(current_round_msgs)
    ref_count = 0
    opposition_count = 0
    agreement_count = 0
    speech_lengths: list[int] = []
    speaker_lengths: dict[str, int] = {}  # agent_id → 本轮发言总字数
    last_speaker_id = ""

    for msg in current_round_msgs:
        if not hasattr(msg, 'content'):
            continue
        text = msg.content
        msg_len = len(text)
        speech_lengths.append(msg_len)

        # 统计每个发言者的字数
        aid = getattr(msg, 'agent_id', '')
        if aid:
            speaker_lengths[aid] = speaker_lengths.get(aid, 0) + msg_len
            last_speaker_id = aid

        # 引用检测
        for pattern in _REFERENCE_PATTERNS_ZH:
            if re.search(pattern, text):
                ref_count += 1
                break

        # 反驳检测
        for marker in _OPPOSITION_MARKERS:
            if marker in text:
                opposition_count += 1
                break

        # 赞同检测
        for marker in _AGREEMENT_MARKERS:
            if marker in text:
                agreement_count += 1
                break

    signals.reference_density = ref_count / total_msgs if total_msgs > 0 else 0.0
    signals.stance_opposition = opposition_count / total_msgs if total_msgs > 0 else 0.0
    signals.stance_agreement = agreement_count / total_msgs if total_msgs > 0 else 0.0
    signals.speaker_count = total_msgs

    # Gini 系数
    signals.gini_coefficient = _gini(speech_lengths)

    # 实体变量
    # 发言最多的人（字数最多）
    if speaker_lengths:
        dominant_id = max(speaker_lengths, key=speaker_lengths.get)
        signals.dominant_speaker = dominant_id
    # 最沉默的人（本轮未发言）
    spoke_ids = set(speaker_lengths.keys())
    silent_ids = [pid for pid in participant_ids if pid not in spoke_ids]
    if silent_ids:
        signals.silent_speaker = silent_ids[0]
    # 最后发言的人
    signals.last_speaker = last_speaker_id


def _gini(values: list[int]) -> float:
    """计算 Gini 系数（衡量不平等程度，0=完全平等, 1=完全不平等）。"""
    if not values or len(values) < 2:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    total = sum(sorted_vals)
    if total == 0:
        return 0.0
    cumulative = 0.0
    gini_sum = 0.0
    for i, val in enumerate(sorted_vals):
        cumulative += val
        gini_sum += (2 * (i + 1) - n - 1) * val
    return gini_sum / (n * total)

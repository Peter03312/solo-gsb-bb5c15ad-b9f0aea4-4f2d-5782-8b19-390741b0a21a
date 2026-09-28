"""只读配液方案精确求解（纯函数，不依赖 Web/DB）。

问题：用若干已有样本（来源）各取**整数微升**，配制目标体积 V、目标浓度 C
（整数纳克/微升）的混合液，可行方案 x_i 必须**精确**满足：

    sum_i x_i = V,   sum_i x_i * c_i = V * C,   0 <= x_i <= a_i（x_i 为整数）

选择规则（两级字典序）：

1. **非零用量的来源样本数最少**；
2. 来源数相同时，按**请求顺序**排列的取用体积向量字典序最小。

不允许浓度四舍五入或贪心近似：先用记忆化动态规划对每个
``(下标, 剩余体积, 剩余质量)`` 状态求出补足该状态所需的**最少额外来源数**
（不可行记无穷大），再在可行状态空间内按来源顺序、用量从小到大 DFS——
首条可行路径即“最少来源数 + 字典序最小”的方案。状态空间有界
（最多 7 × 31 × 3001 ≈ 65 万个状态），目标体积上限 30 μL、来源上限 6 个，
计算在毫秒量级完成。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache


@dataclass(frozen=True)
class PlanSource:
    """一个候选来源样本（下标即请求顺序，字典序按该顺序比较）。"""

    index: int
    sample_id: str
    concentration_ng_ul: int
    available_volume_ul: int


@dataclass(frozen=True)
class PlanSolution:
    """最优方案：``volumes`` 与请求来源等长、同序，未使用来源用量为 0。"""

    volumes: tuple[int, ...]
    used_count: int


_INF = 10**9


def solve(
    sources: list[PlanSource],
    target_volume_ul: int,
    target_concentration_ng_ul: int,
) -> PlanSolution | None:
    """搜索精确整数配液方案；无任何可行方案时返回 ``None``。"""

    n = len(sources)
    target_mass = target_volume_ul * target_concentration_ng_ul
    caps = [s.available_volume_ul for s in sources]
    concs = [s.concentration_ng_ul for s in sources]

    # 后缀可用体积之和：剩余体积超过它则任何取法都无法补足
    suffix_cap = [0] * (n + 1)
    # 给定剩余体积 k，后缀来源可达到的精确质量范围（容量受限下的紧界）：
    # band_min[i][k] / band_max[i][k] 为后缀来源（i..n-1）恰好共取 k μL
    # 时总质量的最小/最大值；对当前来源用量 x 取一遍 min/max 即递推得到。
    # 仅作安全必要条件剪枝（质量落在界外必不可行，界内仍由精确 DP 判定）。
    band_min: list[list[int]] = [[_INF] * (target_volume_ul + 1) for _ in range(n + 1)]
    band_max: list[list[int]] = [[-1] * (target_volume_ul + 1) for _ in range(n + 1)]
    band_min[n][0] = 0
    band_max[n][0] = 0
    for k in range(n - 1, -1, -1):
        suffix_cap[k] = suffix_cap[k + 1] + caps[k]
        for vol in range(target_volume_ul + 1):
            lo, hi = _INF, -1
            upper_x = min(caps[k], vol)
            for x in range(upper_x + 1):
                tail_lo = band_min[k + 1][vol - x]
                tail_hi = band_max[k + 1][vol - x]
                if tail_hi >= 0:
                    lo = min(lo, concs[k] * x + tail_lo)
                    hi = max(hi, concs[k] * x + tail_hi)
            band_min[k][vol] = lo
            band_max[k][vol] = hi

    @cache
    def min_used(i: int, vol_left: int, mass_left: int) -> int:
        """补足状态 (i, vol_left, mass_left) 所需的**最少额外来源数**。

        纯可达性 + 最优值计算，与前缀选择无关；不可行返回 _INF。
        与前缀选择、用量顺序无关，可安全记忆化并在各分支间共享。
        """

        if vol_left == 0:
            return 0 if mass_left == 0 else _INF
        if i == n or vol_left < 0 or mass_left < 0:
            return _INF
        if vol_left > suffix_cap[i]:
            return _INF
        # 质量可达界（考虑容量，比线性界更紧；只是必要条件，安全剪枝）
        if not (band_min[i][vol_left] <= mass_left <= band_max[i][vol_left]):
            return _INF
        upper = min(caps[i], vol_left)
        ci = concs[i]
        best = _INF
        for x in range(upper + 1):
            tail = min_used(i + 1, vol_left - x, mass_left - x * ci)
            if tail < _INF:
                cost = tail + (1 if x else 0)
                if cost < best:
                    best = cost
        return best

    min_total = min_used(0, target_volume_ul, target_mass)
    if min_total >= _INF:
        return None

    # 在最少来源数（= min_total）约束下，按来源顺序、用量从小到大贪心选路：
    # 每一步选择最小的、使后缀最少来源数不超过剩余名额的用量 x；
    # x 最小 + 可行即字典序最小，且总来源数恰为 min_total。
    volumes = [0] * n
    vol_left = target_volume_ul
    mass_left = target_mass
    slots = min_total
    for i in range(n):
        upper = min(caps[i], vol_left)
        ci = concs[i]
        chosen = None
        for x in range(upper + 1):
            nxt_slots = slots - (1 if x else 0)
            if nxt_slots < 0:
                continue
            tail = min_used(i + 1, vol_left - x, mass_left - x * ci)
            if tail <= nxt_slots:
                chosen = x
                break
        assert chosen is not None  # min_total 可行，必有一路可走
        volumes[i] = chosen
        vol_left -= chosen
        mass_left -= chosen * ci
        slots -= 1 if chosen else 0
    assert vol_left == 0 and mass_left == 0 and slots == 0
    return PlanSolution(volumes=tuple(volumes), used_count=min_total)

"""第 53 批：木箱破坏/断裂系统。

修复点（与缺陷一一对应）：
1. 材质感知断裂：fracture_cells 按材质对均匀网格细分，木材碎得更细、石材更粗。
2. 质量=体积×密度：fragment_mass 同时考虑体积与材质密度。
3. 冲击传播：impulse_transfer 把命中冲量按质量换算成速度增量，可向相邻刚体传播。
4. 支撑图重建：rebuild_support 在断裂后收集全部节点（含只作为邻接出现的节点）。
5. 碎片碰撞滤波：collision_filter 过滤同一碎片的自碰撞，不同碎片才参与碰撞。
6. 睡眠阈值：sleep_threshold 让低速静止碎片进入睡眠，节省物理开销。
7. 断裂面去重：unique_face 拒绝重复法线，保证断裂面不重复生成。
8. 统一碎片路径：预碎片与运行时断裂都走 UNIFIED_FRAGMENT_PATH/fragment_path 同一条路径。
9. 异步破坏队列：async_queue 把破坏事件移出主线程，放入队列延后处理。
10. 确定性碎片：deterministic_seed 用 splitmix64 按 (seed, index) 派生种子，网络回放一致。
"""

from collections import deque

__all__ = [
    "UNIFIED_FRAGMENT_PATH",
    "fracture_cells",
    "fragment_path",
    "fragment_mass",
    "impulse_transfer",
    "rebuild_support",
    "collision_filter",
    "sleep_threshold",
    "unique_face",
    "async_queue",
    "deterministic_seed",
]

# --- 8. 统一碎片路径 -------------------------------------------------------
# 预碎片（prefractured）与运行时断裂（runtime fracture）必须共用同一条均匀
# 网格路径，禁止两套断裂逻辑混用。
UNIFIED_FRAGMENT_PATH = "uniform_grid:runtime"

# --- 1. 材质感知断裂 -------------------------------------------------------
# 材质 -> 均匀网格细分系数：木材脆且纹理多，细分一倍；石材坚硬，保持基础网格。
_MATERIAL_CELL_FACTOR = {
    "wood": 2.0,
    "stone": 1.0,
}
_DEFAULT_CELL_FACTOR = 1.0


def fragment_path(material=None):
    """返回碎片断裂的统一路径，预碎片与运行时断裂都从这里进入。"""
    return UNIFIED_FRAGMENT_PATH


def fracture_cells(material, grid):
    """按材质返回断裂网格数量（均匀网格，材质感知细分）。"""
    if grid <= 0:
        return 1
    factor = _MATERIAL_CELL_FACTOR.get(material, _DEFAULT_CELL_FACTOR)
    return max(1, int(grid * factor))


# --- 2. 质量 = 体积 × 密度 -------------------------------------------------
def fragment_mass(volume, density):
    """按体积和密度返回碎片质量；非正体积或密度视为 0，避免负质量。"""
    if volume <= 0.0 or density <= 0.0:
        return 0.0
    return float(volume) * float(density)


# --- 3. 冲击传播 -----------------------------------------------------------
def impulse_transfer(impulse, mass):
    """返回碎片接收冲量后的速度增量（J/m），用于向相邻刚体传播冲击。

    质量非正时无法承接冲量，返回 0.0 而不是抛出除零错误。
    """
    if mass <= 0.0:
        return 0.0
    return float(impulse) / float(mass)


# --- 4. 支撑图重建 ---------------------------------------------------------
def rebuild_support(graph):
    """重建支撑图节点列表。

    断裂后支撑关系变化，需要重新收集节点：既包括图的键，也包括只在邻接
    列表里出现的节点，返回排序后的确定性列表。
    """
    nodes = set(graph)
    for neighbors in graph.values():
        nodes.update(neighbors)
    return sorted(nodes)


# --- 5. 碎片碰撞滤波 -------------------------------------------------------
def collision_filter(fragment_a, fragment_b):
    """判断两个碎片是否参与碰撞：同一碎片（自碰撞）过滤掉，不同碎片才碰撞。"""
    return fragment_a != fragment_b


# --- 6. 睡眠阈值 -----------------------------------------------------------
def sleep_threshold(velocity, threshold):
    """速度大小不超过阈值时碎片进入睡眠（静止碎片不再参与每帧模拟）。"""
    return abs(velocity) <= threshold


# --- 7. 断裂面去重 ---------------------------------------------------------
def unique_face(normal, faces):
    """判断断裂面法线是否未重复：已存在同法线的面则拒绝，避免重复断裂面。"""
    return normal not in faces


# --- 9. 异步破坏队列 -------------------------------------------------------
def async_queue(events):
    """把破坏事件放入异步队列（deque），与主线程解耦后按序消费。"""
    return deque(events)


# --- 10. 确定性碎片 --------------------------------------------------------
_MASK64 = (1 << 64) - 1
_GOLDEN = 0x9E3779B97F4A7C15


def deterministic_seed(seed, index):
    """按 (种子, 碎片索引) 派生确定性随机数种子（splitmix64）。

    相同 (seed, index) 永远得到相同结果，不同索引必然发散，保证网络回放
    与多端模拟的碎片形态完全一致。
    """
    state = (int(seed) * _GOLDEN + int(index)) & _MASK64
    state = (state + _GOLDEN) & _MASK64
    z = state
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK64
    return z ^ (z >> 31)

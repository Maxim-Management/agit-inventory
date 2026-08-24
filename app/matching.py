"""
Подбор оптимальных пар ротор/статор по зазору (OD ротора / ID статора).

Целевой зазор — диапазон [GAP_MIN, GAP_MAX] мм (по умолчанию 0.2-0.3),
оптимум — середина диапазона. Задача — классическая задача о назначениях
(bipartite assignment): нужно сопоставить роторы статорам так, чтобы:
  1) как можно больше пар получили зазор в допустимом диапазоне;
  2) среди допустимых пар суммарное отклонение от идеального зазора было
     минимальным.

Реализован венгерский алгоритм (Kuhn-Munkres) на чистом Python без внешних
зависимостей (scipy недоступен в целевом окружении), т.к. количество
единиц в обороте (десятки) делает O(n^3) более чем достаточным.
"""
from typing import List, Dict, Optional

GAP_MIN = 0.2
GAP_MAX = 0.3
GAP_TARGET = (GAP_MIN + GAP_MAX) / 2  # 0.25
INVALID_COST = 10 ** 7


def _hungarian(cost: List[List[float]]) -> List[int]:
    """Минимизация суммарной стоимости назначения для квадратной матрицы cost.
    Возвращает список: assignment[i] = j (индекс столбца, назначенного строке i).
    Реализация O(n^3) (алгоритм Куна с потенциалами / venгерский алгоритм)."""
    n = len(cost)
    INF = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (n + 1)
    p = [0] * (n + 1)   # p[j] = строка, назначенная столбцу j (1-indexed)
    way = [0] * (n + 1)

    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = INF
            j1 = -1
            for j in range(1, n + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j] = cur
                        way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]
                        j1 = j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1

    assignment = [-1] * n
    for j in range(1, n + 1):
        if p[j] != 0:
            assignment[p[j] - 1] = j - 1
    return assignment


def suggest_pairs(rotors: List[Dict], stators: List[Dict],
                   gap_min: float = GAP_MIN, gap_max: float = GAP_MAX) -> List[Dict]:
    """rotors/stators — списки словарей с ключами как минимум 'id', 'od_mm' /
    'id_mm', 'serial_number'. Возвращает список найденных пар (только валидных,
    т.е. с зазором в допустимом диапазоне), отсортированный по качеству
    (близости к идеальному зазору)."""
    n_r = len(rotors)
    n_s = len(stators)
    if n_r == 0 or n_s == 0:
        return []

    target = (gap_min + gap_max) / 2
    n = max(n_r, n_s)
    cost = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i < n_r and j < n_s:
                rotor = rotors[i]
                stator = stators[j]
                od = rotor.get("od_mm")
                idm = stator.get("id_mm")
                if od is None or idm is None:
                    cost[i][j] = INVALID_COST
                    continue
                gap = float(idm) - float(od)
                if gap_min <= gap <= gap_max:
                    cost[i][j] = abs(gap - target) * 1000.0
                else:
                    cost[i][j] = INVALID_COST
            else:
                # фиктивная строка/столбец — "не назначать", стоимость 0
                cost[i][j] = 0.0

    assignment = _hungarian(cost)

    results = []
    for i, j in enumerate(assignment):
        if i >= n_r or j < 0 or j >= n_s:
            continue
        rotor = rotors[i]
        stator = stators[j]
        od = rotor.get("od_mm")
        idm = stator.get("id_mm")
        if od is None or idm is None:
            continue
        gap = round(float(idm) - float(od), 4)
        if gap_min <= gap <= gap_max:
            results.append({
                "rotor": rotor,
                "stator": stator,
                "gap_mm": gap,
                "deviation": round(abs(gap - target), 4),
                "quality": _quality_label(gap, gap_min, gap_max, target),
            })

    results.sort(key=lambda r: r["deviation"])
    return results


def _quality_label(gap: float, gap_min: float, gap_max: float, target: float) -> str:
    dev = abs(gap - target)
    span = (gap_max - gap_min) / 2
    if dev <= span * 0.25:
        return "оптимально"
    if dev <= span * 0.6:
        return "хорошо"
    return "приемлемо"


def evaluate_pair(od_mm: Optional[float], id_mm: Optional[float],
                   gap_min: float = GAP_MIN, gap_max: float = GAP_MAX) -> Dict:
    """Оценка одной произвольной пары (для ручного подбора)."""
    if od_mm is None or id_mm is None:
        return {"gap_mm": None, "valid": False, "quality": None}
    gap = round(float(id_mm) - float(od_mm), 4)
    target = (gap_min + gap_max) / 2
    valid = gap_min <= gap <= gap_max
    return {
        "gap_mm": gap,
        "valid": valid,
        "quality": _quality_label(gap, gap_min, gap_max, target) if valid else "вне диапазона",
    }

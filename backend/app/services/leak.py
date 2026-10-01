"""泄漏排查业务规则：状态流转、字段校验与筛选口径都收在这里。

状态以既有台账字段「排查状态」为准（status / pending / abnormal 只是给概览用的派生值），
保证动作结果直接落到盘点清单同一份字段上，列表、明细、导出、概览口径一致。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "leak"
LEDGER_STATUS = "排查状态"
LEDGER_FIELDS = ["排查编号", "排查区域", "排查方式", "疑似点位", "检出数量", "排查人员", "排查日期", LEDGER_STATUS]
REQUIRED_FIELDS = ["排查编号", "排查区域", "排查方式"]
STATUS_ORDER = ["待排查", "排查中", "已处置", "已排除"]
DONE_STATUSES = {"已处置", "已排除"}
ACTION_RULES = {"安排排查": "排查中", "确认处置": "已处置", "排除嫌疑": "已排除"}
NEGATIVE_ACTIONS = []
# 只允许向前流转：待排查→排查中；排查中→已处置 / 已排除。终态之间互不能改。
ALLOWED_TRANSITIONS = {
    "待排查": {"安排排查"},
    "排查中": {"确认处置", "排除嫌疑"},
    "已处置": set(),
    "已排除": set(),
}


def _status_of(entry: dict[str, Any]) -> str:
    """读取台账状态；异常老数据回退到派生字段，保证脏数据也能被正确归类。"""
    status = str(entry.get(LEDGER_STATUS) or "").strip()
    if status in STATUS_ORDER:
        return status
    fallback = str(entry.get("status") or "").strip()
    return fallback if fallback in STATUS_ORDER else STATUS_ORDER[0]


def _is_pending(entry: dict[str, Any]) -> bool:
    return _status_of(entry) not in DONE_STATUSES


def _apply_status(entry: dict[str, Any], status: str, *, abnormal: bool) -> None:
    """台账字段与派生字段一并落库，避免两处口径漂移。"""
    entry[LEDGER_STATUS] = status
    entry["status"] = status
    entry["pending"] = status not in DONE_STATUSES
    entry["abnormal"] = abnormal


class LeakService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        scope: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("排查编号", ""))]
        if status:
            rows = [row for row in rows if _status_of(row) == status]
        # scope=pending 即「待处理范围」：已处置与已排除同时消失。
        if scope == "pending":
            rows = [row for row in rows if _is_pending(row)]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        # 详情读出来的也必须是同一份状态，不能让台账字段与派生字段继续错位。
        _apply_status(entry, _status_of(entry), abnormal=bool(entry.get("abnormal")))
        return entry

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        # 沿用既有台账字段，不另起一套；未填字段保留为 None，由列表展示为「—」。
        for field in LEDGER_FIELDS:
            entry[field] = values.get(field)
        _apply_status(entry, STATUS_ORDER[0], abnormal=False)
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"排查记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于泄漏排查可执行范围"
        current = _status_of(entry)
        target = ACTION_RULES[action]
        if action not in ALLOWED_TRANSITIONS.get(current, set()):
            if current in DONE_STATUSES:
                # 终态记录重复点任何动作都不允许改回去；同动作重复提交则当作已生效的幂等重放。
                if current == target:
                    return entry, f"排查记录已为「{current}」，无需重复{action}"
                return None, f"排查记录已为「{current}」状态，不能再{action}，处置结果不会被覆盖"
            return None, f"当前状态「{current}」不允许直接{action}，请先按流程安排排查"
        _apply_status(entry, target, abnormal=action in NEGATIVE_ACTIONS)
        return entry, f"排查记录已{action}"

    def stats(self) -> dict[str, int]:
        """列表页统计口径：与待处理范围、检出数量同源于台账数据。"""
        rows = store.rows(MODULE)
        result = {status: 0 for status in STATUS_ORDER}
        detected = 0
        for row in rows:
            result[_status_of(row)] += 1
            try:
                detected += int(float(str(row.get("检出数量") or 0)))
            except ValueError:
                continue
        return {
            "待排查": result["待排查"],
            "排查中": result["排查中"],
            "已处置": result["已处置"],
            "已排除": result["已排除"],
            "待处理": result["待排查"] + result["排查中"],
            "本月检出点": detected,
        }

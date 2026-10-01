"""泄漏排查业务规则：状态流转、字段校验与筛选口径都收在这里。

设计要点：
- 台账字段沿用既有清单字段（排查编号/排查区域/排查方式/疑似点位/检出数量/
  排查人员/排查日期/排查状态），不再额外维护一套平行的业务字段。
- 列表、详情、盘点清单（导出）读的是同一张台账，因此处置结果在三处一致。
- “已处置/已排除”是终态：离开待处理范围，且不允许再被任何动作改回去。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "leak"
# 台账既有字段，顺序即列表/详情/盘点清单的列顺序。
LEDGER_FIELDS = [
    "排查编号",
    "排查区域",
    "排查方式",
    "疑似点位",
    "检出数量",
    "排查人员",
    "排查日期",
    "排查状态",
]
# 登记时必须提供的台账字段。
REQUIRED_FIELDS = ["排查编号", "排查区域", "排查方式"]
# 内部状态序列与既有台账里“排查状态”的取值保持同一套口径。
STATUS_ORDER = ["待排查", "排查中", "已处置", "已排除"]
ACTION_RULES = {"安排排查": "排查中", "确认处置": "已处置", "排除嫌疑": "已排除"}
# 状态字段同时是内部 status 与台账“排查状态”列的数据源。
STATUS_FIELD = "排查状态"
# 离开待处理范围的终态：已处置与已排除都不再算待办。
DONE_STATUSES = {"已处置", "已排除"}


def _is_done(entry: dict[str, Any]) -> bool:
    return entry.get(STATUS_FIELD) in DONE_STATUSES


class LeakService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("排查编号", ""))]
        if status:
            # 筛选用的是台账“排查状态”，与列表展示同一字段，不会再出现两套口径。
            rows = [row for row in rows if row.get(STATUS_FIELD) == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        # 沿用既有台账字段；未填的可选项落为空串，列表统一显示“—”。
        for field in LEDGER_FIELDS:
            entry[field] = str(values.get(field) or "").strip() if field != STATUS_FIELD else STATUS_ORDER[0]
        # 内部汇总标记与台账状态严格同源。
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"排查记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于泄漏排查可执行范围"

        current = str(entry.get(STATUS_FIELD) or entry.get("status") or STATUS_ORDER[0])
        target = ACTION_RULES[action]

        # 断线重试/重复点击：状态已是该动作的目标，按幂等成功返回同一份结果，
        # 不会因为重发而报错或改写任何字段。
        if current == target:
            return entry, f"排查记录已是「{target}」，无需重复{action}"

        # 终态保护：已处置/已排除的记录不能再被改回去。
        if current in DONE_STATUSES:
            return None, (
                f"排查记录当前为「{current}」（终态），不能再执行「{action}」，"
                "如需改判请重新登记"
            )

        current_index = STATUS_ORDER.index(current) if current in STATUS_ORDER else -1
        target_index = STATUS_ORDER.index(target)
        if target_index <= current_index:
            return None, f"当前状态为「{current}」，不能回退执行「{action}」"

        # 写同一份结果：台账“排查状态”、内部 status、待办标记一起更新，
        # 这样列表、详情、概览待办、盘点清单看到的都是同一份状态。
        entry[STATUS_FIELD] = target
        entry["status"] = target
        entry["pending"] = target not in DONE_STATUSES
        return entry, f"排查记录已{action}，当前状态：{target}"

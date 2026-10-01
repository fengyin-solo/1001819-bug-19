"""泄漏排查接口：维护排查记录，覆盖安排排查、确认处置、排除嫌疑等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.leak import (
    ACTION_RULES,
    LEDGER_FIELDS,
    STATUS_ORDER,
    LeakService,
)

router = APIRouter(prefix="/api/leak", tags=["泄漏排查"])

service = LeakService()

LIST_FIELDS = LEDGER_FIELDS
STATUSES = STATUS_ORDER


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按排查编号检索"),
    status: str | None = Query(default=None, description="待排查、排查中、已处置、已排除"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按排查编号与状态过滤泄漏排查列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if status and status not in STATUSES:
        # 非法筛选值要说明原因，而不是静默返回空列表。
        raise HTTPException(
            status_code=400,
            detail=f"排查状态「{status}」不支持，可选：{'、'.join(STATUSES)}",
        )
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def stats() -> dict[str, Any]:
    """泄漏排查自身的统计口径：各状态条数与待办数，与概览待办同源。"""
    rows = service.list_entries(page=1, size=10000)[0]
    by_status = {name: 0 for name in STATUSES}
    for row in rows:
        name = str(row.get("排查状态") or "")
        if name in by_status:
            by_status[name] += 1
    return {
        "total": len(rows),
        "pending": by_status["待排查"] + by_status["排查中"],
        "by_status": by_status,
    }


@router.get("/export")
def export_entries(
    keyword: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """导出泄漏盘点清单：与列表同一数据源、同一筛选口径，动作结果即时反映。"""
    if status and status not in STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"排查状态「{status}」不支持，可选：{'、'.join(STATUSES)}",
        )
    items, total = service.list_entries(keyword=keyword, status=status, page=1, size=10000)
    return {"module": "leak", "total": total, "fields": LIST_FIELDS, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条排查记录明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"排查记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条排查记录，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="排查记录已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条排查记录执行安排排查、确认处置、排除嫌疑。

    终态（已处置/已排除）不可改回；重复提交同一动作为幂等成功。
    业务不通过时 ok=False 且 message 说明原因，前端原样展示。
    """
    action = str(payload.values.get("action") or "").strip()
    if not action:
        return ActionResult(ok=False, message="缺少 action，未执行任何排查动作")
    if action not in ACTION_RULES:
        return ActionResult(
            ok=False,
            message=f"动作「{action}」不属于泄漏排查可执行范围，可选：{'、'.join(ACTION_RULES)}",
        )
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)

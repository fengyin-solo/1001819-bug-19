"""泄漏排查接口：维护排查记录，覆盖安排排查、确认处置、排除嫌疑等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.leak import ACTION_RULES, STATUS_ORDER, LeakService

router = APIRouter(prefix="/api/leak", tags=["泄漏排查"])

service = LeakService()

LIST_FIELDS = ["排查编号", "排查区域", "排查方式", "疑似点位", "检出数量", "排查人员", "排查日期", "排查状态"]
STATUSES = STATUS_ORDER


@router.get("/stats")
def entry_stats() -> dict[str, int]:
    """泄漏排查台账统计：与列表、概览同一份口径，避免条数对不上。"""
    return service.stats()


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出泄漏排查清单：返回全量台账数据，动作结果已直接反映在「排查状态」列上。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "leak", "total": total, "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按排查编号检索"),
    status: str | None = Query(default=None, description="待排查、排查中、已处置、已排除"),
    scope: str | None = Query(default=None, description="pending=只看待处理（不含已处置、已排除）"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按排查编号与状态过滤泄漏排查列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if status and status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"排查状态「{status}」不合法，可选：{'、'.join(STATUSES)}")
    if scope and scope not in {"pending", "all"}:
        raise HTTPException(status_code=400, detail="范围参数 scope 只支持 pending 或 all")
    items, total = service.list_entries(keyword=keyword, status=status, scope=scope, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


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

    终态记录的重复提交按幂等处理（同一动作重放返回成功且不改结果），
    试图把已处置 / 已排除改回去则拒绝并说明原因，保证断线重试可以放心重发。
    """
    action = str(payload.values.get("action") or "").strip()
    if not action:
        return ActionResult(ok=False, message="缺少动作参数 action，可选：" + "、".join(ACTION_RULES))
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)

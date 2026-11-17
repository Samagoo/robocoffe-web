"""Order persistence and retrieval (Phase 2). Dispatch arrives in Phase 4."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Order, OrderEvent
from ..order_config import OrderConfig, get_order_config
from ..schemas import OrderCreate, OrderOut

router = APIRouter(tags=["orders"])


@router.get("/catalog", response_model=OrderConfig)
def catalog():
    """Products, tables and (provisional) statuses, so the frontend never hard-codes them."""
    return get_order_config()


@router.post("/orders", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_order(body: OrderCreate, db: Session = Depends(get_db)):
    cfg = get_order_config()
    table = cfg.table(body.table_number)
    order = Order(
        product_code=body.product_code,
        table_number=table.number,
        distance_m=table.distance_m,       # snapshot: re-measuring later won't rewrite history
        customer_name=body.customer_name,
        notes=body.notes,
        status=cfg.initial_status,
    )
    # Same transaction => created_at and the creation event share the exact server timestamp
    order.events.append(OrderEvent(from_status=None, to_status=cfg.initial_status,
                                   cause="created", source="customer"))
    db.add(order)
    db.commit()
    db.refresh(order)                      # load server-generated folio and timestamps
    return order


@router.get("/orders", response_model=list[OrderOut])
def list_orders(
    status_: str | None = Query(default=None, alias="status", description="Filter by status"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Newest first."""
    stmt = select(Order).order_by(Order.created_at.desc(), Order.id.desc()).limit(limit)
    if status_ is not None:
        if status_ not in get_order_config().statuses:
            raise HTTPException(422, f"unknown status {status_!r}")
        stmt = stmt.where(Order.status == status_)
    return db.scalars(stmt).all()

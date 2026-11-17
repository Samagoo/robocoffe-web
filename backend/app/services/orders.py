"""Order state changes shared by the REST API and the robot link.

Every status change writes an order_events row (the audit trail of the order state machine).
"""
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import Order, OrderEvent
from ..order_config import get_order_config


def record_event(db: Session, order: Order, to_status: str, cause: str, source: str,
                 at: datetime | None = None) -> None:
    """Change the status (to_status may equal the current one: an audit-only event)."""
    ev = OrderEvent(order_id=order.id, from_status=order.status, to_status=to_status,
                    cause=cause[:80], source=source)
    if at is not None:
        ev.created_at = at
    db.add(ev)
    order.status = to_status


def mark_dispatched(db: Session, order: Order, at: datetime, cause: str, source: str) -> bool:
    """The robot accepted the order. Idempotent: the OK reply and the robot's own
    TRANSICION event can both confirm it; the first one wins."""
    if order.dispatched_at is not None:
        return False
    cfg = get_order_config()
    order.dispatched_at = at
    new_status = cfg.dispatched_status if order.status in cfg.dispatch_from else order.status
    record_event(db, order, new_status, cause, source, at=at)
    return True

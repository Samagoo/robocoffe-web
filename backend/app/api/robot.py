"""Robot status and order dispatch (Phase 4). All robot I/O goes through RobotLink -> ClienteRobot."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["robot"])


def get_robot_link(request: Request):
    return request.app.state.robot_link


@router.get("/robot")
def robot_status(request: Request):
    """Connection, robot state, current order (robot_msg_id), battery [V] and pose (x, y [m], th [deg])."""
    return get_robot_link(request).status()


@router.post("/orders/{order_id}/dispatch")
async def dispatch_order(order_id: int, request: Request):
    """Send the order to the robot with ORDEN (ClienteRobot.ordenar).

    200 accepted (robot left) · 409 rejected by the robot (OCUPADO, FUERA_DE_BASE, ...) or the
    order can't be dispatched · 503 robot software not connected · 504 no answer from the robot.
    """
    out = await get_robot_link(request).dispatch(order_id)
    return JSONResponse(status_code=out.http_status, content={
        "ok": out.ok, "robot_msg_id": out.robot_msg_id, "reason": out.reason,
        "robot_state": out.robot_state, "order": out.order,
    })

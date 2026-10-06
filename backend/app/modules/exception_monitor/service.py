from app.modules.exception_monitor.schemas import ExceptionItem


def list_exceptions() -> list[ExceptionItem]:
    return [
        ExceptionItem(id="E-1001", line="L1", title="温度超限", status="open"),
        ExceptionItem(id="E-1002", line="L3", title="设备停机", status="open"),
        ExceptionItem(id="E-1003", line="L2", title="来料异常", status="closed"),
    ]

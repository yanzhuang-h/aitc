"""明确区分关闭、传输故障与响应契约问题，保留原异常链。"""


class ModelGatewayError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ModelDisabledError(ModelGatewayError):
    """当前配置未启用模型；不能伪造模型调用成功。"""


class ModelUnavailableError(ModelGatewayError):
    """模型服务网络或 HTTP 故障。"""


class ModelTimeoutError(ModelUnavailableError):
    """原传输层的超时，或服务端明确报告超时。"""


class ModelResponseError(ModelGatewayError):
    """服务响应不是约定的 JSON/文本结构。"""

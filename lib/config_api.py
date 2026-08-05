"""HTTP 接口层：把 lib 下已交付的 6 个配置函数封装为路由。

只做「路由匹配 + HTTP 状态码映射」，不改动底层函数的语义。
底层函数见 road_info_functions.py / cross_info_functions.py。

对应关系（见部署说明附录）：
    GET  /road_info/{Cross_id}   -> query_road_info
    POST /road_info/add          -> add_road_info
    POST /road_info/update       -> update_road_info
    GET  /cross_info/{Cross_id}  -> query_cross_info
    POST /cross_info/add         -> add_cross_info
    POST /cross_info/update      -> update_cross_info
"""

import os
import time

from lib.road_info_functions import (
    query_road_info,
    add_road_info,
    update_road_info,
)
from lib.cross_info_functions import (
    query_cross_info,
    add_cross_info,
    update_cross_info,
)

# 资源 -> {动作: 底层函数}
_QUERY = {"road_info": query_road_info, "cross_info": query_cross_info}
_WRITE = {
    ("road_info", "add"): add_road_info,
    ("road_info", "update"): update_road_info,
    ("cross_info", "add"): add_cross_info,
    ("cross_info", "update"): update_cross_info,
}

# ================== 单写策略（跨进程） ==================
# 底层函数只用 threading.Lock 串行化同进程内的写操作；多进程/多实例共享
# 同一 JSON 文件时会发生后写覆盖先写。此处在接口层用文件锁把写操作跨进程
# 串行化：任一时刻同一资源只允许一个写入者。见部署说明第 7 节「部署限制」。
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_LOCK_PATHS = {
    "road_info": os.path.join(_BASE_DIR, "road_info.json.lock"),
    "cross_info": os.path.join(_BASE_DIR, "cross_info.json.lock"),
}
_LOCK_TIMEOUT = 10.0   # 等待锁的最长秒数
_LOCK_POLL = 0.05      # 轮询间隔
_LOCK_STALE = 60.0     # 锁文件超过此秒数视为持有者已崩溃的残留锁


class _CrossProcessLock:
    """基于 O_CREAT|O_EXCL 的跨进程互斥锁（Windows/POSIX 通用，无第三方依赖）。"""

    def __init__(self, path):
        self._path = path
        self._fd = None

    def __enter__(self):
        deadline = time.time() + _LOCK_TIMEOUT
        while True:
            try:
                self._fd = os.open(
                    self._path, os.O_CREAT | os.O_EXCL | os.O_RDWR
                )
                os.write(self._fd, str(os.getpid()).encode("ascii"))
                return self
            except FileExistsError:
                # 清理持有者崩溃后残留的锁，避免永久死锁
                try:
                    if time.time() - os.path.getmtime(self._path) > _LOCK_STALE:
                        os.remove(self._path)
                        continue
                except FileNotFoundError:
                    continue
                if time.time() >= deadline:
                    raise TimeoutError("config write lock is busy")
                time.sleep(_LOCK_POLL)

    def __exit__(self, *exc):
        if self._fd is not None:
            os.close(self._fd)
            try:
                os.remove(self._path)
            except FileNotFoundError:
                pass
            self._fd = None


def _alias_cycle_to_zhouqi(body):
    """把 cross_info payload 里的 Cycle 归一化为底层存储字段 zhouqi。

    对外统一用 Cycle（与查询输出一致），底层函数仍使用 zhouqi，
    现有 JSON 数据与读取方（E_T_new.py 等）不受影响。
    同时提供 Cycle 与 zhouqi 时以 Cycle 为准。
    """
    cross_info = body.get("cross_info")
    if not isinstance(cross_info, dict) or "Cycle" not in cross_info:
        return body

    # 浅拷贝，避免修改调用方传入的原始 dict
    new_body = dict(body)
    new_cross_info = dict(cross_info)
    new_cross_info["zhouqi"] = new_cross_info.pop("Cycle")
    new_body["cross_info"] = new_cross_info
    return new_body


def _write_status(result):
    """按底层函数的返回值推断 HTTP 状态码。

    success  -> 201 (created) / 200 (updated)
    error    -> 409 (已存在) / 404 (不存在) / 400 (校验失败)
    """
    if result.get("status") == "success":
        return 201 if result.get("operation") == "created" else 200

    reason = (result.get("reason") or "").lower()
    if "already exists" in reason:
        return 409
    if "does not exist" in reason:
        return 404
    return 400


def handle_config_request(method, path, body):
    """处理一次配置接口请求。

    参数:
        method: HTTP 方法（"GET" / "POST"）。
        path:   请求路径，如 "/road_info/1300229" 或 "/road_info/add"。
        body:   已解析的请求体 dict（GET 可为 None）。

    返回:
        (status_code, response_dict)；若路径不属于配置接口返回 None，
        由调用方按原有逻辑继续处理。
    """
    segments = [seg for seg in path.strip("/").split("/") if seg]
    if len(segments) != 2:
        return None

    resource, action = segments

    # 查询: GET /{resource}/{Cross_id}
    if resource in _QUERY and action not in ("add", "update"):
        if method != "GET":
            return 405, {"status": "error", "reason": "method not allowed"}
        result = _QUERY[resource]({"Cross_id": action})
        # 空 dict 代表路口不存在或不可读，接口层映射为 404
        return (200, result) if result else (404, {})

    # 添加/修改: POST /{resource}/{add|update}
    func = _WRITE.get((resource, action))
    if func is not None:
        if method != "POST":
            return 405, {"status": "error", "reason": "method not allowed"}
        if not isinstance(body, dict):
            return 400, {"status": "error", "saved": False,
                         "reason": "request body must be a JSON object"}
        if resource == "cross_info":
            body = _alias_cycle_to_zhouqi(body)
        # 跨进程单写：同一资源的写操作全局串行化
        try:
            with _CrossProcessLock(_LOCK_PATHS[resource]):
                result = func(body)
        except TimeoutError:
            return 503, {"status": "error", "saved": False,
                         "reason": "config store is busy, please retry"}
        return _write_status(result), result

    return None

"""AITC 服务启动入口。

main() 内完成三件事：配置日志、装配应用、接住 SIGINT 优雅退出；
其余逻辑都在 runtime/ 的编排层内。import 本模块不会产生装配副作用。
"""

import logging
import logging.handlers
import signal

from runtime import create_application


def setup_logging():
    """根日志器：控制台输出 + server.log 每日轮转（保留 7 天）。

    挂在 root 上：其余模块的命名 logger 会把日志冒泡到 root，
    因此这里一次配置即全局生效。
    """
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
    handlers = (
        logging.StreamHandler(),               # 控制台实时查看
        logging.handlers.TimedRotatingFileHandler(  # 每日轮转文件
            "server.log", when="midnight", backupCount=7
        ),
    )
    for handler in handlers:
        handler.setLevel(logging.INFO)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


def main():
    """配置日志、装配应用并进入服务循环（由 TCP 监听阻塞）。"""
    logger = setup_logging()
    # 装配完整应用（数据底座 + 决策管线 + Agent + 协议服务）
    application = create_application(logger)

    def stop_server(_signal, _frame):
        """SIGINT 回调：在主线程内优雅停止整个应用。"""
        logger.info("Stopping server...")
        application.stop()

    # 注册信号处理函数，确保在接收到 SIGINT 信号时能够优雅地停止服务器
    signal.signal(signal.SIGINT, stop_server)
    application.run()


if __name__ == "__main__":
    main()

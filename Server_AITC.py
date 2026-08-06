"""AITC 服务启动入口。"""

import logging
import logging.handlers
import signal

from runtime import create_application


def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
    for handler in (logging.StreamHandler(), logging.handlers.TimedRotatingFileHandler("server.log", when="midnight", backupCount=7)):
        handler.setLevel(logging.INFO)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


logger = setup_logging()
application = create_application(logger)


def stop_server(_signal, _frame):
    logger.info("Stopping server...")
    application.stop()


signal.signal(signal.SIGINT, stop_server)

if __name__ == "__main__":
    application.run()

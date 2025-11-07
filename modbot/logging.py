import logging


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=level,
    )
    return logging.getLogger("modbot")


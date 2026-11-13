"""Reading the robot settings.

The settings are read from the RISM config DB (9100,
``rism_configs.robot_list`` / ``common``) by
``pyindy.mongo.load_robot_settings`` (robot: ``ROBOT_NAME``, DB location:
``RISM_CONFIG_HOST`` / ``RISM_CONFIG_PORT``).
"""

from logging import getLogger

from pyindy.mongo import load_robot_settings

logger = getLogger(__name__)


def load_config():
    """Robot settings (same shape as the former rism_config); {} when not available.

    Never raises: a missing config must not stop the node (defaults are used).
    """
    try:
        return load_robot_settings() or {}
    except Exception as e:
        logger.warning(f"cannot read the robot settings: {e}")
        return {}

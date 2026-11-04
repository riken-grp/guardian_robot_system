#!/usr/bin/env python
# coding: utf-8 -*-

"""ROS2 Setup File"""

import os
from glob import glob

from setuptools import setup

PKG_NAME = "memory"

setup(
    name=PKG_NAME,
    version="2.0.2",
    packages=[
        f"{PKG_NAME}",
        f"{PKG_NAME}/sensor_memory",
        f"{PKG_NAME}/short_term_memory",
        f"{PKG_NAME}/long_term_memory",
        f"{PKG_NAME}/util",
        f"{PKG_NAME}/util/llm",
    ],
    data_files=[
        (
            "share/ament_index/resource_index/packages",
            ["resource/" + PKG_NAME],
        ),
        ("share/" + PKG_NAME, ["package.xml"]),
        # Include all launch files
        (os.path.join("share", PKG_NAME), glob("launch/*.py")),
        # Include config files
        (os.path.join("share", PKG_NAME), glob("config/*.yaml")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="username",
    maintainer_email="no-reply@example.com",
    description="Memory System for Indy",
    license="TODO: License declaration",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            f"memory_node = {PKG_NAME}.indy_memory_node:main",
        ],
    },
)

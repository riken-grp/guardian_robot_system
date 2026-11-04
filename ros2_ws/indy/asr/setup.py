import os
from glob import glob

from setuptools import setup

PKG_NAME = "asr"

setup(
    name=PKG_NAME,
    version="3.1.2",
    packages=[PKG_NAME],
    data_files=[
        (
            "share/ament_index/resource_index/packages",
            ["resource/" + PKG_NAME],
        ),
        ("share/" + PKG_NAME, ["package.xml"]),
        # Include all launch files
        (os.path.join("share", PKG_NAME), glob("launch/*.py")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="username",
    maintainer_email="no-reply@example.com",
    description="TODO: Package description",
    license="TODO: License declaration",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            f"asr_node = {PKG_NAME}.asr:main",
            f"asr_metadata = {PKG_NAME}.metadata_tt:main",
        ],
    },
)

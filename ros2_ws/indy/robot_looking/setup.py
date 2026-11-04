import os
from glob import glob

from setuptools import setup

package_name = "robot_looking"

setup(
    name=package_name,
    version="1.0.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        # Include all launch files
        (os.path.join("share", package_name), glob("launch/*.py")),
        # Include config files
        (os.path.join("share", package_name), glob("config/*")),
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
            f"looking_target_recognition_node = {package_name}.looking_target_recognition_node:main",
        ],
    },
)

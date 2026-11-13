import os
from glob import glob

from setuptools import find_packages, setup

package_name = "action_recognition"

setup(
    name=package_name,
    version="1.0.0",
    packages=find_packages(include=[package_name, "tools"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        # Include all launch files
        (os.path.join("share", package_name, "launch"), glob("launch/*.py")),
        # Include config files
        (os.path.join("share", package_name, "config"), glob("config/*")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="TODO",
    maintainer_email="todo@todo.todo",
    description="TODO: Package description",
    license="TODO: License declaration",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            f"hand_waving_node = {package_name}.hand_waving_node:main",
            f"arm_state_node = {package_name}.arm_state_node:main",
            f"looking_at_node = {package_name}.looking_at_node:main",
            f"looking_at_simple_node = {package_name}.looking_at_simple_node:main",
            f"wheelchair_node = {package_name}.wheelchair_node:main",
            f"gaze_data_saver_node = {package_name}.gaze_data_saver_node:main",
            f"noticed_node = {package_name}.noticed_node:main",
        ],
    },
)

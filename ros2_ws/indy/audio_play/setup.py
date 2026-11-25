import os
from glob import glob

from setuptools import setup

package_name = "audio_play"

setup(
    name=package_name,
    version="1.0.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        # Include all launch files
        (os.path.join("share", package_name), glob("launch/*.py")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="username",
    maintainer_email="no-reply@example.com",
    description="Play audio received on robot/play_audio with the robot speaker (pass-through)",
    license="TODO: License declaration",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "rosAudioPlay = audio_play.rosAudioPlay:main",
        ],
    },
)

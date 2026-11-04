from glob import glob

from setuptools import setup

package_name = "db_management"

setup(
    name=package_name,
    version="0.0.0",
    packages=[
        package_name,
    ],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name, glob("launch/*.launch.py")),
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
            f"register_db_recog_node = {package_name}.register_db_recog_node:main",
            f"register_db_asr_node = {package_name}.register_db_asr_node:main",
            f"register_db_weather_node = {package_name}.register_db_weather_node:main",
            f"register_db_environsensor_node = {package_name}.register_db_environsensor_node:main",
            f"register_db_bumper_node = {package_name}.register_db_bumper_node:main",
            f"register_db_qrcode_node = {package_name}.register_db_qrcode_node:main",
            f"modify_priority_node = {package_name}.modify_priority_node:main",
            f"check_num_of_person_node = {package_name}.check_num_of_person_node:main",
            f"check_looking_at_node = {package_name}.check_looking_at_node:main",
            f"check_arm_state_node = {package_name}.check_arm_state_node:main",
            f"check_waving_hand_node = {package_name}.check_waving_hand_node:main",
            f"check_wheelchair_node = {package_name}.check_wheelchair_node:main",
            f"map_to_mongodb = {package_name}.map_to_mongodb:main",
        ],
    },
)

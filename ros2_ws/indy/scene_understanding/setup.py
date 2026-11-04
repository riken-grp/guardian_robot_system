from glob import glob

from setuptools import find_packages, setup

package_name = "scene_understanding"

setup(
    name=package_name,
    version="0.0.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name, glob("launch/*.launch.py")),
        ("share/" + package_name + "/config", glob("config/*.yaml")),
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
            f"aruco_reader_node = {package_name}.aruco_reader_node:main",
            f"qr_code_reader_node = {package_name}.qr_code_reader_node:main",
            f"association_node = {package_name}.association_node:main",
            f"attribute_recognition_node = {package_name}.attribute_recognition_node:main",
            f"detection_and_tracking_node = {package_name}.detection_and_tracking_node:main",
            f"dummy_tf_publisher_node = {package_name}.dummy_tf_publisher:main",
            f"head_pose_estimation_node = {package_name}.head_pose_estimation_node:main",
            f"body_pose_estimation_node = {package_name}.body_pose_estimation_node:main",
            f"scene_text_node = {package_name}.scene_text_node:main",
            f"compressed_image_flip_node = {package_name}.compressed_image_flip_node:main",
        ],
    },
)

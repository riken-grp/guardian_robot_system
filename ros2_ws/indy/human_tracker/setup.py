import os
from glob import glob
from setuptools import setup

package_name = 'human_tracker'

setup(
    name=package_name,
    version='0.0.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        # Include all launch files
        (os.path.join('share', package_name), glob('launch/*launch.py')),
        # Include config files
        (os.path.join('share', package_name), glob('config/*')),

    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='username',
    maintainer_email='no-reply@example.com',
    description='TODO: Package description',
    license='TODO: License declaration',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'human_tracker_node = human_tracker.human_tracker:main',
            'human_leg_tracker_node = human_tracker.human_leg_tracker:main',
            'facepose_publisher_node = human_tracker.facepose_publisher:main',
            'ros_audio_tracker_node = human_tracker.ros_audio_tracker:main',
            'human_tracker_integration_node = human_tracker.human_tracker_integration:main',
        ],
    },
)

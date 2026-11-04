import os
from glob import glob

from setuptools import find_packages, setup

package_name = 'lidar_person_tracker'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
    ],
    install_requires=['setuptools', 'numpy'],
    zip_safe=True,
    maintainer='todo',
    maintainer_email='todo@todo.com',
    description='LiDAR-based person tracker using LaserScan clustering and Kalman filtering',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'tracker_node = lidar_person_tracker.tracker_node:main',
        ],
    },
)

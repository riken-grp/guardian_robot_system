from setuptools import find_packages, setup
import os
from glob import glob

package_name = 'gestures_modes'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        # Include all launch files
        (os.path.join('share', package_name), glob('launch/*.py')),
        # Include config files
        (os.path.join('share', package_name), glob('config/*')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='username',
    maintainer_email='no-reply@example.com',
    description='TODO: Package description',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'modes_description_w_action_server = gestures_modes.modes_description_w_action_server:main',
            'default_mode_action_server = gestures_modes.default_mode_action_server:main',
            'default_mode_action_client = gestures_modes.default_mode_action_client:main',
            'tracking_mode_action_server = gestures_modes.tracking_mode_action_server:main',
            'tracking_mode_action_client = gestures_modes.tracking_mode_action_client:main',
            'listen_mode_action_server = gestures_modes.listen_mode_action_server:main',
            'listen_mode_action_client = gestures_modes.listen_mode_action_client:main',
            'face_tracking_publisher_dummy = gestures_modes.face_tracking_publisher_dummy:main'
        ],
    },
)

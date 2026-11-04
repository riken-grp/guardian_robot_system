import os
from glob import glob

from setuptools import setup

package_name = 'audio_source_separator'

setup(
    name=package_name,
    version='0.0.1',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='TODO',
    maintainer_email='todo@todo.todo',
    description='Audio source separation using MVDR beamforming and VAD',
    license='TODO: License declaration',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            f"separator_node = {package_name}.separator_node:main",
            f"speaker_id_node = {package_name}.speaker_id_node:main",
            f"monitor_node = {package_name}.monitor_node:main",
        ],
    },
)

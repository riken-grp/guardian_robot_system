import os
from glob import glob

from setuptools import find_packages, setup

package_name = 'sound_source_localizer'

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
    install_requires=['setuptools', 'numpy', 'scipy', 'pyyaml'],
    zip_safe=True,
    maintainer='TODO',
    maintainer_email='todo@todo.com',
    description='SRP-PHAT based sound source localization for 16-channel microphone array',
    license='TODO',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'localizer_node = sound_source_localizer.localizer_node:main',
        ],
    },
)

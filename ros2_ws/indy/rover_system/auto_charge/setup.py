import os
from glob import glob
from setuptools import setup


package_name = 'auto_charge'

setup(
    name=package_name,
    version='0.0.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name), glob('launch/*launch.[pxy][yma]*')),
        (os.path.join('share', package_name), glob('config/*.yaml')),
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
            'auto_charge = auto_charge.auto_charge:main',
            'lidar_marker_finder = auto_charge.lidar_marker_finder:main',
            'navigate_to_charge_server = auto_charge.navigate_to_charge_server:main',
        ],
    },
)

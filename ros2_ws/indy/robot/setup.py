import os
from glob import glob
from setuptools import setup

package_name = 'robot'


setup(
    name=package_name,
    version='1.0.0',
    packages=[package_name],
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
    license='TODO: License declaration',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            # 'NodeName = robot.FileName:main',
            'rosTTS = robot.rosTTS:main',
            'rosEYE = robot.rosEYE:main',
            'rosNAV = robot.rosNAV:main',
            'rosNavSmr = robot.rosNAV_smr:main',
            'rosCommand = robot.rosCommand:main',
            'rosGesture = robot.rosGesture:main',
            'rosGesture_modes = robot.rosGesture_modes:main',
            'rosWatchdog = robot.rosWatchdog:main',
            'rosVolume = robot.rosVolume:main'
        ],
    },
)

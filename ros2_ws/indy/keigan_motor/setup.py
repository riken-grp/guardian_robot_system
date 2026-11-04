import os
import sys
from glob import glob
from setuptools import setup


package_name = 'keigan_motor'

# pykeigan(公式ライブラリ)が配置されていない場合はノード・launch等をインストールしない
pykeigan_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            package_name, 'pykeigan')
has_pykeigan = os.path.isdir(pykeigan_dir)

if has_pykeigan:
    packages = [package_name, package_name + '/pykeigan']
    data_files = [
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name), glob('launch/*launch.py')),
        (os.path.join('share', package_name), glob('config/*.yaml')),
    ]
    console_scripts = [
        'keigan_motor_node = keigan_motor.keigan_motor:main',
    ]
else:
    print('[keigan_motor] WARNING: pykeigan not found in %s. '
          'Skipping build of keigan_motor (see README.md).' % pykeigan_dir,
          file=sys.stderr)
    packages = []
    data_files = []
    console_scripts = []

setup(
    name=package_name,
    version='0.0.0',
    packages=packages,
    data_files=data_files,
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='username',
    maintainer_email='no-reply@example.com',
    description='TODO: Package description',
    license='TODO: License declaration',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': console_scripts,
    },
)

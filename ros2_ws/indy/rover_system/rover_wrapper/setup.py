import os
from glob import glob
from setuptools import setup


package_name = 'rover_wrapper'

# 環境変数 ON_ROBOT が 1 の場合のみビルドし、それ以外の場合はパッケージをスキップする
# （colcon が setup.py の標準出力を解析するため、ここでは print しない）
on_robot = os.getenv('ON_ROBOT') == '1'

setup(
    name=package_name,
    version='0.0.0',
    packages=[package_name] if on_robot else [],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name), glob('launch/*launch.[pxy][yma]*')),
        (os.path.join('share', package_name), glob('config/*.yaml')),
    ] if on_robot else [],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='username',
    maintainer_email='no-reply@example.com',
    description='TODO: Package description',
    license='TODO: License declaration',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'rover_wrapper = rover_wrapper.rover_wrapper:main',
        ],
    } if on_robot else {},
)

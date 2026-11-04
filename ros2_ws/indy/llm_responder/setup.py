import os
from glob import glob
from setuptools import setup

PKG_NAME = 'llm_responder'

setup(
    name=PKG_NAME,
    version='1.0.0',
    packages=[
        f"{PKG_NAME}",
        f"{PKG_NAME}/util",
        f"{PKG_NAME}/util/llm",
    ],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + PKG_NAME]),
        ('share/' + PKG_NAME, ['package.xml']),
        # Include all launch files
        (os.path.join('share', PKG_NAME), glob('launch/*.py')),
        # Include config files
        (os.path.join('share', PKG_NAME), glob('config/*')),

    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='username',
    maintainer_email='no-reply@example.com',
    description='LLM-based Response Generator for Indy',
    license='TODO: License declaration',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            # 'NodeName = llm_responder.FileName:main'
            f"llm_responder_node = {PKG_NAME}.llm_responder_node:main",
        ],
    },
)

import copy
import os
import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction, Shutdown
from launch.substitutions import LaunchConfiguration
from launch.substitutions import TextSubstitution
from launch_ros.actions import Node

configurable_parameters = [
    {'name': 'report_hz',          'default': '1',         'description': 'timer_callback interavl [Hz]'},
    {'name': 'baudrate',           'default': '115200',         'description': 'baudrate'},
    {'name': 'serial_port',        'default': '/dev/ttyUSB0',         'description': 'serial port name'},
    {'name': 'node_id',            'default': 'not_set',         'description': 'Node ID'},
    {'name': 'default_target_file',            'default': 'neutral2.jpg',         'description': 'Default traget file'},
    {'name': 'config_file',        'default': "''", 'description': 'yaml config file'},
    {'name': 'log_level',          'default': 'info', 'description': 'debug log level [DEBUG|INFO|WARN|ERROR|FATAL]'},
]

def declare_configurable_parameters(parameters):
    return [DeclareLaunchArgument(param['name'], default_value=param['default'], description=param['description']) for param in parameters]

def set_configurable_parameters(parameters):
    return dict([(param['name'], LaunchConfiguration(param['name'])) for param in parameters])

def yaml_to_dict(path_to_yaml):
    with open(path_to_yaml, "r") as f:
        return yaml.load(f, Loader=yaml.SafeLoader)


def launch_setup(context, *args, **kwargs):
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        return

    _config_file = LaunchConfiguration("config_file").perform(context)
    params_from_file = {} if _config_file == "''" else yaml_to_dict(_config_file)
    log_level = 'info'

    start_target_program_with_parameters = Node(
        package='eye_display',
        namespace=robot_name,
        name='eye_display',
        executable='eye_display',
        # output='screen',  # console log -> .ros/log/*/launch.log
        emulate_tty=True,
        parameters=[set_configurable_parameters(configurable_parameters)
                            , params_from_file
                            ],
        arguments=['--ros-args', '--log-level', LaunchConfiguration('log_level')],
        on_exit = Shutdown()
        )

    return [
        start_target_program_with_parameters,
        ]

def generate_launch_description():
    return LaunchDescription(declare_configurable_parameters(configurable_parameters) + [
        OpaqueFunction(function=launch_setup)
    ])
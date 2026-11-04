import os
from ament_index_python.packages import get_package_share_directory
import launch
import launch_ros.actions
import xacro
from launch.actions import Shutdown

share_dir_path = os.path.join(get_package_share_directory('amr_description'))
xacro_path = os.path.join(share_dir_path, 'urdf', 'urdf', 'amr.xacro')
urdf_path = os.path.join(share_dir_path, 'urdf', 'urdf', 'amr.urdf')

def generate_launch_description():
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        return

    doc = xacro.process_file(xacro_path, mappings={"robot_name" : robot_name})
    robot_desc = doc.toprettyxml(indent='   ')

    f = open(urdf_path, 'w')
    f.write(robot_desc)
    f.close()
    rsp = launch_ros.actions.Node(
        package='robot_state_publisher', 
        executable='robot_state_publisher', 
        namespace=robot_name,
        # output='both', 
        arguments=[urdf_path],
        on_exit = Shutdown()
        )
    
    return launch.LaunchDescription([rsp])
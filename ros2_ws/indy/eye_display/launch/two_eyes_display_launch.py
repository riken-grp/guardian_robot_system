import launch
from ament_index_python.packages import get_package_share_directory
from launch.launch_description_sources import PythonLaunchDescriptionSource

def generate_launch_description():
  launch_launch_share_dir = get_package_share_directory("eye_display")

  right_eye_launch = launch.actions.IncludeLaunchDescription(
    PythonLaunchDescriptionSource([launch_launch_share_dir + "/eye_display_launch.py"]),
      launch_arguments={
          "serial_port": "/dev/ttyClientA",
          "node_id": "right",
          "default_target_name": "neutral1.jpg"
      }.items()
  )

  left_eye_launch = launch.actions.IncludeLaunchDescription(
    PythonLaunchDescriptionSource([launch_launch_share_dir + "/eye_display_launch.py"]),
      launch_arguments={
          "serial_port": "/dev/ttyClientB",
          "node_id": "left",
          "default_target_name": "neutral1.jpg"
      }.items()
  )

  return launch.LaunchDescription([
    right_eye_launch,
    left_eye_launch
  ])

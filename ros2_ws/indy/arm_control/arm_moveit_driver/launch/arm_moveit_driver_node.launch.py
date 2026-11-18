import os
import xacro
import yaml

from ament_index_python.packages import get_package_share_directory
from launch import LaunchContext, LaunchDescription
from launch.actions import GroupAction, OpaqueFunction, Shutdown
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node, SetRemap


def load_file(package_name, file_path):
    package_path = get_package_share_directory(package_name)
    absolute_file_path = os.path.join(package_path, file_path)

    try:
        with open(absolute_file_path, "r") as file:
            return file.read()
    except EnvironmentError:  # parent of IOError, OSError *and* WindowsError where available
        return None

def load_yaml_file(package_name, file_path):
    package_path = get_package_share_directory(package_name)
    absolute_file_path = os.path.join(package_path, file_path)
    try:
        with open(absolute_file_path, "r") as file:
            return yaml.safe_load(file)
    except EnvironmentError:  # parent of IOError, OSError *and* WindowsError where available
        return None    

def pose_control_params(prefix_name_str):
    """手先位置制御用のパラメータを作る。

    - モータの gain / offset / 可動範囲は arm_motor_control.yaml の該当する腕の節をそのまま読む
      （キーがノード名付きのため、ファイルを渡すだけでは本ノードに届かない）
    - 取り付け位置と干渉判定の箱は amr_description の arm_mount.yaml を読む（amr.xacro と共有）
    読めない場合は空のまま渡し、ノード側で手先制御を無効にする（関節角指令には影響しない）。
    """
    params = {}
    side = prefix_name_str.rstrip("/").split("/")[-1]   # "right_arm" / "left_arm"
    robot_name = prefix_name_str.strip("/").split("/")[0]

    try:
        motor_yaml_path = os.path.join(
            get_package_share_directory("arm_motor_control"), "config", "arm_motor_control.yaml")
        with open(motor_yaml_path, "r") as f:
            motor_yaml = yaml.safe_load(f)
        motor = None
        for key, value in motor_yaml.items():
            if key.endswith("/" + side + "/arm_motor_control_node"):
                motor = value["ros__parameters"]
                break
        if motor is None:
            raise KeyError(side + "/arm_motor_control_node が見つからない")
        params.update({
            "motor_joint_names": list(motor["joint_names"]),
            "motor_gain": [float(v) for v in motor["gain"]],
            "motor_default_offset": [float(v) for v in motor["default_offset"]],
            "motor_min_position": [float(v) for v in motor["min_position"]],
            "motor_max_position": [float(v) for v in motor["max_position"]],
        })
    except Exception as e:
        print("[arm_moveit_driver] WARNING: arm_motor_control.yaml を読めないため手先制御を無効にする: " + str(e))
        return {}

    try:
        mount_yaml_path = os.path.join(
            get_package_share_directory("amr_description"), "urdf", "urdf", "arm_mount.yaml")
        with open(mount_yaml_path, "r") as f:
            mount_yaml = yaml.safe_load(f)
        mount = mount_yaml[side]
        boxes = mount_yaml.get("collision_boxes", {}) or {}
        params.update({
            "mount_parent_frame": robot_name + "_" + mount_yaml["parent_link"],
            "mount_xyz": [float(v) for v in mount["xyz"]],
            "mount_rpy": [float(v) for v in mount["rpy"]],
            "collision_box_names": list(boxes.keys()) if boxes else [""],
            "collision_box_sizes": [float(v) for b in boxes.values() for v in b["size"]] or [0.0],
            "collision_box_poses": [float(v) for b in boxes.values() for v in list(b["xyz"]) + list(b["rpy"])] or [0.0],
            "collision_padding": float(mount_yaml.get("collision_padding", 0.0)),
            "collision_allowed_links": list(mount_yaml.get("collision_allowed_links", [""])),
        })
    except Exception as e:
        print("[arm_moveit_driver] WARNING: arm_mount.yaml を読めないため手先制御を無効にする（関節角指令は従来どおり）: " + str(e))

    return params


def launch_node(context: LaunchContext):
    prefix_name = LaunchConfiguration("prefix_name")
    prefix_name_str = context.perform_substitution(prefix_name)

    group_name = LaunchConfiguration("group_name")
    group_name_str = context.perform_substitution(group_name)
    
    package_name = LaunchConfiguration("package_name")
    package_name_str = context.perform_substitution(package_name)

    xacro_file_path = LaunchConfiguration("xacro_file_path")
    xacro_file = context.perform_substitution(xacro_file_path)
    
    srdf_file_path = LaunchConfiguration("srdf_file_path")
    srdf_file = context.perform_substitution(srdf_file_path)    
    
    node_params = {
        "prefix_name": prefix_name_str,
        "group_name": group_name_str,
    }

    # planning_context
    robot_description_config = xacro.process_file(
        os.path.join(
            get_package_share_directory(package_name_str),
            xacro_file,
        )
    )
    robot_description = {"robot_description": robot_description_config.toxml()}

    robot_description_semantic_config = load_file(
        package_name_str, srdf_file
    )
    robot_description_semantic = {
        "robot_description_semantic": robot_description_semantic_config
    }

    kinematics_yaml = load_yaml_file(
        package_name_str, "config/kinematics.yaml"
    )
    
    
    trajectory_execution = {
        "moveit_manage_controllers": True,
        "trajectory_execution.allowed_execution_duration_scaling": 1.2,
        "trajectory_execution.allowed_goal_duration_margin": 0.5,
        "trajectory_execution.allowed_start_tolerance": 0.01,
    }

    planning_scene_monitor_parameters = {
        "publish_planning_scene": True,
        "publish_geometry_updates": True,
        "publish_state_updates": True,
        "publish_transforms_updates": True,
    }
    
    
    # joint_limits.yaml
    joint_limits_yaml = load_yaml_file(
        package_name_str, "config/joint_limits.yaml"
    )
    robot_description_planning = {"robot_description_planning": joint_limits_yaml}
    
    
    moveit_simple_controllers_yaml = load_yaml_file(
        package_name_str, "config/moveit_controllers.yaml"
    )
    moveit_controllers = {
        "moveit_simple_controller_manager": moveit_simple_controllers_yaml,
        "moveit_controller_manager": "moveit_simple_controller_manager/MoveItSimpleControllerManager",
    }

    return [
        SetRemap(src="joint_states", dst="joints"),
        SetRemap(src="/tf", dst="/" + prefix_name_str + "/tf"),
        SetRemap(src="/tf_static", dst="/" + prefix_name_str + "/tf_static"),
        Node(
            package=package_name_str,
            executable="arm_moveit_driver_node",
            namespace=prefix_name_str,
            parameters=[
                {"move_group_namespace": "/" + prefix_name_str, "group_name": group_name},
                moveit_controllers,
                planning_scene_monitor_parameters,
                robot_description,
                robot_description_semantic,
                kinematics_yaml,
                robot_description_planning,
                trajectory_execution,
                node_params,
                # 手先位置制御用（本ノード内の IK のみが使う。move_group には渡さない）
                # 本ノードの IK ソルバはトップレベルの "<group>.*" を読むため、上の kinematics_yaml を後勝ちで上書きする
                load_yaml_file(package_name_str, "config/kinematics_pose_ik.yaml"),
                pose_control_params(prefix_name_str),
                ],
            # output="screen",
            on_exit = Shutdown()
        )
    ]



def generate_launch_description():
    # robot_name = os.getenv("ROBOT_NAME")
    # if robot_name is None:
    #     print ("error: failed to get robot name")
    #     return
    
    return LaunchDescription(
        [
            GroupAction(
                [
                    # PushRosNamespace(robot_name),
                    OpaqueFunction(function=launch_node)
                ]
            )
        ]
    )


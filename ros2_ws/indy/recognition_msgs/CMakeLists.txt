cmake_minimum_required(VERSION 3.8)
project(recognition_msgs)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# find dependencies
find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
# uncomment the following section in order to fill in
# further dependencies manually.
# find_package(<dependency> REQUIRED)

set(msg_files
  "msg/ArUcoMarker.msg"
  "msg/ArUcoMarkers.msg"
  "msg/Label.msg"
  "msg/Labels.msg"
  "msg/Object.msg"
  "msg/Objects.msg"
  "msg/ObjectTracklet.msg"
  "msg/Person.msg"
  "msg/Persons.msg"
  "msg/PersonTracklet.msg"
  "msg/Pointing.msg"
  "msg/Pointings.msg"
  "msg/Pose.msg"
  "msg/Poses.msg"
  "msg/RecogResult.msg"
  "msg/StringStamped.msg"
  "msg/OmronEnvSensor.msg"
  "msg/SceneText.msg"
  "msg/Relation.msg"
  "msg/Relations.msg"
  )

set(srv_files
  "srv/ArUcoID.srv"
)

rosidl_generate_interfaces(${PROJECT_NAME}
  ${msg_files}
  ${srv_files}
  DEPENDENCIES std_msgs sensor_msgs
  )

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  # the following line skips the linter which checks for copyrights
  # comment the line when a copyright and license is added to all source files
  set(ament_cmake_copyright_FOUND TRUE)
  # the following line skips cpplint (only works in a git repo)
  # comment the line when this package is in a git repo and when
  # a copyright and license is added to all source files
  set(ament_cmake_cpplint_FOUND TRUE)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()

cmake_minimum_required(VERSION 3.8)
project(guardian_urdf)

# 環境変数 ON_ROBOT の値を取得
if("$ENV{ON_ROBOT}" STREQUAL "1")
  # ON_ROBOT が 1 の場合、特定のパッケージをビルドするための設定を行う
  message("ON_ROBOT is set to 1. Building the package.")
else()
  # ON_ROBOT が 1 でない場合、パッケージをスキップする設定を行う
  message("ON_ROBOT is not set to 1. Skipping the package.")
  return()
endif()

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# find dependencies
find_package(ament_cmake REQUIRED)
find_package(urdf_launch REQUIRED)

# install urdf files
install(
  DIRECTORY
  urdf
  visual
  DESTINATION share/${PROJECT_NAME}/
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

ament_export_include_directories(include)

ament_package()

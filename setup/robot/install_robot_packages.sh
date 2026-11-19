#!/bin/bash
# ロボット搭載マシンに必要なパッケージを一括でインストールする
# （docs/手順書/indy_ロボット搭載マシン構築.md の「1. 一括インストール」。内容は同「2. 一括インストールの内容」）
#
#   ./install_robot_packages.sh                  既定の手順をすべて実行する
#   ./install_robot_packages.sh pyindy check     指定した手順だけ実行する（手順名は --help を参照）
#
# Ubuntu 22.04 で、sudo できる一般ユーザで実行する（root では実行しない）。
# 何度実行してもよい。
#
# 以下は本スクリプトでは行わない。手順書に従って設定する。
#   - chrony の同期先（3. 時刻同期設定）
#   - Avahi のインタフェース（4. Avahi設定）
#   - /etc/rc.local の CAN 設定（5. CANインターフェースの起動時自動設定）
#   - ~/indy.env と ~/.bashrc（6. 環境変数設定）
#   - ビルド（7）、起動スクリプトの登録（8）
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)

ZENOH_VERSION=1.9.0
# numpy は 1.24.4、opencv-python は 4.12 未満を入れる
NUMPY_SPEC="numpy==1.24.4"
OPENCV_SPEC="opencv-python<4.12"

ALL_STEPS=(base ros2 python zenoh chrony mic2sock avahi pyindy node rism2 viewer check)
DEFAULT_STEPS=("${ALL_STEPS[@]}")


log()  { echo; echo "===== $* ====="; }
warn() { echo "[WARN] $*" >&2; }
apt_install() { sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "$@"; }

# 指定したリポジトリ（URL の正規表現）を、コメント以外の行で参照している apt の設定ファイルを表示する
# （.list と deb822 形式の .sources の両方を見る。http / https は区別しない）
apt_repo_files() {
  local pattern=$1
  local files=(/etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources)
  local f
  for f in "${files[@]}"; do
    [ -f "$f" ] || continue
    grep -Eq "^[^#]*${pattern}" "$f" && echo "$f"
  done
  return 0
}

# apt リポジトリを追加する。同じリポジトリが既に設定されている場合は、鍵もリストも変更しない
# （Signed-By の異なる設定が重複すると apt-get update がエラーになるため）
#   add_apt_repo <名前> <URL の正規表現> <書き込む .list> <.list の内容> <鍵を置く関数>
add_apt_repo() {
  local name=$1 pattern=$2 list=$3 line=$4 install_key=$5
  local existing others=()
  existing=$(apt_repo_files "$pattern")
  if [ -n "$existing" ]; then
    echo "$name の apt リポジトリは設定済みのため、追加しません:"
    sed 's/^/  /' <<<"$existing"
    # 本スクリプトが過去に書いた $list と、別の設定が重複していないか確認する
    while read -r f; do [ "$f" != "$list" ] && others+=("$f"); done <<<"$existing"
    if [ -f "$list" ] && [ ${#others[@]} -gt 0 ]; then
      warn "$name のリポジトリが $list と ${others[*]} で重複しています。"
      warn "apt-get update が Signed-By の不一致でエラーになる場合は、内容を確認のうえ sudo rm $list で削除してください"
    fi
    return 0
  fi
  "$install_key"
  echo "$line" | sudo tee "$list" >/dev/null
}

usage() {
  cat <<EOF
使い方: $0 [手順名 ...]

手順名を省略した場合は、既定の手順（${DEFAULT_STEPS[*]}）を順に実行する。

  base      基本パッケージ（vim、git、tmux、ffmpeg、can-utils、pip、ビルド用ライブラリなど）
  ros2      ROS2 Humble と関連パッケージ、rosdep による不足分の補完
  python    Python ライブラリ（opencv-python、open3d）
  zenoh     zenoh-bridge-ros2dds ${ZENOH_VERSION}（apt-mark hold で固定）
  chrony    chrony のインストール（同期先の設定は手順書 3. で行う）
  mic2sock  Rust、JACK
  avahi     avahi-daemon、avahi-utils（インタフェースの設定は手順書 4. で行う）
  pyindy    pyindy（modules/pyindy）と依存ライブラリ
  node      Node.js（LTS）と chat_monitor のライブラリ
  rism2     uv とシナリオマネージャ（rism2）の依存
  viewer    indyxe_viewer の依存
  check     インストール結果の確認
EOF
}

# ---------------------------------------------------------------
# 2.1. 基本パッケージ
# ---------------------------------------------------------------
step_base() {
  log "2.1. 基本パッケージ"
  sudo apt-get update
  sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y
  apt_install vim openssh-server git net-tools tmux ffmpeg can-utils \
              curl gnupg lsb-release
  # pip と pyindy の依存（simpleaudio）のビルド用
  apt_install python3-pip python3-dev build-essential libasound2-dev
}

# ---------------------------------------------------------------
# 2.2. ROS2
# ---------------------------------------------------------------
ros2_key() {
  sudo curl -fsSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
       -o /usr/share/keyrings/ros-archive-keyring.gpg
}

step_ros2() {
  log "2.2. ROS2 Humble"
  add_apt_repo "ROS2" 'packages\.ros\.org/ros2/' /etc/apt/sources.list.d/ros2.list \
    "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo "$UBUNTU_CODENAME") main" \
    ros2_key
  sudo apt-get update
  apt_install ros-humble-desktop ros-dev-tools
  apt_install ros-humble-navigation2 \
              ros-humble-image-transport-plugins \
              ros-humble-xacro \
              ros-humble-image-proc \
              ros-humble-rmw-cyclonedds-cpp \
              ros-humble-urdf-launch \
              ros-humble-pcl-ros \
              ros-humble-moveit \
              ros-humble-moveit-configs-utils \
              ros-humble-moveit-kinematics \
              ros-humble-moveit-simple-controller-manager \
              ros-humble-diagnostic-updater \
              ros-humble-laser-proc \
              ros-humble-realsense2-camera \
              ros-humble-slam-toolbox \
              ros-humble-teleop-twist-keyboard

  # package.xml の依存のうち、上で入らなかったものを rosdep で入れる
  [ -f /etc/ros/rosdep/sources.list.d/20-default.list ] || sudo rosdep init
  rosdep update --rosdistro humble
  rosdep install --from-paths "$REPO/ros2_ws/indy" --ignore-src -r -y --rosdistro humble \
    --skip-keys "ftd2xx mpsse warehouse_ros_mongo pulseaudio-utils python3_pytest" \
    || warn "rosdep で解決できない依存があります（上のメッセージを確認してください）"
}

# ---------------------------------------------------------------
# 2.2. ROS2 の手順4（Python ライブラリ）
# ---------------------------------------------------------------
step_python() {
  log "2.2. Python ライブラリ"
  pip3 install "$NUMPY_SPEC" "$OPENCV_SPEC" open3d
}

# ---------------------------------------------------------------
# 2.3. zenoh-bridge-ros2dds
# ---------------------------------------------------------------
zenoh_key() {
  sudo mkdir -p /etc/apt/keyrings
  curl -fsSL https://download.eclipse.org/zenoh/debian-repo/zenoh-public-key \
    | sudo gpg --dearmor --yes --output /etc/apt/keyrings/zenoh-public-key.gpg
}

step_zenoh() {
  log "2.3. zenoh-bridge-ros2dds ${ZENOH_VERSION}"
  add_apt_repo "zenoh" 'download\.eclipse\.org/zenoh/debian-repo' /etc/apt/sources.list.d/zenoh.list \
    "deb [signed-by=/etc/apt/keyrings/zenoh-public-key.gpg] https://download.eclipse.org/zenoh/debian-repo/ /" \
    zenoh_key
  sudo apt-get update
  apt_install --allow-change-held-packages "zenoh-bridge-ros2dds=${ZENOH_VERSION}"
  sudo apt-mark hold zenoh-bridge-ros2dds
}

# ---------------------------------------------------------------
# 2.4. chrony
# ---------------------------------------------------------------
step_chrony() {
  log "2.4. chrony"
  apt_install chrony
  sudo systemctl enable chrony
}

# ---------------------------------------------------------------
# 2.5. mic2sock（Rust、JACK）
# ---------------------------------------------------------------
step_mic2sock() {
  log "2.5. mic2sock（Rust、JACK）"
  if [ ! -x "$HOME/.cargo/bin/rustup" ]; then
    curl https://sh.rustup.rs -sSf | sh -s -- -y
  fi
  # jackd の「リアルタイム優先度を有効にするか」に「はい」と答える
  # （/etc/security/limits.d/audio.conf が有効になる）
  echo "jackd2 jackd/tweak_rt_limits boolean true" | sudo debconf-set-selections
  apt_install cargo jackd libjack-jackd2-dev
  # 既に jackd2 が入っていた場合も設定を反映する
  sudo DEBIAN_FRONTEND=noninteractive dpkg-reconfigure jackd2
}

# ---------------------------------------------------------------
# 2.6. Avahi
# ---------------------------------------------------------------
step_avahi() {
  log "2.6. Avahi"
  apt_install avahi-daemon avahi-utils
}

# ---------------------------------------------------------------
# 2.7. pyindy
# ---------------------------------------------------------------
step_pyindy() {
  log "2.7. pyindy"
  # numpy、opencv-python は step_python と同じ版を指定する
  pip3 install "$NUMPY_SPEC" "$OPENCV_SPEC" "$REPO/modules/pyindy"
}

# ---------------------------------------------------------------
# 2.8. Node.js と chat_monitor
# ---------------------------------------------------------------
step_node() {
  log "2.8. Node.js（LTS）と chat_monitor"
  if [ ! -x /usr/local/bin/node ]; then
    apt_install nodejs npm
    sudo npm install -g n
    sudo n lts
    sudo DEBIAN_FRONTEND=noninteractive apt-get purge -y nodejs npm
    hash -r
  fi
  /usr/local/bin/node --version
  (cd "$REPO/modules/indy_modules/chat_monitor" && /usr/local/bin/npm install mongodb express deepl-node)
}

# ---------------------------------------------------------------
# 2.9. uv とシナリオマネージャ（rism2）
# ---------------------------------------------------------------
uv_bin() {
  if [ ! -x "$HOME/.local/bin/uv" ]; then
    curl -LsSf https://astral.sh/uv/install.sh | sh >&2
  fi
  echo "$HOME/.local/bin/uv"
}

step_rism2() {
  log "2.9. uv とシナリオマネージャ（rism2）"
  local uv
  uv=$(uv_bin)
  "$uv" --version
  (cd "$REPO/modules/scenario_manager/rism2" && "$uv" sync)
}

# ---------------------------------------------------------------
# 2.10. indyxe_viewer
# ---------------------------------------------------------------
step_viewer() {
  log "2.10. indyxe_viewer"
  local uv
  uv=$(uv_bin)
  (cd "$REPO/modules/indy_modules/indyxe_viewer" && "$uv" sync)
}

# ---------------------------------------------------------------
# 確認
# ---------------------------------------------------------------
step_check() {
  log "確認"
  local ng=0
  python3 - <<'EOF' || ng=1
import numpy, cv2, open3d
import pyindy.mongo, pyindy.grp_tts, pyindy.param_manager, pyindy.functions
print("numpy", numpy.__version__, "/ opencv", cv2.__version__, "/ open3d", open3d.__version__)
assert numpy.__version__.startswith("1."), "numpy 2 が入っています。install_robot_packages.sh python pyindy を実行し直してください"
print("pyindy OK:", pyindy.mongo.__file__)
EOF
  command -v zenoh-bridge-ros2dds >/dev/null && zenoh-bridge-ros2dds --version || { warn "zenoh-bridge-ros2dds がありません"; ng=1; }
  [ -f /opt/ros/humble/setup.bash ] || { warn "ROS2 Humble がありません"; ng=1; }
  [ -x /usr/local/bin/node ] && /usr/local/bin/node --version || { warn "Node.js がありません"; ng=1; }
  [ -x "$HOME/.local/bin/uv" ] && "$HOME/.local/bin/uv" --version || { warn "uv がありません"; ng=1; }
  if [ "$ng" -ne 0 ]; then
    warn "確認で問題が見つかりました。上のメッセージを確認してください"
    return 1
  fi
  cat <<'EOF'

インストールが完了しました。続けて、手順書の「後半: 手動設定」を順に実施してください。
  3. 時刻同期設定（/etc/chrony/chrony.conf の同期先）
  4. Avahi設定（/etc/avahi/avahi-daemon.conf のインタフェース）
  5. CANインターフェースの起動時自動設定（/etc/rc.local）
  6. 環境変数設定（~/indy.env、~/.bashrc）
  7. ソフトウェアのビルド
  8. 起動スクリプトの準備
  9. 地図の作成
EOF
}

# ---------------------------------------------------------------
# main
# ---------------------------------------------------------------
if [ "$(id -u)" -eq 0 ]; then
  echo "root では実行しないでください。sudo できる一般ユーザで実行してください。" >&2
  exit 1
fi
if [ "$(. /etc/os-release && echo "$VERSION_ID")" != "22.04" ]; then
  warn "Ubuntu 22.04 で実行してください"
fi

steps=()
for a in "$@"; do
  case "$a" in
    -h|--help) usage; exit 0 ;;
    *)
      if [[ " ${ALL_STEPS[*]} " == *" $a "* ]]; then
        steps+=("$a")
      else
        echo "不明な手順名です: $a" >&2; usage >&2; exit 1
      fi ;;
  esac
done
[ ${#steps[@]} -eq 0 ] && steps=("${DEFAULT_STEPS[@]}")

# sudo の認証を更新し続ける
sudo -v
( while true; do sudo -n true; sleep 60; done ) 2>/dev/null &
SUDO_KEEPALIVE=$!
trap 'kill "$SUDO_KEEPALIVE" 2>/dev/null' EXIT

for s in "${steps[@]}"; do
  "step_$s"
done

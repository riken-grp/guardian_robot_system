# guardian_urdf
アーム（Guardian）のURDFモデルと、表示用のSTLメッシュを提供する。
ノードは持たず、モデルファイルのみをインストールする。

## ビルド方法
本パッケージは環境変数 `ON_ROBOT` が `1` の場合のみビルドされる。それ以外の場合はスキップされる。
```
export ON_ROBOT=1
colcon build --packages-select guardian_urdf
```

## 提供するファイル
|パス|概要|
|---|---|
|urdf/arm.urdf|アーム1本分のURDFモデル|
|visual/*.STL|リンク表示用メッシュ|
|visual/ROBSTRIDE02.stl|Robstride02モータの表示用メッシュ|

インストール先は `share/guardian_urdf/` で、URDF内からは
`package://guardian_urdf/visual/<ファイル名>` の形で参照される。

## 関節構成
`base_link` を根として、以下の4つの可動関節を持つ。

|関節名|概要|
|---|---|
|bracket_arm_a_joint|第1関節|
|bracket_arm_b_joint|第2関節|
|bracket_arm_c_joint|第3関節|
|bracket_arm_d_joint|第4関節|

上記以外の `*_fixed_joint` は固定関節である。
関節名は arm_motor_control の `joint_names` パラメータおよび
arm_moveit_driver の `config/guardian.srdf` と一致している必要がある。

## 利用箇所
arm_moveit_driver の `config/guardian.urdf.xacro` から参照され、MoveItのロボットモデルとして使用される。

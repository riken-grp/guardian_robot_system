// Robstride02 モータのハードウェア設定ツール
//   ゼロ点設定（アーム・首）、CAN ID の変更、モータの検索・状態表示を行う。
//
// ビルド: 同じディレクトリの build.sh を実行する（実行ファイルは tools/other_tools/ に置かれる）。
// 使い方: robstride02_tool --help
//
// ※arm_motor_control / motor_control が動いている間は実行しない（同じ CAN バスに命令が混ざるため。動いていれば中止する）。

#include "../src/Robstride02.hpp"

#include <cstdio>
#include <cstdlib>
#include <map>
#include <string>
#include <vector>

namespace {

struct Part {
    std::string description;          // 部位の説明
    std::string zero_pose;            // ゼロ点を設定するときの姿勢
    std::map<int, std::string> joints;  // CAN ID → 関節名
};

// 既定の CAN インタフェースと関節（arm_motor_control.yaml / motor_control.yaml に合わせる）
const std::map<std::string, Part> kParts = {
    {"rightarm", {"右腕", "手のひらを下に向けて、腕を真横に伸ばした姿勢",
                  {{1, "bracket_arm_a_joint"}, {2, "bracket_arm_b_joint"},
                   {3, "bracket_arm_c_joint"}, {4, "bracket_arm_d_joint"}}}},
    {"leftarm",  {"左腕", "手のひらを下に向けて、腕を真横に伸ばした姿勢",
                  {{1, "bracket_arm_a_joint"}, {2, "bracket_arm_b_joint"},
                   {3, "bracket_arm_c_joint"}, {4, "bracket_arm_d_joint"}}}},
    {"neck",     {"首・胴体", "首と胴体を正面に向けて、直立させた姿勢",
                  {{1, "body_pitch_joint"}, {2, "neck_yaw_joint"}, {3, "neck_pitch_joint"}}}},
};

constexpr int kMinId = 1;
constexpr int kMaxId = 127;

void usage(const char* prog)
{
    std::printf(
        "使い方:\n"
        "  %s scan     <CAN I/F>                    応答するモータの CAN ID を探す\n"
        "  %s show     <CAN I/F> [CAN ID ...]       位置・電圧・温度を表示する\n"
        "  %s set-zero <CAN I/F> [CAN ID ...]       現在の位置をゼロ点に設定する\n"
        "  %s set-id   <CAN I/F> <今の ID> <新しい ID>  CAN ID を変更する\n"
        "\n"
        "CAN I/F: rightarm（右腕）、leftarm（左腕）、neck（首・胴体）など\n"
        "CAN ID を省略した場合は、その CAN I/F の全関節（右腕・左腕: 1〜4、首: 1〜3）を対象にする。\n"
        "※arm_motor_control / motor_control を停止してから実行すること。\n"
        "※scan / show / set-zero は、対象のモータに停止（disable）命令を送る。アームはトルクが抜けるので手で支えること。\n",
        prog, prog, prog, prog);
}

bool parse_id(const std::string& s, int& id)
{
    char* end = nullptr;
    long v = std::strtol(s.c_str(), &end, 0);  // 10 進 / 0x 付き 16 進
    if (end == s.c_str() || *end != '\0' || v < kMinId || v > kMaxId) {
        std::fprintf(stderr, "error: CAN ID が不正です: %s（%d〜%d）\n", s.c_str(), kMinId, kMaxId);
        return false;
    }
    id = static_cast<int>(v);
    return true;
}

std::string joint_name(const std::string& can_if, int id)
{
    auto p = kParts.find(can_if);
    if (p == kParts.end()) return "";
    auto j = p->second.joints.find(id);
    return j == p->second.joints.end() ? "" : j->second;
}

bool controller_running()
{
    // ROS のモータ制御ノードが動いていると、同じ CAN バスに命令が混ざる
    // （[a] / [m] は、pgrep を呼ぶ sh 自身のコマンド行に一致させないための書き方）
    return std::system("pgrep -f 'lib/[a]rm_motor_control/arm_motor_control|lib/[m]otor_control/motor_control' "
                       ">/dev/null 2>&1") == 0;
}

bool confirm(const std::string& question)
{
    std::printf("%s [y/N]: ", question.c_str());
    std::fflush(stdout);
    char buf[16] = {0};
    if (!std::fgets(buf, sizeof(buf), stdin)) return false;
    return buf[0] == 'y' || buf[0] == 'Y';
}

// 対象の CAN ID を決める（省略時は既定の全関節）
bool resolve_ids(const std::string& can_if, int argc, char* argv[], int first, std::vector<int>& ids)
{
    for (int i = first; i < argc; i++) {
        int id;
        if (!parse_id(argv[i], id)) return false;
        ids.push_back(id);
    }
    if (ids.empty()) {
        auto p = kParts.find(can_if);
        if (p == kParts.end()) {
            std::fprintf(stderr, "error: %s の既定の CAN ID はありません。CAN ID を指定してください\n", can_if.c_str());
            return false;
        }
        for (const auto& j : p->second.joints) ids.push_back(j.first);
    }
    return true;
}

// 指定した全モータが応答するか確認する
bool check_active(Robstride02Driver& motor, const std::string& can_if, const std::vector<int>& ids)
{
    bool ok = true;
    for (int id : ids) {
        if (!motor.isActive(id)) {
            std::fprintf(stderr, "error: %s の CAN ID %d のモータが応答しません（電源・配線・CAN ID を確認してください）\n",
                         can_if.c_str(), id);
            ok = false;
        }
    }
    return ok;
}

int cmd_scan(Robstride02Driver& motor, const std::string& can_if)
{
    std::printf("%s の CAN ID %d〜%d を検索します...\n", can_if.c_str(), kMinId, kMaxId);
    int found = 0;
    for (int id = kMinId; id <= kMaxId; id++) {
        if (motor.isActive(id)) {
            std::string name = joint_name(can_if, id);
            std::printf("  CAN ID %3d (0x%02X)  %s\n", id, id, name.c_str());
            found++;
        }
    }
    std::printf("%d 台見つかりました。\n", found);
    return found > 0 ? 0 : 1;
}

int cmd_show(Robstride02Driver& motor, const std::string& can_if, const std::vector<int>& ids)
{
    int ret = 0;
    for (int id : ids) {
        std::string name = joint_name(can_if, id);
        if (!motor.isActive(id)) {
            std::printf("CAN ID %d %s: 応答なし\n", id, name.c_str());
            ret = 1;
            continue;
        }
        std::printf("CAN ID %d %s: 位置 %+.3f rad, 電圧 %.1f V, 温度 %.1f ℃\n",
                    id, name.c_str(), motor.getPosition(id), motor.getVbus(id), motor.getTemp(id));
    }
    return ret;
}

int cmd_set_zero(Robstride02Driver& motor, const std::string& can_if, const std::vector<int>& ids)
{
    if (!check_active(motor, can_if, ids)) return 1;

    auto p = kParts.find(can_if);
    std::printf("\n");
    if (p != kParts.end()) {
        std::printf("対象: %s（%s）\n", p->second.description.c_str(), can_if.c_str());
        std::printf("姿勢: %s\n", p->second.zero_pose.c_str());
    } else {
        std::printf("対象: %s\n", can_if.c_str());
    }
    std::printf("現在の位置:\n");
    for (int id : ids) {
        std::printf("  CAN ID %d %s: %+.3f rad\n", id, joint_name(can_if, id).c_str(), motor.getPosition(id));
    }
    std::printf("\n上の姿勢になるよう手で押さえたまま、続けてください。\n");
    if (!confirm("現在の位置をゼロ点に設定しますか？")) {
        std::printf("中止しました。\n");
        return 1;
    }

    for (int id : ids) {
        motor.enable(id);
        motor.setMechPosZero(id);
        motor.disable(id);
    }

    // 応答が無いと位置は 0 と読めてしまうため、先に応答を確認する
    int ret = 0;
    std::printf("設定後の位置（0 付近になっていれば成功）:\n");
    for (int id : ids) {
        if (!motor.isActive(id)) {
            std::printf("  CAN ID %d %s: 応答なし（設定できたか不明）\n", id, joint_name(can_if, id).c_str());
            ret = 1;
            continue;
        }
        std::printf("  CAN ID %d %s: %+.3f rad\n", id, joint_name(can_if, id).c_str(), motor.getPosition(id));
    }
    std::printf("※モータの電源を入れ直したあと、show で位置が保たれていることを確認してください。\n");
    return ret;
}

int cmd_set_id(Robstride02Driver& motor, const std::string& can_if, int old_id, int new_id)
{
    if (old_id == new_id) {
        std::fprintf(stderr, "error: 今の ID と新しい ID が同じです\n");
        return 1;
    }
    if (!motor.isActive(old_id)) {
        std::fprintf(stderr, "error: %s の CAN ID %d のモータが応答しません\n", can_if.c_str(), old_id);
        return 1;
    }
    if (motor.isActive(new_id)) {
        std::fprintf(stderr, "error: %s には CAN ID %d のモータが既にあります\n", can_if.c_str(), new_id);
        return 1;
    }
    std::printf("※同じ CAN バスに同じ ID のモータが複数あると区別できません。変更するモータだけを接続しておくと安全です。\n");
    if (!confirm(can_if + " の CAN ID " + std::to_string(old_id) + " を " + std::to_string(new_id) + " に変更しますか？")) {
        std::printf("中止しました。\n");
        return 1;
    }

    motor.setCanId(old_id, new_id);
    usleep(100 * 1000);

    if (!motor.isActive(new_id)) {
        std::fprintf(stderr, "error: CAN ID %d で応答がありません。scan で確認してください\n", new_id);
        return 1;
    }
    std::printf("CAN ID を %d に変更しました。\n", new_id);
    std::printf("※モータの電源を入れ直したあと、scan で新しい ID が保たれていることを確認してください。\n");
    std::printf("※arm_motor_control.yaml / motor_control.yaml の can_id と合っているか確認してください。\n");
    return 0;
}

}  // namespace

int main(int argc, char* argv[])
{
    if (argc < 3) {
        usage(argv[0]);
        return (argc >= 2 && (std::string(argv[1]) == "-h" || std::string(argv[1]) == "--help")) ? 0 : 1;
    }
    const std::string cmd = argv[1];
    const std::string can_if = argv[2];

    if (cmd != "scan" && cmd != "show" && cmd != "set-zero" && cmd != "set-id") {
        std::fprintf(stderr, "error: 不明なコマンドです: %s\n\n", cmd.c_str());
        usage(argv[0]);
        return 1;
    }

    // 引数を先に検査する（CAN を開く前に誤りを知らせるため）
    int old_id = 0, new_id = 0;
    std::vector<int> ids;
    if (cmd == "scan") {
        if (argc != 3) { usage(argv[0]); return 1; }
    } else if (cmd == "set-id") {
        if (argc != 5) { usage(argv[0]); return 1; }
        if (!parse_id(argv[3], old_id) || !parse_id(argv[4], new_id)) return 1;
    } else {
        if (!resolve_ids(can_if, argc, argv, 3, ids)) return 1;
    }

    if (controller_running()) {
        std::fprintf(stderr, "error: arm_motor_control / motor_control が動いています。停止してから実行してください\n");
        return 1;
    }

    Robstride02Driver motor;
    if (motor.initSocket(can_if) < 0) {
        std::fprintf(stderr, "error: CAN インタフェース %s を開けません（ip link show %s で確認してください）\n",
                     can_if.c_str(), can_if.c_str());
        return 1;
    }
    motor.clearBuffer();

    int ret;
    if (cmd == "scan") {
        ret = cmd_scan(motor, can_if);
    } else if (cmd == "set-id") {
        ret = cmd_set_id(motor, can_if, old_id, new_id);
    } else if (cmd == "show") {
        ret = cmd_show(motor, can_if, ids);
    } else {
        ret = cmd_set_zero(motor, can_if, ids);
    }

    motor.closeSocket();
    return ret;
}

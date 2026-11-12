import subprocess
import re
import time
import sys

def get_wifi_signal_info(interface):
    try:
        # iwconfig <interface> コマンドを実行
        result = subprocess.run(['iwconfig', interface], capture_output=True, text=True, check=True)
        output = result.stdout

        # 正規表現で Link Quality と Signal level を抽出
        match = re.search(r'Link Quality=(\d+)/(\d+)\s+Signal level=(-?\d+)\s*dBm', output)

        if match:
            link_quality = int(match.group(1))
            link_quality_max = int(match.group(2))
            signal_level = int(match.group(3))
            return {
                "interface": interface,
                "link_quality": link_quality,
                "link_quality_max": link_quality_max,
                "signal_level_dBm": signal_level
            }
        else:
            return {"error": f"{interface} に Wi-Fi 情報が見つかりませんでした。"}

    except subprocess.CalledProcessError as e:
        return {"error": f"iwconfig 実行エラー: {e}"}
    except Exception as e:
        return {"error": f"予期せぬエラー: {e}"}

def main():
    if len(sys.argv) < 2:
        print("使用法: python wifi_monitor.py <interface_name>")
        sys.exit(1)

    interface = sys.argv[1]

    print(f"[INFO] モニタリング対象: {interface}")
    try:
        while True:
            info = get_wifi_signal_info(interface)
            print(info)
            time.sleep(10)
    except KeyboardInterrupt:
        print("\n[INFO] 終了しました。")

if __name__ == "__main__":
    main()

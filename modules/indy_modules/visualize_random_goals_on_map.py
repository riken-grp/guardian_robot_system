#!/usr/bin/env python3
# /// script
# dependencies = [
#   "pymongo",
#   "numpy",
#   "matplotlib",
# ]
# ///
"""マップを可視化してkeepoutの意味を確認"""

import os
import sys
import numpy as np
from pymongo import MongoClient
import matplotlib.pyplot as plt

# MongoDB接続
env_mongo_uri = os.getenv("MONGO_URI")
env_mongo_port = os.getenv("MONGO_PORT")

if env_mongo_uri is None:
    print("error: failed to get mongo_uri")
    sys.exit(1)

if env_mongo_port is None:
    print("error: failed to get mongo_port")
    sys.exit(1)

client = MongoClient(f"mongodb://{env_mongo_uri}:{env_mongo_port}")
db = client["tBlackBoard"]
maps_collection = db["maps"]

# データ取得
map_doc = maps_collection.find_one({"name": "map"})
keepout_doc = maps_collection.find_one({"name": "keepout"})

map_info = map_doc["info"]
map_data = np.array(map_doc["data"], dtype=np.int8).reshape(map_info["height"], map_info["width"])
keepout_info = keepout_doc["info"]
keepout_data = np.array(keepout_doc["data"], dtype=np.int8).reshape(keepout_info["height"], keepout_info["width"])

# 最近生成された座標を取得
actions = db["Actions"]
recent = list(actions.find({"command": "navigation"}).sort("inserted", -1).limit(5))

# 座標をピクセル位置に変換
origin_x = map_info['origin']['position']['x']
origin_y = map_info['origin']['position']['y']
resolution = map_info['resolution']

positions = []
for action in recent:
    nav = action['option']['navigation']
    x, y = nav[0], nav[1]
    px = int((x - origin_x) / resolution)
    py = int((y - origin_y) / resolution)
    positions.append((px, py, x, y))

# 可視化
fig, axes = plt.subplots(2, 2, figsize=(16, 12))

# Map data
axes[0, 0].imshow(map_data, cmap='gray_r', vmin=-1, vmax=100, origin='lower')
axes[0, 0].set_title('Map Data\n(white=free/0, black=occupied/100, gray=unknown/-1)')
for i, (px, py, x, y) in enumerate(positions, 1):
    axes[0, 0].plot(px, py, 'ro', markersize=10)
    axes[0, 0].text(px+10, py+10, f'{i}', color='red', fontsize=12, fontweight='bold')
axes[0, 0].grid(True, alpha=0.3)

# Keepout data
axes[0, 1].imshow(keepout_data, cmap='gray_r', vmin=0, vmax=100, origin='lower')
axes[0, 1].set_title('Keepout Data\n(Interpretation 1: white=allowed/100, black=restricted/0)')
for i, (px, py, x, y) in enumerate(positions, 1):
    axes[0, 1].plot(px, py, 'ro', markersize=10)
    axes[0, 1].text(px+10, py+10, f'{i}', color='red', fontsize=12, fontweight='bold')
axes[0, 1].grid(True, alpha=0.3)

# Keepout inverted interpretation
axes[1, 0].imshow(keepout_data, cmap='gray', vmin=0, vmax=100, origin='lower')
axes[1, 0].set_title('Keepout Data (INVERTED)\n(Interpretation 2: black=allowed/100, white=restricted/0)')
for i, (px, py, x, y) in enumerate(positions, 1):
    axes[1, 0].plot(px, py, 'ro', markersize=10)
    axes[1, 0].text(px+10, py+10, f'{i}', color='red', fontsize=12, fontweight='bold')
axes[1, 0].grid(True, alpha=0.3)

# Combined: Map free AND Keepout (CORRECTED)
combined1 = np.zeros_like(map_data, dtype=float)
combined1[(map_data == 0) & (keepout_data == 0)] = 1.0  # 修正：両方OKの場所（green）
combined1[(map_data == 0) & (keepout_data != 0)] = 0.5  # mapは通行可能だがkeepout制限あり（yellow）
axes[1, 1].imshow(combined1, cmap='RdYlGn', vmin=0, vmax=1, origin='lower')
axes[1, 1].set_title('Combined (Corrected Logic)\n(green=navigable [map=0,keepout=0], yellow=keepout restricted, red=occupied)')
for i, (px, py, x, y) in enumerate(positions, 1):
    axes[1, 1].plot(px, py, 'bo', markersize=10)
    axes[1, 1].text(px+10, py+10, f'{i}', color='blue', fontsize=12, fontweight='bold',
                   bbox=dict(boxstyle='round', facecolor='white', alpha=0.7))
axes[1, 1].grid(True, alpha=0.3)

# 座標情報を表示
info_text = "Generated Positions:\n"
for i, (px, py, x, y) in enumerate(positions, 1):
    info_text += f"{i}. World({x:.1f}, {y:.1f}) Pixel({px}, {py})\n"
    info_text += f"   map={map_data[py, px]}, keepout={keepout_data[py, px]}\n"

fig.text(0.02, 0.02, info_text, fontsize=10, family='monospace',
         bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

plt.tight_layout(rect=[0, 0.15, 1, 1])
plt.savefig('map_keepout_visualization.png', dpi=150, bbox_inches='tight')
print("Saved visualization to: map_keepout_visualization.png")
print("\n" + info_text)

# keepoutの値の意味を推測
print("\n=== Keepout Interpretation Analysis ===")
print("Based on the visualization:")
print("- If RED dots appear in GREEN areas in 'Combined' plot: Current logic is CORRECT")
print("- If RED dots appear in YELLOW/RED areas: Keepout interpretation may be INVERTED")
print("\nCheck the saved image to verify which interpretation makes sense.")

client.close()

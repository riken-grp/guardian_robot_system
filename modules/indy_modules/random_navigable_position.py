#!/usr/bin/env python3
# /// script
# dependencies = [
#   "pymongo",
#   "numpy",
#   "pillow",
#   "zstandard",
# ]
# ///
"""
MongoDBのtBlackBoard.mapsコレクションから地図データを取得し、
通行可能な座標をランダムに選択するプログラム。

Usage:
    python3 random_navigable_position.py [--host HOST] [--port PORT]
"""

import argparse
import math
import os
import random
from datetime import datetime
from typing import Optional, Tuple

import numpy as np
import zstandard as zstd
from PIL import Image
from pymongo import MongoClient


class NavigablePositionSelector:
    """通行可能な位置をランダムに選択するクラス"""

    def __init__(self, host: str = "", port: int = 9130):
        """
        Args:
            host: MongoDBのホスト名
            port: MongoDBのポート番号
        """
        self.client = MongoClient(f"mongodb://{host}:{port}")
        self.db = self.client["tBlackBoard"]
        self.maps_collection = self.db["maps"]

        # マップデータを取得
        self.map_data = None
        self.keepout_data = None
        self.resolution = None
        self.origin = None
        self._load_maps()

    def _load_maps(self):
        """MongoDBからマップとkeepoutデータを読み込む"""
        # mapデータを取得
        map_doc = self.maps_collection.find_one({"name": "map"})
        if map_doc is None:
            raise ValueError("Map data not found in database")

        # keepoutデータを取得
        keepout_doc = self.maps_collection.find_one({"name": "keepout"})
        if keepout_doc is None:
            raise ValueError("Keepout data not found in database")

        # 画像データをデコード
        self.map_data = self._decode_image(map_doc)
        self.keepout_data = self._decode_image(keepout_doc)

        # メタデータを取得
        info = map_doc.get("info", {})
        self.resolution = info.get("resolution", 0.05)  # デフォルト: 5cm/pixel
        self.origin = info.get("origin", [0.0, 0.0, 0.0])  # [x, y, theta]
        self.width = info.get("width", self.map_data.shape[1])
        self.height = info.get("height", self.map_data.shape[0])

        print(
            f"Map loaded: shape={self.map_data.shape}, resolution={self.resolution}m/pixel"
        )
        print(f"Origin: {self.origin}")

    def _decode_image(self, doc: dict) -> np.ndarray:
        """
        MongoDBドキュメントから画像データをデコード

        Args:
            doc: MongoDBドキュメント

        Returns:
            numpy array (H, W)
        """
        # dataはintのリストとして保存されている
        data_list = doc.get("data")
        if data_list is None:
            raise ValueError("Image data not found in document")

        # infoから画像サイズを取得
        info = doc.get("info", {})
        width = info.get("width")
        height = info.get("height")

        if width is None or height is None:
            raise ValueError("Width or height not found in document info")

        # numpy配列に変換してreshape
        # 占有グリッドマップでは-1（未知）を含む可能性があるのでint8を使用
        img_array = np.array(data_list, dtype=np.int8).reshape(height, width)

        return img_array

    def _pixel_to_world(self, px: int, py: int) -> Tuple[float, float]:
        """
        ピクセル座標を世界座標に変換

        Args:
            px: ピクセルのx座標
            py: ピクセルのy座標

        Returns:
            (world_x, world_y): 世界座標
        """
        # 画像座標系: 左下が原点、右がx正、上がy正
        # 世界座標系: originを基準とした座標
        # originはdictのネスト構造
        origin_x = self.origin["position"]["x"]
        origin_y = self.origin["position"]["y"]

        world_x = origin_x + px * self.resolution
        world_y = origin_y + py * self.resolution

        return world_x, world_y

    def _is_navigable(self, px: int, py: int, margin: int = 2) -> bool:
        """
        指定されたピクセル座標が通行可能かどうか判定

        Args:
            px: ピクセルのx座標
            py: ピクセルのy座標
            margin: 周辺のマージン（ピクセル数）

        Returns:
            True if navigable, False otherwise
        """
        h, w = self.map_data.shape[:2]

        # 範囲チェック
        if px < margin or px >= w - margin or py < margin or py >= h - margin:
            return False

        # 周辺もチェック（ロボットのサイズを考慮）
        for dy in range(-margin, margin + 1):
            for dx in range(-margin, margin + 1):
                ny, nx = py + dy, px + dx
                if 0 <= ny < h and 0 <= nx < w:
                    m_val = self.map_data[ny, nx]
                    k_val = self.keepout_data[ny, nx]

                    # mapデータのチェック
                    # 0=free（通行可能）, 100=occupied（障害物）, -1=unknown（未知）
                    if m_val != 0:  # 0以外（障害物または未知）は通行不可
                        return False

                    # keepoutデータのチェック
                    # 0=通行可能（制限なし）, 100=keepout（進入禁止）
                    if k_val != 0:  # 0以外（keepoutエリア）は通行不可
                        return False

        return True

    def _find_nearest_obstacle(
        self, px: int, py: int, max_search_radius: int = 50
    ) -> Optional[Tuple[int, int]]:
        """
        最寄りの通行不可能な点を探す

        Args:
            px: 起点のピクセルx座標
            py: 起点のピクセルy座標
            max_search_radius: 最大探索半径（ピクセル）

        Returns:
            (obstacle_px, obstacle_py): 最寄りの障害物のピクセル座標、見つからなければNone
        """
        h, w = self.map_data.shape[:2]

        # スパイラル探索
        for radius in range(1, max_search_radius + 1):
            for angle in np.linspace(0, 2 * np.pi, radius * 8, endpoint=False):
                ox = int(px + radius * np.cos(angle))
                oy = int(py + radius * np.sin(angle))

                if 0 <= ox < w and 0 <= oy < h:
                    if not self._is_navigable(ox, oy, margin=0):
                        return (ox, oy)

        return None

    def _calculate_yaw_away_from_point(
        self, from_x: float, from_y: float, obstacle_x: float, obstacle_y: float
    ) -> float:
        """
        障害物に背を向ける方向のyawを計算

        Args:
            from_x, from_y: 起点の世界座標
            obstacle_x, obstacle_y: 障害物の世界座標

        Returns:
            yaw: 背を向ける方向のyaw角度（ラジアン）
        """
        # 障害物への方向を計算
        dx = obstacle_x - from_x
        dy = obstacle_y - from_y

        # 障害物への角度
        angle_to_obstacle = math.atan2(dy, dx)

        # 反対方向を向く（180度回転）
        yaw = angle_to_obstacle + math.pi

        # -π ~ π の範囲に正規化
        while yaw > math.pi:
            yaw -= 2 * math.pi
        while yaw < -math.pi:
            yaw += 2 * math.pi

        return yaw

    def get_random_navigable_position(
        self, margin: int = 5
    ) -> Tuple[float, float, float]:
        """
        通行可能な座標をランダムに選択し、最寄りの障害物に背を向けるyawを計算

        Args:
            margin: ロボットのサイズを考慮したマージン（ピクセル）

        Returns:
            (x, y, yaw): 世界座標とyaw角度
        """
        h, w = self.map_data.shape[:2]

        # 通行可能な候補点をランダムに探索
        max_attempts = 10000
        for attempt in range(max_attempts):
            px = random.randint(margin, w - margin - 1)
            py = random.randint(margin, h - margin - 1)

            if self._is_navigable(px, py, margin):
                # 世界座標に変換
                world_x, world_y = self._pixel_to_world(px, py)

                # 最寄りの障害物を探す
                obstacle_pixel = self._find_nearest_obstacle(px, py)

                if obstacle_pixel is not None:
                    obstacle_x, obstacle_y = self._pixel_to_world(
                        obstacle_pixel[0], obstacle_pixel[1]
                    )
                    yaw = self._calculate_yaw_away_from_point(
                        world_x, world_y, obstacle_x, obstacle_y
                    )
                else:
                    # 障害物が見つからない場合はランダムな方向
                    yaw = random.uniform(-math.pi, math.pi)

                return world_x, world_y, yaw

        raise RuntimeError(
            f"Could not find navigable position after {max_attempts} attempts"
        )


def main():
    env_mongo_uri = os.getenv("MONGO_URI")
    env_mongo_port = os.getenv("MONGO_PORT")

    if env_mongo_uri is None:
        print("error: failed to get mongo_uri")
        return

    if env_mongo_port is None:
        print("error: failed to get mongo_port")
        return

    parser = argparse.ArgumentParser(
        description="MongoDBからマップを読み込み、通行可能な座標をランダムに選択"
    )
    parser.add_argument("--host", default=env_mongo_uri, help="MongoDB host")
    parser.add_argument("--port", type=int, default=int(env_mongo_port), help="MongoDB port")
    parser.add_argument(
        "--margin", type=int, default=5, help="Margin in pixels for robot size"
    )
    parser.add_argument(
        "--num-samples",
        type=int,
        default=5,
        help="Number of random positions to generate",
    )
    parser.add_argument(
        "--mongo",
        help="MongoDB URI for writing results (e.g., mongodb://example.local:9130)",
    )
    parser.add_argument(
        "--actor",
        default=os.getenv("ROBOT_NAME"),
        help="Robot name written as 'actor' with --mongo (default: $ROBOT_NAME)",
    )

    args = parser.parse_args()

    if args.mongo and not args.actor:
        print("error: --actor or ROBOT_NAME is required with --mongo")
        return

    # NavigablePositionSelectorを初期化
    selector = NavigablePositionSelector(host=args.host, port=args.port)

    # MongoDB書き込み用クライアント（--mongoオプションが指定された場合）
    write_client = None
    actions_collection = None
    if args.mongo:
        write_client = MongoClient(args.mongo)
        db = write_client["tBlackBoard"]
        actions_collection = db["Actions"]
        print(f"Will write results to MongoDB: {args.mongo}/tBlackBoard/Actions")

    # ランダムな通行可能位置を生成
    print(f"\nGenerating {args.num_samples} random navigable positions:")
    print("-" * 60)

    results = []
    for i in range(args.num_samples):
        x, y, yaw = selector.get_random_navigable_position(margin=args.margin)
        print(f"Position {i+1}:")
        print(f"  World coordinates: x={x:.3f}m, y={y:.3f}m")
        print(
            f"  Yaw (away from nearest obstacle): {yaw:.3f} rad ({math.degrees(yaw):.1f}°)"
        )

        # MongoDBに書き込む場合
        if actions_collection is not None:
            doc = {
                "actor": args.actor,
                "condition": {"type": "none"},
                "status": "waiting",
                "command": "navigation",
                "option": {
                    "type": "normal",
                    "navigation": [float(x), float(y), float(yaw)],
                },
                "inserted": datetime.now(),
            }
            result = actions_collection.insert_one(doc)
            inserted_id = result.inserted_id
            print(f"  Written to MongoDB: {inserted_id}")
            results.append(inserted_id)

        print()

    # MongoDB接続をクローズ
    if write_client:
        print(f"\nSuccessfully wrote {len(results)} positions to MongoDB")
        for i, doc_id in enumerate(results, 1):
            print(
                f"  Position {i}: http://{args.host}:9131/db/tBlackBoard/Actions/%22{doc_id}%22"
            )
        write_client.close()


if __name__ == "__main__":
    main()

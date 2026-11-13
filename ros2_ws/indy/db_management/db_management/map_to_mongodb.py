import rclpy
from nav_msgs.msg import OccupancyGrid
from pymongo import MongoClient
from rclpy import qos

from .mongo_node_base import MongoDBNode


class Map2MongoDB(MongoDBNode):
    def __init__(self):
        super().__init__("map_to_mongodb")
        self.map = None
        self.keepout = None
        qos_profile = qos.QoSProfile(
            depth=10, durability=qos.DurabilityPolicy.TRANSIENT_LOCAL
        )
        self.map_sub = self.create_subscription(
            OccupancyGrid, "/map", self.map_callback, qos_profile
        )
        self.keepout_sub = self.create_subscription(
            OccupancyGrid, "/keepout_filter_mask", self.keepout_callback, qos_profile
        )
        mongo_uri, mongo_port, dbname = self._init_mongo_params("")
        # mongo_uri はホスト名でも mongodb:// 形式の URI でも受け付ける
        # (他ノードと同じく MongoClient(host, port) で接続する)
        self.client = MongoClient(mongo_uri, mongo_port)
        self.db = self.client[dbname]

    def map_callback(self, msg):
        self.store_in_mongodb(msg, "map")

    def keepout_callback(self, msg):
        self.store_in_mongodb(msg, "keepout")

    def store_in_mongodb(self, map_msg, name):
        self.db.maps.update_one(
            {"name": name},
            {
                "$set": {
                    "info": {
                        "width": map_msg.info.width,
                        "height": map_msg.info.height,
                        "resolution": map_msg.info.resolution,
                        "origin": {
                            "position": {
                                "x": map_msg.info.origin.position.x,
                                "y": map_msg.info.origin.position.y,
                                "z": map_msg.info.origin.position.z,
                            },
                            "orientation": {
                                "x": map_msg.info.origin.orientation.x,
                                "y": map_msg.info.origin.orientation.y,
                                "z": map_msg.info.origin.orientation.z,
                                "w": map_msg.info.origin.orientation.w,
                            },
                        },
                    },
                    "data": list(map_msg.data),
                }
            },
            upsert=True,
        )


def main(args=None):
    rclpy.init(args=args)
    node = Map2MongoDB()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()

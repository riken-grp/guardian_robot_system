from rclpy.node import Node


class MongoDBNode(Node):
    """Base class for ROS2 nodes that connect to MongoDB."""

    def _init_mongo_params(self, default_uri: str = ""):
        """Declare and retrieve MongoDB connection parameters.

        Args:
            default_uri: Default MongoDB host URI.

        Returns:
            tuple: (mongo_uri, mongo_port, dbname)
        """
        self.declare_parameter("mongo_uri", default_uri)
        self.declare_parameter("mongo_port", 9010)
        self.declare_parameter("dbname", "tBlackBoard")
        mongo_uri = self.get_parameter("mongo_uri").value
        mongo_port = self.get_parameter("mongo_port").value
        dbname = self.get_parameter("dbname").value
        return mongo_uri, mongo_port, dbname

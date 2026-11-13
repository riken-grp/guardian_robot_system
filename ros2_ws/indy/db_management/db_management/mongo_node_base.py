from rclpy.node import Node


class MongoDBNode(Node):
    """Base class for ROS2 nodes that connect to MongoDB."""

    DEFAULT_MONGO_PORT = 9010
    DEFAULT_DBNAME = "tBlackBoard"

    def _init_mongo_params(self, default_uri: str = ""):
        """Declare and retrieve MongoDB connection parameters.

        launch ファイルから空文字の mongo_uri や 0/1 の mongo_port が渡されると
        ノードのデフォルト値が上書きされて MongoClient の生成に失敗するため，
        そのような「未指定」相当の値はデフォルト値にフォールバックする．

        Args:
            default_uri: Default MongoDB host URI.

        Returns:
            tuple: (mongo_uri, mongo_port, dbname)
        """
        self.declare_parameter("mongo_uri", default_uri)
        self.declare_parameter("mongo_port", self.DEFAULT_MONGO_PORT)
        self.declare_parameter("dbname", self.DEFAULT_DBNAME)
        mongo_uri = self.get_parameter("mongo_uri").value
        mongo_port = self.get_parameter("mongo_port").value
        dbname = self.get_parameter("dbname").value

        if mongo_uri is None or str(mongo_uri).strip() == "":
            mongo_uri = default_uri
        else:
            mongo_uri = str(mongo_uri).strip()

        try:
            mongo_port = int(mongo_port)
        except (TypeError, ValueError):
            mongo_port = 0
        if mongo_port <= 1:
            mongo_port = self.DEFAULT_MONGO_PORT

        if dbname is None or str(dbname).strip() == "":
            dbname = self.DEFAULT_DBNAME

        return mongo_uri, mongo_port, dbname

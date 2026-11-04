import pytest
import rclpy
from sensor_msgs.msg import CameraInfo, CompressedImage
import numpy as np
import cv2 # For encoding/decoding

# Import the ImageProcessingNode from the package
from scene_understanding.image_processing_node import ImageProcessingNode

@pytest.fixture(scope='module')
def ros_context():
    rclpy.init()
    yield
    rclpy.shutdown()

def test_image_processing_node_init(ros_context):
    node = ImageProcessingNode('test_node')
    assert node is not None
    assert node.get_name() == 'test_node'

    # Check if parameters are declared
    assert node.has_parameter('mongo_uri')
    assert node.has_parameter('mongo_port')

    node.destroy_node()

def test_image_processing_node_camera_info_callback(ros_context):
    node = ImageProcessingNode('test_camera_info_node', subscribe_image=False, subscribe_camera_info=True)

    # Simulate camera info message
    camera_info_msg = CameraInfo()
    camera_info_msg.k = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0] # Example intrinsic matrix
    camera_info_msg.d = [0.0, 0.0, 0.0, 0.0, 0.0] # Example distortion coefficients

    # Manually call the callback
    node._camera_info_callback(camera_info_msg)

    # Check if camera matrix and dist coeffs are set
    assert node.camera_matrix is not None
    assert node.dist_coeffs is not None
    assert np.array_equal(node.camera_matrix, np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], dtype=np.float32))
    assert np.array_equal(node.dist_coeffs, np.array([0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32))

    node.destroy_node()

def test_image_processing_node_process_image_not_implemented(ros_context, caplog):
    node = ImageProcessingNode('test_process_image_node', subscribe_image=False, subscribe_camera_info=False)
    
    # Mock header and image
    header = rclpy.time.Time().to_msg()
    cv_image = np.zeros((100, 100, 3), dtype=np.uint8)

    # Call process_image directly
    node.process_image(header, cv_image)

    # Check if a warning is logged
    assert "process_image method not implemented by child class." in caplog.text

    node.destroy_node()

def test_image_processing_node_publish_compressed_image(ros_context):
    node = ImageProcessingNode('test_publish_compressed_node', subscribe_image=False, subscribe_camera_info=False)
    
    # Create a mock publisher
    mock_publisher = node.create_publisher(CompressedImage, 'mock_topic', 1)
    
    # Mock header and image
    header = rclpy.time.Time().to_msg()
    cv_image = np.zeros((100, 100, 3), dtype=np.uint8)

    # Patch the publisher to capture published messages
    published_messages = []
    original_publish = mock_publisher.publish
    def mock_publish(msg):
        published_messages.append(msg)
    mock_publisher.publish = mock_publish

    # Call the publishing method
    node.publish_compressed_image(mock_publisher, header, cv_image)

    # Check if a message was published
    assert len(published_messages) == 1
    published_msg = published_messages[0]
    assert isinstance(published_msg, CompressedImage)
    assert published_msg.header == header
    assert published_msg.format == "jpeg"
    assert len(published_msg.data) > 0 # Should have image data

    # Verify content (decode and check size)
    decoded_img = cv2.imdecode(np.frombuffer(published_msg.data, np.uint8), cv2.IMREAD_COLOR)
    assert decoded_img.shape == cv_image.shape

    node.destroy_node()

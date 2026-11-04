import pytest
import cv2
import numpy as np
import os
import requests # To mock the download if needed
import dlib # Must import dlib to mock it

# Import the FaceDetector from the package
from scene_understanding.dlib_face_detector import FaceDetector

# Mock requests.get to prevent actual download during tests
@pytest.fixture(autouse=True)
def mock_requests_get(monkeypatch):
    def mock_get(url, *args, **kwargs):
        class MockResponse:
            def __init__(self):
                self.content = b"mock_model_data" * 10 # dummy data
        return MockResponse()
    monkeypatch.setattr(requests, "get", mock_get)

# Mock dlib.cnn_face_detection_model_v1 as it requires a real model file
@pytest.fixture(autouse=True)
def mock_dlib_model(monkeypatch):
    class MockRect:
        def __init__(self, left, top, right, bottom):
            self.left_val = left
            self.top_val = top
            self.right_val = right
            self.bottom_val = bottom
        def left(self): return self.left_val
        def top(self): return self.top_val
        def right(self): return self.right_val
        def bottom(self): return self.bottom_val

    class MockDetection:
        def __init__(self, rect):
            self.rect = rect
            self.confidence = 1.0

    class MockDlibModel:
        def __call__(self, img, upsample_num_times):
            # Simulate a detected face
            return [MockDetection(MockRect(10, 10, 50, 50))]
            
    def mock_cnn_face_detection_model_v1(model_file):
        return MockDlibModel()
    monkeypatch.setattr(dlib, "cnn_face_detection_model_v1", mock_cnn_face_detection_model_v1)

# Clean up the model file if it was created during testing
@pytest.fixture(scope="module", autouse=True)
def cleanup_model_file():
    model_file = "mmod_human_face_detector.dat"
    yield
    if os.path.exists(model_file):
        os.remove(model_file)

def test_dlib_face_detector_init():
    detector = FaceDetector()
    assert detector is not None

def test_dlib_face_detector_detect_faces():
    detector = FaceDetector()
    
    # Create a dummy image (e.g., a black image)
    dummy_image = np.zeros((100, 100, 3), dtype=np.uint8)
    
    detections = detector(dummy_image)
    
    assert len(detections) > 0
    assert hasattr(detections[0], 'rect')
    assert detections[0].rect.left() == 10
    assert detections[0].rect.top() == 10

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
import io


def generate_test_image():
    """Generate an in-memory image for testing."""
    img_io = io.BytesIO()
    image = Image.new("RGB", (100, 100), color=(255, 0, 0))  # Create a red image
    image.save(img_io, format="JPEG")
    img_io.seek(0)  # Reset file pointer to start
    return SimpleUploadedFile("test_image.jpg", img_io.getvalue(), content_type="image/jpeg")

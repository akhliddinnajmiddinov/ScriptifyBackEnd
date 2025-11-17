# renderers.py
from rest_framework.renderers import BaseRenderer

class EventStreamRenderer(BaseRenderer):
    media_type = 'text/event-stream'
    format = 'event-stream'
    charset = None  # SSE should not specify charset

    def render(self, data, accepted_media_type=None, renderer_context=None):
        """
        Convert Python objects to SSE-compatible bytes.
        Expected data format: list of dicts or generator of dicts
        """
        if data is None:
            return b""
        if isinstance(data, (bytes, str)):
            return data.encode() if isinstance(data, str) else data

        # If iterable (generator), yield as chunks
        if hasattr(data, '__iter__') and not isinstance(data, dict):
            for item in data:
                yield f"data: {item}\n\n".encode()
        else:
            return f"data: {data}\n\n".encode()

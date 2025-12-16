"""Detection pipeline for bugcam.

Required system packages:
- sudo apt install python3-gi python3-gi-cairo gir1.2-gstreamer-1.0
- sudo apt install hailo-all python3-numpy python3-opencv
- bugcam setup  (installs hailo_apps)
"""

import os
import sys


def check_dependencies():
    """Check that required system dependencies are available."""
    missing = []

    try:
        import gi
    except ImportError:
        missing.append("gi")

    try:
        import hailo
    except ImportError:
        missing.append("hailo")

    try:
        import hailo_apps
    except ImportError:
        missing.append("hailo_apps")

    try:
        import numpy
    except ImportError:
        missing.append("numpy")

    try:
        import cv2
    except ImportError:
        missing.append("cv2")

    if missing:
        print("Error: Missing required packages:", ", ".join(missing), file=sys.stderr)
        print(file=sys.stderr)
        print("Install missing packages:", file=sys.stderr)
        if "gi" in missing:
            print("  sudo apt install python3-gi python3-gi-cairo gir1.2-gstreamer-1.0", file=sys.stderr)
        if "hailo" in missing:
            print("  sudo apt install hailo-all", file=sys.stderr)
        if "hailo_apps" in missing:
            print("  bugcam setup", file=sys.stderr)
        if "numpy" in missing:
            print("  sudo apt install python3-numpy", file=sys.stderr)
        if "cv2" in missing:
            print("  sudo apt install python3-opencv", file=sys.stderr)
        print(file=sys.stderr)
        print("Run 'bugcam doctor' to check all dependencies.", file=sys.stderr)
        sys.exit(1)


def main():
    """Run the detection pipeline."""
    # Check dependencies first
    check_dependencies()

    # Now safe to import - dependencies verified
    import gi
    gi.require_version('Gst', '1.0')
    from gi.repository import Gst, GLib
    import numpy as np
    import cv2
    import hailo

    from hailo_apps.hailo_app_python.core.common.buffer_utils import (
        get_caps_from_pad,
        get_numpy_from_buffer,
    )
    from hailo_apps.hailo_app_python.core.gstreamer.gstreamer_app import app_callback_class
    from hailo_apps.hailo_app_python.apps.detection.detection_pipeline import GStreamerDetectionApp

    # Import the detection handler - edit detection_handler.py to customize behavior
    # Use path-based import since this script runs standalone with system Python
    from pathlib import Path
    _package_dir = Path(__file__).resolve().parent.parent
    if str(_package_dir) not in sys.path:
        sys.path.insert(0, str(_package_dir))
    from detection_handler import process_detections, format_detection_output

    # User-defined class to be used in the callback function
    class user_app_callback_class(app_callback_class):
        def __init__(self):
            super().__init__()

    # Callback function that will be called when data is available from the pipeline
    def app_callback(pad, info, user_data):
        # Get the GstBuffer from the probe info
        buffer = info.get_buffer()
        if buffer is None:
            return Gst.PadProbeReturn.OK

        user_data.increment()
        frame_count = user_data.get_count()

        # Get the caps from the pad
        format, width, height = get_caps_from_pad(pad)

        # Get video frame if enabled
        frame = None
        if user_data.use_frame and format is not None and width is not None and height is not None:
            frame = get_numpy_from_buffer(buffer, format, width, height)

        # Get the detections from the buffer
        roi = hailo.get_roi_from_buffer(buffer)
        detections_raw = roi.get_objects_typed(hailo.HAILO_DETECTION)

        # Process detections through the handler (edit detection_handler.py to customize)
        result = process_detections(detections_raw, frame_count, hailo)

        # Format and print output
        if result.should_print:
            output = format_detection_output(result)
            print(output)

        # Draw on frame if enabled
        if user_data.use_frame and frame is not None:
            cv2.putText(frame, f"Detections: {len(result.detections)}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            user_data.set_frame(frame)

        return Gst.PadProbeReturn.OK

    # Run the app
    user_data = user_app_callback_class()
    app = GStreamerDetectionApp(app_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()

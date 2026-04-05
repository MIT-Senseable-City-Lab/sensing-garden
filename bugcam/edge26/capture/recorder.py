"""
Video recorder with continuous and interval modes.

Supports two recording modes:
    - Continuous: gapless chunk saving, no interruption between chunks.
    - Interval: record one chunk, release camera, wait N minutes, repeat.

Architecture:
    - Frame grabber thread captures into a queue
    - Main thread consumes frames and writes to chunk files
    - Double-buffering via queue ensures seamless chunk transitions
"""

import cv2
import shutil
import time
import queue
import threading
import logging
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple

logger = logging.getLogger(__name__)
MIN_FREE_DISK_BYTES = 500 * 1024 * 1024


class VideoRecorder:
    """
    Video recorder supporting continuous and interval modes.
    
    Saves fixed-duration video chunks to disk. Camera resolution is
    auto-detected. Completed chunk paths are pushed to a queue for
    downstream processing.
    """
    
    def __init__(
        self,
        output_dir: str,
        fps: int,
        chunk_duration: int,
        resolution: Tuple[int, int],
        device_id: str,
        video_queue: Optional[queue.Queue] = None,
        camera_index: int = 0,
        use_picamera: bool = False,
        recording_mode: str = "continuous",
        interval_minutes: float = 5,
    ):
        """
        Initialize the video recorder.
        
        Args:
            output_dir: Directory to save video chunks (e.g., external USB path)
            fps: Frames per second for recording
            chunk_duration: Duration of each chunk in seconds
            resolution: Requested recording resolution as (width, height)
            device_id: Identifier for filename prefix
            video_queue: Queue to put completed video paths for downstream processing
            camera_index: Camera device index for OpenCV
            use_picamera: Use picamera2 instead of OpenCV (for Raspberry Pi)
            recording_mode: "continuous" (no gaps) or "interval" (record every N minutes)
            interval_minutes: Minutes between start of recordings (interval mode only)
        """
        self.output_dir = Path(output_dir)
        self.fps = fps
        self.chunk_duration = chunk_duration
        self.requested_resolution = resolution
        self.device_id = device_id
        self.video_queue = video_queue
        self.camera_index = camera_index
        self.use_picamera = use_picamera
        self.recording_mode = recording_mode
        self.interval_minutes = interval_minutes
        
        # Resolution is requested from config and confirmed during init.
        self.resolution: Tuple[int, int] = (0, 0)
        
        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Frame queue: buffer between capture and writing
        # Initialized after we know the fps
        self.frame_queue: queue.Queue = None
        
        # Threading controls
        self.stop_event = threading.Event()
        self._grabber_stop = False
        self.camera = None
        self.grabber_thread = None
        
        # Last completed chunk (read by Pipeline after stop)
        self.last_chunk_path: Optional[Path] = None
        
        # Calculate expected frames per chunk
        self.frames_per_chunk = fps * chunk_duration
        
        logger.info(f"VideoRecorder initialized:")
        logger.info(f"  Output: {self.output_dir}")
        logger.info(f"  Target FPS: {fps}, Chunk duration: {chunk_duration}s")
        logger.info(f"  Requested resolution: {resolution[0]}x{resolution[1]}")
        logger.info(f"  Recording mode: {recording_mode}"
                    + (f", interval: {interval_minutes} min" if recording_mode == "interval" else ""))
    
    def _init_camera_opencv(self) -> None:
        """Initialize camera using OpenCV and read resolution."""
        self.camera = cv2.VideoCapture(self.camera_index)
        
        if not self.camera.isOpened():
            raise RuntimeError(f"Failed to open camera {self.camera_index}")
        
        # Set target FPS
        self.camera.set(cv2.CAP_PROP_FPS, self.fps)
        self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.requested_resolution[0])
        self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.requested_resolution[1])
        
        # Read actual resolution from camera
        width = int(self.camera.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(self.camera.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = self.camera.get(cv2.CAP_PROP_FPS)
        
        self.resolution = (width, height)
        self.fps = int(actual_fps) if actual_fps > 0 else self.fps
        
        logger.info(f"Camera opened: {width}x{height} @ {self.fps}fps")
    
    def _init_camera_picamera(self) -> None:
        """Initialize camera using picamera2 (Raspberry Pi) and read resolution."""
        from picamera2 import Picamera2
        
        self.camera = Picamera2()
        
        # Create requested video config and read final applied resolution
        config = self.camera.create_video_configuration(
            # Request a deterministic 3-channel format and convert to BGR
            # before handing frames to OpenCV's VideoWriter.
            main={"size": self.requested_resolution, "format": "RGB888"}
        )
        self.camera.configure(config)
        
        # Read resolution from the configured camera
        width = config["main"]["size"][0]
        height = config["main"]["size"][1]
        self.resolution = (width, height)
        
        # Set frame rate
        self.camera.set_controls({
            "FrameRate": float(self.fps),
        })
        
        self.camera.start()
        
        # Allow camera to warm up
        time.sleep(2)
        logger.info(f"PiCamera started: {self.resolution} @ {self.fps}fps")
    
    def _init_camera(self) -> None:
        """Initialize the camera and read its resolution."""
        if self.use_picamera:
            self._init_camera_picamera()
        else:
            self._init_camera_opencv()
        
        # Now that we have fps, create the frame queue
        # Buffer ~5 seconds of frames to handle file transitions
        self.frame_queue = queue.Queue(maxsize=self.fps * 5)
        
        # Recalculate frames per chunk with actual fps
        self.frames_per_chunk = self.fps * self.chunk_duration
        
        logger.info(f"Recording: {self.resolution[0]}x{self.resolution[1]} @ {self.fps}fps")
        logger.info(f"Chunk: {self.chunk_duration}s = {self.frames_per_chunk} frames")
    
    def _release_camera(self) -> None:
        """Release camera resources."""
        if self.camera is None:
            return
        
        if self.use_picamera:
            try:
                self.camera.stop()
            finally:
                self.camera.close()
        else:
            self.camera.release()
        
        self.camera = None
        logger.info("Camera released")

    def _prepare_frame_for_writer(self, frame: np.ndarray) -> np.ndarray:
        """Convert camera frames to a BGR layout compatible with OpenCV."""
        if not self.use_picamera:
            return frame
        if frame.ndim != 3:
            raise ValueError(f"Unexpected PiCamera frame shape: {frame.shape}")
        if frame.shape[2] == 3:
            return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        if frame.shape[2] == 4:
            return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        raise ValueError(f"Unexpected PiCamera channel count: {frame.shape}")
    
    def _grab_frame(self):
        """Capture a single frame from the camera."""
        if self.use_picamera:
            return self._prepare_frame_for_writer(self.camera.capture_array())
        else:
            ret, frame = self.camera.read()
            if not ret:
                return None
            return frame
    
    def _frame_grabber_loop(self) -> None:
        """
        Continuously grab frames and put them in the queue.
        
        Runs in a separate thread to ensure consistent frame capture
        regardless of file writing operations.
        """
        logger.info("Frame grabber started")
        
        frame_interval = 1.0 / self.fps
        next_frame_time = time.time()
        
        while not self.stop_event.is_set() and not self._grabber_stop:
            try:
                # Capture frame
                frame = self._grab_frame()
                
                if frame is None:
                    logger.warning("Failed to grab frame")
                    continue
                
                # Try to put frame in queue (non-blocking to avoid deadlock)
                try:
                    self.frame_queue.put(frame, timeout=0.1)
                except queue.Full:
                    logger.warning("Frame queue full, dropping frame")
                
                # Maintain frame rate timing
                next_frame_time += frame_interval
                sleep_time = next_frame_time - time.time()
                if sleep_time > 0:
                    time.sleep(sleep_time)
                else:
                    # We're behind, reset timing
                    next_frame_time = time.time()
                    
            except Exception as e:
                if not self.stop_event.is_set():
                    logger.error(f"Frame grabber error: {e}")
                break
        
        logger.info("Frame grabber stopped")
    
    def _generate_chunk_path(self) -> Path:
        """
        Generate a unique path for a new video chunk.
        
        Filename format: {device_id}_{YYYYMMDD}_{HHMMSS}_{ffffff}.mp4
        Timestamp reflects when recording started (real-time).
        """
        now = datetime.now()
        timestamp = now.strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{self.device_id}_{timestamp}.mp4"
        return self.output_dir / filename
    
    def _record_chunk(self) -> Optional[Path]:
        """
        Record a single video chunk by consuming frames from the queue.
        
        Returns:
            Path to the completed chunk, or None if stopped early.
        """
        free_bytes = shutil.disk_usage(self.output_dir).free
        if free_bytes < MIN_FREE_DISK_BYTES:
            logger.warning(
                "Skipping chunk because free space is low: %.1fMB available",
                free_bytes / (1024 * 1024),
            )
            return None

        chunk_path = self._generate_chunk_path()
        logger.info(f"Recording chunk: {chunk_path.name}")
        
        # Initialize video writer
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(
            str(chunk_path),
            fourcc,
            self.fps,
            self.resolution
        )
        
        if not writer.isOpened():
            logger.error(f"Failed to open video writer for {chunk_path}")
            return None
        
        frames_written = 0
        
        try:
            while frames_written < self.frames_per_chunk:
                if self.stop_event.is_set():
                    logger.info("Stop requested, finishing chunk early")
                    break
                
                try:
                    frame = self.frame_queue.get(timeout=1.0)
                    writer.write(frame)
                    frames_written += 1
                except queue.Empty:
                    continue
                    
        finally:
            writer.release()
        
        # Log chunk completion
        if chunk_path.exists():
            size_mb = chunk_path.stat().st_size / (1024 * 1024)
            actual_duration = frames_written / self.fps
            logger.info(
                f"Chunk complete: {chunk_path.name} "
                f"({frames_written} frames, {actual_duration:.1f}s, {size_mb:.1f}MB)"
            )
            return chunk_path
        
        return None
    
    def start(self) -> None:
        """
        Start video recording (continuous or interval).
        
        This method blocks and runs the recording loop.
        Call from a thread if you need non-blocking behavior.
        """
        if self.recording_mode == "interval":
            self._start_interval()
        else:
            self._start_continuous()
    
    def _start_continuous(self) -> None:
        """Record non-stop, chunk after chunk with no gaps."""
        logger.info("Starting continuous recording...")
        
        try:
            self._init_camera()
            self._start_grabber()
            
            while not self.stop_event.is_set():
                chunk_path = self._record_chunk()
                if chunk_path:
                    self.last_chunk_path = chunk_path
                    if self.video_queue:
                        self.video_queue.put(chunk_path)
                    
        except Exception as e:
            logger.error(f"Recording error: {e}", exc_info=True)
        finally:
            self._cleanup(final=True)
    
    def _start_interval(self) -> None:
        """Record one chunk, wait, repeat."""
        interval_seconds = self.interval_minutes * 60
        
        logger.info(f"Starting interval recording "
                    f"({self.chunk_duration}s every {self.interval_minutes} min)...")
        
        try:
            while not self.stop_event.is_set():
                chunk_start = time.time()
                
                # Init camera, record one chunk, release camera
                self._init_camera()
                self._start_grabber()
                
                chunk_path = self._record_chunk()
                if chunk_path:
                    self.last_chunk_path = chunk_path
                    if self.video_queue:
                        self.video_queue.put(chunk_path)
                
                self._cleanup()
                
                if self.stop_event.is_set():
                    break
                
                # Wait until next interval
                elapsed = time.time() - chunk_start
                wait_time = max(0, interval_seconds - elapsed)
                
                if wait_time > 0:
                    logger.info(f"Next recording in {wait_time:.0f}s")
                    # Sleep in small increments so stop_event is responsive
                    wait_end = time.time() + wait_time
                    while time.time() < wait_end and not self.stop_event.is_set():
                        time.sleep(min(1.0, wait_end - time.time()))
                    
        except Exception as e:
            logger.error(f"Recording error: {e}", exc_info=True)
        finally:
            self._cleanup(final=True)
    
    def _start_grabber(self) -> None:
        """Start the frame grabber thread."""
        self.grabber_thread = threading.Thread(
            target=self._frame_grabber_loop,
            daemon=True,
        )
        self.grabber_thread.start()
    
    def stop(self) -> None:
        """
        Signal the recorder to stop.
        
        The current chunk will be finalized before stopping.
        """
        logger.info("Stopping recorder...")
        self.stop_event.set()
    
    def _cleanup(self, final: bool = False) -> None:
        """
        Clean up camera and grabber resources.
        
        Args:
            final: If True, also sets stop_event (full shutdown).
                   If False, only tears down camera/grabber (interval pause).
        """
        if final:
            self.stop_event.set()
        
        # Signal grabber to stop and wait
        if self.grabber_thread and self.grabber_thread.is_alive():
            # Grabber checks stop_event; for interval pause we need a
            # separate mechanism so we don't poison stop_event.
            self._grabber_stop = True
            self.grabber_thread.join(timeout=2.0)
        self._grabber_stop = False
        self.grabber_thread = None
        
        # Release camera
        self._release_camera()
        
        # Drain any remaining frames in the queue
        if self.frame_queue is not None:
            while not self.frame_queue.empty():
                try:
                    self.frame_queue.get_nowait()
                except queue.Empty:
                    break
        
        logger.debug("Recorder resources released")

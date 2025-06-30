import cv2
import time
import os
import threading
import queue
import logging
from datetime import datetime, time as dt_time
from pathlib import Path
from picamera2 import Picamera2

logger = logging.getLogger(__name__)

class VideoRecorder:
    def __init__(self, output_dir="recordings", fps=15, resolution=(640, 640), 
                 recording_duration=300, device_id="recorder", video_queue=None,
                 recording_start_hour=6, recording_end_hour=22):
        """
        Initialize the video recorder for gapless recording.
        
        Args:
            output_dir: Directory to save video files
            fps: Frames per second for recording
            resolution: Video resolution (width, height)
            recording_duration: Duration of each video segment in seconds
            device_id: Device identifier for filename
            video_queue: A queue to put the finished video file paths into.
            recording_start_hour: Hour to start recording (24-hour format, default 6 = 6am)
            recording_end_hour: Hour to stop recording (24-hour format, default 22 = 10pm)
        """
        self.output_dir = Path(output_dir)
        self.fps = fps
        self.resolution = resolution
        self.recording_duration = recording_duration
        self.device_id = device_id
        self.video_queue = video_queue
        self.recording_start_hour = recording_start_hour
        self.recording_end_hour = recording_end_hour
        
        self.output_dir.mkdir(exist_ok=True, parents=True)
        
        self.picam2 = None
        self.stop_event = threading.Event()
        
        # Frame queue for decoupling capture from writing
        self.frame_queue = queue.Queue(maxsize=fps * 5) # Buffer 5 seconds of frames
        self.frame_grabber_thread = None
        
        logger.info("Video Recorder component initialized.")
        logger.info(f"  - FPS: {self.fps}, Resolution: {self.resolution}")
        logger.info(f"  - Recording schedule: {self.recording_start_hour:02d}:00 - {self.recording_end_hour:02d}:00")
    
    def is_recording_time(self):
        """Check if current time is within recording hours."""
        current_hour = datetime.now().hour
        return self.recording_start_hour <= current_hour < self.recording_end_hour
    
    def initialize_camera(self):
        """Initialize and configure the camera."""
        try:
            self.picam2 = Picamera2()
            camera_config = self.picam2.create_video_configuration(
                main={"format": 'RGB888', "size": self.resolution}
            )
            self.picam2.configure(camera_config)
            self.picam2.set_controls({
                "FrameRate": float(self.fps),
                "AfMode": 0, "LensPosition": 0.0,
            })
            self.picam2.start()
            logger.info("Camera initializing...")
            time.sleep(2)
            logger.info("Camera ready.")
        except Exception as e:
            logger.error(f"Failed to initialize camera: {e}", exc_info=True)
            raise

    def _stop_camera(self):
        """Stop the camera and frame grabber thread."""
        self.stop_event.set()
        
        if self.frame_grabber_thread and self.frame_grabber_thread.is_alive():
            self.frame_grabber_thread.join(timeout=2)
            
        if self.picam2:
            try:
                self.picam2.stop()
                logger.info("📸 Camera stopped for time restriction")
            except Exception as e:
                logger.warning(f"Warning: Error stopping camera: {e}")
        
        # Clear the stop event so recording can resume later
        self.stop_event.clear()

    def _frame_grabber(self):
        """Continuously grabs frames from the camera and puts them in a queue."""
        logger.info("📹 Frame grabber thread started.")
        while not self.stop_event.is_set():
            try:
                frame = self.picam2.capture_array()
                self.frame_queue.put(frame)
            except Exception:
                if not self.stop_event.is_set():
                    logger.exception("Error in frame grabber thread.")
                break
        logger.info("📹 Frame grabber thread stopped.")

    def record_segment(self, output_path):
        """Record a single video segment by consuming frames from the queue."""
        logger.info(f"🎬 Recording new segment: {output_path.name}")
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(str(output_path), fourcc, self.fps, self.resolution)
        
        if not out.isOpened():
            raise RuntimeError(f"Failed to open video writer for {output_path}")

        start_time = time.time()
        frame_count = 0
        
        try:
            while time.time() - start_time < self.recording_duration:
                try:
                    frame = self.frame_queue.get(timeout=1)
                    out.write(frame)
                    frame_count += 1
                except queue.Empty:
                    if self.stop_event.is_set():
                        logger.info("Stop event received, finishing current segment early.")
                        break
                    continue
        finally:
            out.release()
            
        file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
        logger.info(f"  ✅ Segment complete: {output_path.name} ({frame_count} frames, {file_size_mb:.1f} MB)")
        
        if self.video_queue:
            self.video_queue.put(output_path)
    
    def start_continuous_recording(self):
        """Start continuous recording loop. This is intended to be the target of a thread."""
        logger.info("🚀 Starting continuous recording loop...")
        camera_initialized = False
        
        try:
            while not self.stop_event.is_set():
                if self.is_recording_time():
                    # Initialize camera only when we need to record
                    if not camera_initialized:
                        logger.info("⏰ Entered recording hours - initializing camera...")
                        self.initialize_camera()
                        self.frame_grabber_thread = threading.Thread(target=self._frame_grabber, daemon=True)
                        self.frame_grabber_thread.start()
                        camera_initialized = True
                    
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"{self.device_id}_{timestamp}.mp4"
                    output_path = self.output_dir / filename
                    
                    self.record_segment(output_path)
                else:
                    # Outside recording hours
                    if camera_initialized:
                        logger.info("⏰ Exited recording hours - stopping camera...")
                        self._stop_camera()
                        camera_initialized = False
                    
                    # Sleep for a minute before checking time again
                    current_time = datetime.now().strftime("%H:%M")
                    logger.info(f"😴 Outside recording hours (current time: {current_time}). Checking again in 60 seconds...")
                    time.sleep(60)
        
        except Exception as e:
             if not self.stop_event.is_set():
                logger.error(f"❌ Fatal error in recording loop: {e}", exc_info=True)
        finally:
             if camera_initialized:
                 self._stop_camera()
             logger.info("🎥 Recording loop has finished.")

    def stop(self):
        """Signals all internal loops to stop and cleans up resources."""
        logger.info("🔄 Stopping recorder component...")
        self.stop_event.set()
        
        if self.frame_grabber_thread and self.frame_grabber_thread.is_alive():
            self.frame_grabber_thread.join(timeout=2)
            
        if self.picam2:
            try:
                self.picam2.stop()
                logger.info("📸 Camera stopped")
            except Exception as e:
                logger.warning(f"Warning: Error stopping camera: {e}")
        
        logger.info("✅ Recorder component stopped.") 
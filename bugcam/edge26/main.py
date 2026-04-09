import json
import logging
import queue
import shutil
import sys
import threading
from pathlib import Path
from datetime import datetime

from bugcam.edge26.capture import VideoRecorder
from bugcam.edge26.processing import VideoProcessor
from bugcam.edge26.output import ResultsWriter


def setup_logging(log_dir: Path) -> None:
    """Configure logging to console and file."""
    log_dir.mkdir(parents=True, exist_ok=True)
    
    log_file = log_dir / f"edge26_{datetime.now().strftime('%Y%m%d')}.log"
    
    # Format
    fmt = "%(asctime)s | %(levelname)-8s | %(message)s"
    datefmt = "%H:%M:%S"
    
    # Root logger
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        datefmt=datefmt,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file)
        ]
    )
    
    # Reduce noise from libraries
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("hailo_platform").setLevel(logging.WARNING)


logger = logging.getLogger("edge26")


class Pipeline:
    """Main pipeline orchestrating capture and processing."""
    
    def __init__(self, config: dict):
        self.config = config
        self.video_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.recording_stopped = threading.Event()
        self.recorder_thread = None
        self.processor_thread = None
        
        # Device config
        device_config = config.get("device", {})
        self.flick_id = device_config.get("flick_id", "edge26")
        self.dot_ids = device_config.get("dot_ids", [])
        self.input_storage = Path(config["paths"]["input_storage"])
        
        # Pipeline mode
        pipeline_config = config.get("pipeline", {})
        self.enable_recording = pipeline_config.get("enable_recording", True)
        self.enable_processing = pipeline_config.get("enable_processing", True)
        self.enable_classification = pipeline_config.get("enable_classification", True)
        self.continuous_tracking = pipeline_config.get("continuous_tracking", True)
        
        # --- Video sampling (save 1 video per N to output) ---
        self._video_batch_count = 0
        self._video_sample_saved = False
        self._video_sample_interval = pipeline_config.get("video_sample_interval", 10)
        
        # --- Tracker reset signals (continuous_tracking mode) ---
        # 1. Day-change: reset when the date in the filename changes
        self._last_video_date: str = ""
        # 2. Recording-stop: reset after the last recorded video is processed
        #    Persisted via .last_recording marker file so it survives restarts.
        self._reset_after_video: str = ""
        self._pending_tracker_reset = False
        if self.continuous_tracking:
            self._load_last_recording_marker()
        
        # Initialize components based on mode
        self.recorder = self._init_recorder() if self.enable_recording else None
        self.processor = VideoProcessor(config) if self.enable_processing else None
        self.writer = ResultsWriter(config["output"]) if self.enable_processing else None
        
        logger.info("=" * 60)
        logger.info("EDGE26 PIPELINE INITIALIZED")
        logger.info("=" * 60)
        
        # Mode info
        mode = "RECORD + PROCESS" if (self.enable_recording and self.enable_processing) else \
               "RECORD ONLY" if self.enable_recording else \
               "PROCESS ONLY" if self.enable_processing else "NONE"
        logger.info(f"Mode:          {mode}")
        logger.info(f"Device:        {self.flick_id}")
        logger.info(f"Input storage: {config['paths']['input_storage']}")
        if self.enable_processing:
            logger.info(f"Results dir:   {config['output']['results_dir']}")
            classify = pipeline_config.get("enable_classification", True)
            logger.info(f"Classification: {'enabled' if classify else 'disabled (detection only)'}")
            cont_track = pipeline_config.get("continuous_tracking", True)
            logger.info(f"Tracking:      {'continuous (across videos)' if cont_track else 'per-video (reset each)'}")
        if self.dot_ids:
            logger.info(f"DOT devices:   {', '.join(self.dot_ids)}")
        if self.enable_recording:
            rec_mode = pipeline_config.get("recording_mode", "continuous")
            logger.info(f"Chunk duration: {config['capture']['chunk_duration_seconds']}s")
            logger.info(f"Recording mode: {rec_mode}"
                       + (f" (every {pipeline_config.get('recording_interval_minutes', 5)} min)"
                          if rec_mode == "interval" else ""))
    
    def _init_recorder(self) -> VideoRecorder:
        """Initialize video recorder from config."""
        paths = self.config["paths"]
        capture = self.config["capture"]
        pipeline_cfg = self.config.get("pipeline", {})
        
        return VideoRecorder(
            output_dir=paths["input_storage"],
            fps=capture["fps"],
            chunk_duration=capture["chunk_duration_seconds"],
            resolution=tuple(capture.get("resolution", [1080, 1080])),
            device_id=self.flick_id,
            video_queue=self.video_queue,
            camera_index=capture["camera_index"],
            use_picamera=capture["use_picamera"],
            recording_mode=pipeline_cfg.get("recording_mode", "continuous"),
            interval_minutes=pipeline_cfg.get("recording_interval_minutes", 5),
        )
    
    def _is_flick_video(self, path: Path) -> bool:
        """Check if a path is a FLICK video (matches flick_id prefix)."""
        return (path.is_file()
                and path.suffix == ".mp4"
                and path.name.startswith(f"{self.flick_id}_"))
    
    def _is_dot_directory(self, path: Path) -> bool:
        """Check if a path is a DOT device directory (matches a dot_id prefix)."""
        if not path.is_dir():
            return False
        return any(path.name.startswith(f"{dot_id}_") for dot_id in self.dot_ids)
    
    def _find_existing_items(self) -> list:
        """
        Find existing videos and DOT directories in input_storage.
        
        Returns a sorted list of (path, type) tuples where type is
        "video" or "dot". Only items matching configured device IDs
        are included. Sorted by name gives chronological order since
        filenames and directory names both contain timestamps.
        """
        if not self.input_storage.exists():
            return []
        
        items = []
        for entry in sorted(self.input_storage.iterdir()):
            if self._is_flick_video(entry):
                items.append((entry, "video"))
            elif self.dot_ids and self._is_dot_directory(entry):
                items.append((entry, "dot"))
        
        if items:
            n_videos = sum(1 for _, t in items if t == "video")
            n_dots = sum(1 for _, t in items if t == "dot")
            parts = []
            if n_videos:
                parts.append(f"{n_videos} video(s)")
            if n_dots:
                parts.append(f"{n_dots} DOT dir(s)")
            logger.info(f"Found {', '.join(parts)} to process")
        
        return items
    
    def _find_dot_directories(self) -> list:
        """Find unprocessed DOT directories in input_storage."""
        if not self.input_storage.exists() or not self.dot_ids:
            return []
        
        return [d for d in sorted(self.input_storage.iterdir())
                if self._is_dot_directory(d)]
    
    def _parse_dot_dir_name(self, dir_name: str):
        """
        Parse a DOT directory name into (dot_id, date_str).
        
        Directory name format: {dot_id}_{YYYYMMDD}
        Returns (dot_id, "YYYYMMDD") or (None, None).
        """
        for dot_id in self.dot_ids:
            if dir_name.startswith(f"{dot_id}_"):
                date_str = dir_name[len(dot_id) + 1:]
                return dot_id, date_str
        return None, None
    
    def _compute_output_dir(self, device_id: str, date_time: str) -> Path:
        """Compute the output directory for a device and timestamp."""
        results_dir = Path(self.config["output"]["results_dir"])
        return results_dir / device_id / date_time
    
    def _find_ready_dot_tracks(self, dot_dir: Path) -> list:
        """Find tracks within a DOT directory that have a done.txt signal."""
        crops_dir = dot_dir / "crops"
        if not crops_dir.exists():
            return []
        return [d for d in sorted(crops_dir.iterdir())
                if d.is_dir() and (d / "done.txt").exists()]
    
    def _find_latest_background(self, dot_dir: Path):
        """Find the most recent background image in a DOT directory."""
        backgrounds = sorted(dot_dir.glob("*_background.jpg"))
        return backgrounds[-1] if backgrounds else None
    
    def _load_existing_results(self, results_path: Path) -> dict:
        """Load existing results.json for incremental updates, or create a fresh structure."""
        if results_path.exists():
            try:
                with open(results_path) as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "source_device": None,
            "processing_timestamp": None,
            "summary": {
                "total_detections": 0,
                "total_tracks": 0,
                "confirmed_tracks": 0,
                "unconfirmed_tracks": 0,
            },
            "tracks": [],
        }
    
    # ------------------------------------------------------------------
    # Last-recording marker (persists across restarts)
    # ------------------------------------------------------------------
    
    @property
    def _marker_path(self) -> Path:
        return self.input_storage / ".last_recording"
    
    def _load_last_recording_marker(self) -> None:
        """Read the .last_recording marker on startup."""
        if not self._marker_path.exists():
            return
        
        marker_video = self._marker_path.read_text().strip()
        if not marker_video:
            self._marker_path.unlink(missing_ok=True)
            return
        
        if (self.input_storage / marker_video).exists():
            # Video still waiting to be processed
            self._reset_after_video = marker_video
            logger.info(f"Previous session marker: will reset tracker after {marker_video}")
        else:
            # Already processed (deleted) — reset before next video
            self._pending_tracker_reset = True
            self._marker_path.unlink(missing_ok=True)
            logger.info(f"Previous session ended ({marker_video} already processed), "
                       f"tracker will reset on next video")
    
    def _save_last_recording_marker(self) -> None:
        """Write the .last_recording marker when recording stops."""
        if not (self.continuous_tracking and self.recorder
                and self.recorder.last_chunk_path):
            return
        
        filename = self.recorder.last_chunk_path.name
        self._marker_path.write_text(filename)
        self._reset_after_video = filename
        logger.info(f"Marked last recording: {filename}")
    
    def _clear_last_recording_marker(self) -> None:
        """Delete the marker after the boundary video is processed."""
        self._marker_path.unlink(missing_ok=True)
        self._reset_after_video = ""
    
    # ------------------------------------------------------------------
    
    def _processor_worker(self) -> None:
        """
        Worker that processes video chunks and DOT directories.
        
        Items from input_storage are processed in chronological order
        (sorted by name). DOT classification does NOT touch the BugSpot
        tracker, so continuous tracking across FLICK videos is preserved
        even when a DOT directory is processed in between.
        """
        logger.info("Processor started")
        
        # Process existing items in chronological order
        for path, item_type in self._find_existing_items():
            if self.stop_event.is_set():
                break
            if item_type == "video":
                self._process_video(path)
            else:
                self._process_dot_directory(path)
        
        # Process new videos from queue + poll for DOT directories
        while not self.stop_event.is_set():
            try:
                video_path = self.video_queue.get(timeout=1.0)
                self._process_video(video_path)
                self.video_queue.task_done()
            except queue.Empty:
                # Check for new DOT directories while waiting
                for dot_dir in self._find_dot_directories():
                    if self.stop_event.is_set():
                        break
                    self._process_dot_directory(dot_dir)
                
                # If recording stopped, check if we're done
                if self.recording_stopped.is_set():
                    remaining = self.video_queue.qsize()
                    has_ready_tracks = any(
                        self._find_ready_dot_tracks(d)
                        for d in self._find_dot_directories()
                    )
                    if remaining == 0 and not has_ready_tracks:
                        logger.info("Queue empty - processing complete")
                        break
                continue
            except Exception as e:
                logger.error(f"Processor error: {e}", exc_info=True)
        
        logger.info("Processor stopped")
    
    def _process_video(self, video_path: Path) -> None:
        """Process a single video file from this FLICK."""
        if not video_path.exists():
            logger.warning(f"Video not found: {video_path}")
            return
        
        logger.info("-" * 50)
        logger.info(f"PROCESSING: {video_path.name}")
        logger.info("-" * 50)
        
        try:
            # Compute output directory: results_dir/flick_id/date_time/
            date_time = video_path.stem[len(self.flick_id) + 1:]
            output_dir = self._compute_output_dir(self.flick_id, date_time)
            
            # --- Pre-process tracker resets (continuous_tracking only) ---
            if self.continuous_tracking:
                # Pending reset from a previous session whose marker video
                # was already processed before we started
                if self._pending_tracker_reset:
                    logger.info("Resetting tracker (previous recording session ended)")
                    self.processor.reset_tracker()
                    self._pending_tracker_reset = False
                
                # Day-change detection
                video_date = date_time[:8]  # YYYYMMDD
                if self._last_video_date and video_date != self._last_video_date:
                    logger.info(f"Day changed ({self._last_video_date} → {video_date}), resetting tracker")
                    self.processor.reset_tracker()
                self._last_video_date = video_date
            
            # Process
            results = self.processor.process_video(video_path, output_dir)
            
            # Write results JSON
            output_paths = self.writer.write_results(
                results=results,
                output_dir=output_dir,
            )
            
            # Summary
            summary = results.get("summary", {})
            logger.info(f"COMPLETE: {summary.get('confirmed_tracks', 0)} insects confirmed "
                       f"({summary.get('total_tracks', 0)} total tracks)")
            
            if output_paths.get('json'):
                logger.info(f"Output: {output_paths['json']}")
            
            # Sample video: save 1 per N to output (0 = disabled)
            if self._video_sample_interval > 0:
                self._video_batch_count += 1
                confirmed = summary.get('confirmed_tracks', 0)
                is_last_in_batch = self._video_batch_count >= self._video_sample_interval
                
                if not self._video_sample_saved and (confirmed > 0 or is_last_in_batch):
                    shutil.copy2(video_path, output_dir / "video.mp4")
                    self._video_sample_saved = True
                    reason = "detections" if confirmed > 0 else "fallback"
                    logger.info(f"  Sample video saved ({reason})")
                
                if is_last_in_batch:
                    self._video_batch_count = 0
                    self._video_sample_saved = False
            
            # Cleanup
            self.processor.clear_video_detections()
            self._delete_video(video_path)
            
            # Recording-stop boundary: reset tracker after the last
            # video from the previous recording session
            if self._reset_after_video and video_path.name == self._reset_after_video:
                logger.info(f"Last recorded video processed, resetting tracker")
                self.processor.reset_tracker()
                self._clear_last_recording_marker()
            
        except Exception as e:
            logger.error(f"Failed to process {video_path.name}: {e}", exc_info=True)
    
    def _process_dot_directory(self, dot_dir: Path) -> None:
        """
        Process ready tracks from a DOT device directory.
        
        The DOT directory persists for a full day. New tracks arrive
        continuously; only those with a done.txt signal are processed.
        Processed tracks (crops + labels) are copied to output then
        deleted from input. Composites are generated from crops placed
        onto the most recent background image using label bounding boxes.
        
        DOT directory structure:
            {dot_id}_{YYYYMMDD}/
                crops/
                    {track_id}_{HHMMSS}/
                        frame_000042.jpg
                        done.txt
                labels/
                    {track_id}.json
                videos/
                    {dot_id}_{YYYYMMDD}_{HHMMSS}.mp4
                {HHMMSS}_background.jpg
        """
        try:
            dot_id, date_str = self._parse_dot_dir_name(dot_dir.name)
            if not dot_id:
                logger.warning(f"Could not parse DOT directory: {dot_dir.name}")
                return
            
            ready_tracks = self._find_ready_dot_tracks(dot_dir)
            if not ready_tracks:
                return
            
            logger.info("-" * 50)
            logger.info(f"PROCESSING DOT: {dot_dir.name} ({len(ready_tracks)} track(s) ready)")
            logger.info("-" * 50)
            
            output_dir = self._compute_output_dir(dot_id, date_str)
            output_dir.mkdir(parents=True, exist_ok=True)
            
            background = self._find_latest_background(dot_dir)
            
            # Copy any new videos to output, then delete from input
            videos_dir = dot_dir / "videos"
            if videos_dir.exists():
                dst_videos = output_dir / "videos"
                dst_videos.mkdir(parents=True, exist_ok=True)
                for vid in sorted(videos_dir.iterdir()):
                    if vid.is_file() and vid.suffix == ".mp4":
                        shutil.copy2(vid, dst_videos / vid.name)
                        vid.unlink()
                        logger.info(f"  Video copied: {vid.name}")
            
            # Load existing results.json for incremental updates
            results = None
            if self.enable_classification:
                results = self._load_existing_results(output_dir / "results.json")
                results["source_device"] = dot_id
                results["date"] = date_str
            
            new_tracks = 0
            for track_dir in ready_tracks:
                if self.stop_event.is_set():
                    break
                try:
                    self._process_dot_track(
                        dot_dir, track_dir, output_dir, background, results
                    )
                    new_tracks += 1
                except Exception as e:
                    logger.error(f"Failed to process track {track_dir.name}: {e}",
                                exc_info=True)
            
            # Write updated results.json (classification mode only)
            if new_tracks > 0 and results is not None:
                results["processing_timestamp"] = datetime.now().isoformat()
                results["summary"]["total_tracks"] = len(results["tracks"])
                results["summary"]["confirmed_tracks"] = len(results["tracks"])
                results["summary"]["total_detections"] = sum(
                    t["num_detections"] for t in results["tracks"]
                )
                self.writer.write_results(results=results, output_dir=output_dir)
            
            if new_tracks > 0:
                classify_str = "" if self.enable_classification else " (classification disabled)"
                logger.info(f"DOT COMPLETE: {new_tracks} new track(s) from {dot_id}{classify_str}")
        
        except Exception as e:
            logger.error(f"Failed to process DOT {dot_dir.name}: {e}", exc_info=True)
    
    def _process_dot_track(self, dot_dir: Path, track_dir: Path,
                           output_dir: Path, background_path, results) -> None:
        """
        Process a single DOT track: classify, create composite, copy to output, cleanup.
        
        Args:
            dot_dir: Parent DOT directory
            track_dir: Track directory inside crops/ (e.g. crops/a1b2c3d4_120000/)
            output_dir: Output results directory
            background_path: Path to background image (or None)
            results: Mutable results dict to append to (None if classification disabled)
        """
        track_dir_name = track_dir.name
        track_id = track_dir_name.rsplit("_", 1)[0]
        
        logger.info(f"  Track {track_dir_name}:")
        
        # Parse timestamp from track directory name: {track_id}_{HHMMSS}
        parts = track_dir_name.rsplit("_", 1)
        track_timestamp = parts[1] if len(parts) == 2 else None
        
        # Phase 5-6: Classify crops
        if self.enable_classification and results is not None:
            track_result = self.processor.classify_dot_track(
                track_dir, track_id, track_timestamp
            )
            if track_result:
                results["tracks"].append(track_result)
                final = track_result.get("final_prediction", {})
                logger.info(f"    {final.get('family', 'N/A')} / "
                           f"{final.get('genus', 'N/A')} / "
                           f"{final.get('species', 'N/A')} "
                           f"({final.get('species_confidence', 0):.1%})")
        
        # Create composite from crops + background
        if background_path:
            label_path = dot_dir / "labels" / f"{track_id}.json"
            composite_dir = output_dir / "composites"
            composite_dir.mkdir(parents=True, exist_ok=True)
            try:
                self.processor.create_dot_composite(
                    track_dir, background_path, label_path,
                    composite_dir / f"{track_dir_name}.jpg"
                )
                logger.info(f"    Composite saved")
            except Exception as e:
                logger.warning(f"    Could not create composite: {e}")
        
        # Copy crops to output (exclude done.txt)
        dst_crops = output_dir / "crops" / track_dir_name
        dst_crops.mkdir(parents=True, exist_ok=True)
        for f in track_dir.iterdir():
            if f.name != "done.txt" and f.is_file():
                shutil.copy2(f, dst_crops / f.name)
        
        # Copy label file to output, then delete from input
        label_src = dot_dir / "labels" / f"{track_id}.json"
        if label_src.exists():
            dst_labels = output_dir / "labels"
            dst_labels.mkdir(parents=True, exist_ok=True)
            shutil.copy2(label_src, dst_labels / f"{track_id}.json")
            label_src.unlink()
        
        # Delete processed track from input
        shutil.rmtree(track_dir)
        logger.debug(f"    Deleted input: {track_dir_name}")
    
    def _delete_video(self, video_path: Path) -> None:
        """Delete processed video."""
        try:
            video_path.unlink()
            logger.debug(f"Deleted: {video_path.name}")
        except Exception as e:
            logger.error(f"Could not delete {video_path.name}: {e}")
    
    def start(self) -> None:
        """Start the pipeline."""
        logger.info("=" * 60)
        logger.info("STARTING PIPELINE")
        logger.info("=" * 60)
        
        # Start recorder (if enabled)
        if self.enable_recording and self.recorder:
            self.recorder_thread = threading.Thread(
                target=self.recorder.start,
                daemon=True,
                name="Recorder"
            )
            self.recorder_thread.start()
            logger.info("Recorder thread started")
        else:
            self.recording_stopped.set()  # No recording
        
        # Start processor (if enabled)
        if self.enable_processing and self.processor:
            self.processor_thread = threading.Thread(
                target=self._processor_worker,
                daemon=False,  # Non-daemon so it completes
                name="Processor"
            )
            self.processor_thread.start()
            logger.info("Processor thread started")
        
        if self.enable_recording and self.enable_processing:
            logger.info("Pipeline running - Ctrl+C to stop recording (processing continues)")
        elif self.enable_recording:
            logger.info("Recording - Ctrl+C to stop")
        else:
            logger.info("Processing existing videos...")
    
    def stop_recording(self) -> None:
        """Stop recording only, processing continues."""
        if not self.recording_stopped.is_set():
            logger.info("=" * 60)
            logger.info("STOPPING RECORDING")
            logger.info("=" * 60)
            
            if self.recorder:
                self.recorder.stop()
            if self.recorder_thread:
                self.recorder_thread.join(timeout=10.0)
            
            # Mark the last recorded video so tracker resets after it
            self._save_last_recording_marker()
            
            self.recording_stopped.set()
            logger.info("Recording stopped - processing remaining videos...")
            
            remaining = self.video_queue.qsize()
            if remaining > 0:
                logger.info(f"Videos in queue: {remaining}")
    
    def stop(self) -> None:
        """Stop the pipeline gracefully."""
        logger.info("=" * 60)
        logger.info("STOPPING PIPELINE")
        logger.info("=" * 60)
        
        # Stop recorder first
        self.stop_recording()
        
        # Stop processor
        self.stop_event.set()
        if self.processor_thread:
            self.processor_thread.join(timeout=30.0)
            logger.info("Processor stopped")
        
        logger.info("Pipeline stopped cleanly")
    
    def wait(self) -> None:
        """Wait for pipeline (blocks until stopped)."""
        # Wait for recorder to finish (if running)
        if self.recorder_thread:
            self.recorder_thread.join()
        
        # Wait for processor to finish (if running)
        if self.processor_thread:
            self.processor_thread.join()

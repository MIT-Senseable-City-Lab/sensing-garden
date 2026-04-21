import json
import logging
import queue
import shutil
import sys
import threading
import time
from pathlib import Path
from datetime import datetime

import cv2

from bugcam.edge26.capture import VideoRecorder
from bugcam.edge26.processing import VideoProcessor, HailoClassifier
from bugcam.edge26.output import ResultsWriter
from bugcam.edge26.queue import ClassificationQueue, QueueEntry


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
    """
    Main pipeline orchestrating capture and processing.
    
    Architecture:
        - Detection thread: Runs BugSpot detection/tracking (maintains tracker state)
        - Classification thread: Runs Hailo classification (shared resource)
        - Classification queue: Disk-based FIFO queue for both FLIK and DOT tracks
    """
    
    def __init__(self, config: dict):
        self.config = config
        self.video_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.recording_stopped = threading.Event()
        self.recorder_thread = None
        self.detection_thread = None
        self.classification_thread = None
        
        # Device config
        device_config = config.get("device", {})
        self.flick_id = device_config.get("flick_id", "edge26")
        self.dot_ids = device_config.get("dot_ids", [])
        self.input_storage = Path(config["paths"]["input_storage"])
        
        # Output paths
        self.results_dir = Path(config["output"]["results_dir"])
        
        # Pending queue for classification
        pending_dir = Path(config["paths"].get("pending_dir", 
                         Path(config["paths"]["input_storage"]).parent / "pending"))
        self.classification_queue = ClassificationQueue(pending_dir)
        
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
        
        # Eagerly initialize classifier for the classification thread
        if self.enable_classification and self.processor:
            self.processor._classifier = HailoClassifier(self.processor.classification_config)
            logger.info("Hailo classifier initialized")
        
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
        logger.info(f"Pending dir:   {pending_dir}")
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
        return self.results_dir / device_id / date_time
    
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
    
    @staticmethod
    def _deduplicate_track_id(track_id: str, results: dict) -> str:
        """If track_id already exists in results, append a suffix to make it unique."""
        existing_ids = {t.get("track_id") for t in results.get("tracks", [])}
        if track_id not in existing_ids:
            return track_id
        n = 1
        while f"{track_id}_{n}" in existing_ids:
            n += 1
        deduped = f"{track_id}_{n}"
        logger.warning(f"Track {track_id} already in results, saving as {deduped}")
        return deduped

    def _load_existing_results(self, results_path: Path) -> dict:
        """Load existing results.json for incremental updates, or create a fresh structure."""
        if results_path.exists():
            try:
                with open(results_path) as f:
                    return json.load(f)
            except json.JSONDecodeError:
                logger.warning(f"Corrupt results.json, starting fresh: {results_path}")
            except Exception as e:
                logger.error(f"Cannot read results.json ({e}), starting fresh: {results_path}")
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
    # Detection Thread - Runs BugSpot detection/tracking
    # ------------------------------------------------------------------
    
    def _detection_worker(self) -> None:
        """
        Worker that runs detection/tracking for videos and queues DOT tracks.
        
        Maintains continuous tracker state for FLIK videos.
        Queues both FLIK and DOT tracks for classification.
        """
        logger.info("Detection worker started")
        
        # Process existing items in chronological order
        for path, item_type in self._find_existing_items():
            if self.stop_event.is_set():
                break
            if item_type == "video":
                self._process_video_detection(path)
            else:
                self._process_dot_directory_detection(path)
        
        # Process new videos from queue + poll for DOT directories
        while not self.stop_event.is_set():
            try:
                video_path = self.video_queue.get(timeout=1.0)
                self._process_video_detection(video_path)
                self.video_queue.task_done()
                
                # Check for DOT directories after each video (interleaved processing)
                for dot_dir in self._find_dot_directories():
                    if self.stop_event.is_set():
                        break
                    self._process_dot_directory_detection(dot_dir)
                
            except queue.Empty:
                # Check for new DOT directories while waiting
                for dot_dir in self._find_dot_directories():
                    if self.stop_event.is_set():
                        break
                    self._process_dot_directory_detection(dot_dir)
                
                # If recording stopped, check if we're done
                if self.recording_stopped.is_set():
                    remaining = self.video_queue.qsize()
                    has_ready_tracks = any(
                        self._find_ready_dot_tracks(d)
                        for d in self._find_dot_directories()
                    )
                    pending_count = self.classification_queue.count()
                    if remaining == 0 and not has_ready_tracks and pending_count == 0:
                        logger.info("Queue empty - processing complete")
                        break
                continue
            except Exception as e:
                logger.error(f"Detection error: {e}", exc_info=True)
        
        logger.info("Detection worker stopped")
    
    def _process_video_detection(self, video_path: Path) -> None:
        """
        Process a FLIK video: detection/tracking only, queue crops for classification.
        
        Maintains tracker state for continuous tracking across videos.
        """
        if not video_path.exists():
            logger.warning(f"Video not found: {video_path}")
            return
        
        logger.info("-" * 50)
        logger.info(f"DETECTION: {video_path.name}")
        logger.info("-" * 50)
        
        try:
            # Compute output directory: results_dir/flick_id/date_time/
            date_time = video_path.stem[len(self.flick_id) + 1:]
            output_dir = self._compute_output_dir(self.flick_id, date_time)
            output_dir.mkdir(parents=True, exist_ok=True)
            
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
            
            # Run BugSpot detection/tracking (Phases 1-4)
            result = self.processor._pipeline.process_video(
                str(video_path),
                extract_crops=True,
                render_composites=self.processor.output_config.get("save_composites", True),
                save_crops_dir=str(output_dir / "crops"),
                save_composites_dir=str(output_dir / "composites") if self.processor.output_config.get("save_composites", True) else None,
            )
            
            logger.info(f"  BugSpot: {len(result.confirmed_tracks)} confirmed / "
                       f"{len(result.track_paths)} total tracks")
            
            # Save crops and queue for classification
            confirmed_count = 0
            for track_id, track in result.confirmed_tracks.items():
                # BugSpot saves crops using first 8 chars of track UUID
                # track_id format: {uuid}_{timestamp} -> use first 8 chars for directory
                base_track_id = track_id.split('-')[0]
                track_dir = output_dir / "crops" / base_track_id
                
                if not track_dir.exists():
                    logger.warning(f"Track directory not found: {track_dir}")
                    continue
                
                # Extract timestamp from video filename
                track_timestamp = date_time.split('_')[-1] if '_' in date_time else None
                
                # Queue for classification
                self.classification_queue.enqueue(
                    entry_type="flik",
                    source_device=self.flick_id,
                    date=date_time[:8],  # YYYYMMDD
                    time=track_timestamp,
                    track_id=track_id,
                    track_dir=track_dir,
                    output_dir=output_dir,
                    num_crops=len(track.crops),
                )
                confirmed_count += 1
            
            # Sample video: save 1 per N to output (0 = disabled)
            if self._video_sample_interval > 0:
                self._video_batch_count += 1
                is_last_in_batch = self._video_batch_count >= self._video_sample_interval
                
                if not self._video_sample_saved and (confirmed_count > 0 or is_last_in_batch):
                    shutil.copy2(video_path, output_dir / "video.mp4")
                    self._video_sample_saved = True
                    reason = "detections" if confirmed_count > 0 else "fallback"
                    logger.info(f"  Sample video saved ({reason})")
                
                if is_last_in_batch:
                    self._video_batch_count = 0
                    self._video_sample_saved = False
            
            # Clear detections but KEEP tracker state (continuous tracking)
            self.processor.clear_video_detections()
            
            # Delete processed video
            self._delete_video(video_path)
            
            # Recording-stop boundary: reset tracker after the last
            # video from the previous recording session
            if self._reset_after_video and video_path.name == self._reset_after_video:
                logger.info(f"Last recorded video processed, resetting tracker")
                self.processor.reset_tracker()
                self._clear_last_recording_marker()
            
            logger.info(f"QUEUED: {confirmed_count} tracks for classification")
            
            # Save detection metadata for classification thread to merge into results
            if confirmed_count > 0:
                detection_meta = {
                    "source_device": self.flick_id,
                    "date": date_time[:8],
                    "video_file": video_path.name,
                    "model_id": self.config.get("model", {}).get("model_id"),
                    "video_info": {
                        "fps": result.video_info.get("fps"),
                        "total_frames": result.video_info.get("total_frames"),
                        "duration_seconds": result.video_info.get("duration"),
                    } if hasattr(result, "video_info") and result.video_info else None,
                    "summary": {
                        "total_detections": len(result.all_detections) if hasattr(result, "all_detections") else 0,
                        "total_tracks": len(result.track_paths) if hasattr(result, "track_paths") else 0,
                        "confirmed_tracks": len(result.confirmed_tracks),
                        "unconfirmed_tracks": (len(result.track_paths) - len(result.confirmed_tracks)) if hasattr(result, "track_paths") else 0,
                    },
                    "tracks": {
                        tid: {
                            "num_detections": track.num_detections if hasattr(track, "num_detections") else None,
                            "first_seen_seconds": track.first_frame_time if hasattr(track, "first_frame_time") else None,
                            "last_seen_seconds": track.last_frame_time if hasattr(track, "last_frame_time") else None,
                            "duration_seconds": track.duration if hasattr(track, "duration") else None,
                            "topology_metrics": track.topology_metrics if hasattr(track, "topology_metrics") else None,
                        }
                        for tid, track in result.confirmed_tracks.items()
                    },
                    "frame_detections": {
                        track_id: [
                            {
                                "frame_number": det.get("frame_number"),
                                "timestamp_seconds": det.get("frame_time_seconds"),
                                "bbox": det.get("bbox"),
                            }
                            for det in result.all_detections
                            if det.get("track_id") == track_id
                        ]
                        for track_id in result.confirmed_tracks
                    } if hasattr(result, "all_detections") else {},
                }
                meta_path = output_dir / ".detection.json"
                meta_path.write_text(json.dumps(detection_meta, indent=2, default=str))
                
                # Write expected track count for completeness check
                (output_dir / ".expected_tracks").write_text(str(confirmed_count))
                logger.info(f"  Detection metadata saved ({confirmed_count} tracks)")
            
        except Exception as e:
            logger.error(f"Failed to process {video_path.name}: {e}", exc_info=True)
    
    def _process_dot_directory_detection(self, dot_dir: Path) -> None:
        """
        Process DOT directory: copy crops/labels, queue for classification.
        
        Does NOT touch the tracker - DOT processing is independent.
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
            logger.info(f"DOT DETECTION: {dot_dir.name} ({len(ready_tracks)} track(s) ready)")
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
            
            # Queue each track for classification
            queued_count = 0
            for track_dir in ready_tracks:
                if self.stop_event.is_set():
                    break
                
                track_dir_name = track_dir.name
                track_id = track_dir_name.rsplit("_", 1)[0]
                track_timestamp = track_dir_name.rsplit("_", 1)[-1] if "_" in track_dir_name else None
                
                # Copy crops to output
                dst_crops = output_dir / "crops" / track_dir_name
                dst_crops.mkdir(parents=True, exist_ok=True)
                
                crop_count = 0
                for f in track_dir.iterdir():
                    if f.name != "done.txt" and f.is_file():
                        shutil.copy2(f, dst_crops / f.name)
                        crop_count += 1
                
                # Copy label file to output
                label_src = dot_dir / "labels" / f"{track_id}.json"
                dst_labels = output_dir / "labels"
                dst_labels.mkdir(parents=True, exist_ok=True)
                if label_src.exists():
                    shutil.copy2(label_src, dst_labels / f"{track_id}.json")
                
                # Queue for classification
                self.classification_queue.enqueue(
                    entry_type="dot",
                    source_device=dot_id,
                    date=date_str,
                    time=track_timestamp,
                    track_id=track_id,
                    track_dir=dst_crops,
                    output_dir=output_dir,
                    labels_path=dst_labels / f"{track_id}.json" if label_src.exists() else None,
                    background_path=background,
                    num_crops=crop_count,
                )
                queued_count += 1
                
                # Delete processed track from input
                shutil.rmtree(track_dir)
                logger.debug(f"  Queued track {track_id} ({crop_count} crops)")
            
            logger.info(f"QUEUED: {queued_count} DOT tracks for classification")
            
            # Write expected track count for completeness check
            if queued_count > 0:
                (output_dir / ".expected_tracks").write_text(str(queued_count))
            
            # Clean up DOT directory if empty after processing
            try:
                remaining = list(dot_dir.iterdir())
                if not remaining:
                    dot_dir.rmdir()
                    logger.info(f"Removed empty DOT directory: {dot_dir.name}")
            except OSError:
                pass
        
        except Exception as e:
            logger.error(f"Failed to process DOT {dot_dir.name}: {e}", exc_info=True)
    
    # ------------------------------------------------------------------
    # Classification Thread - Runs Hailo classification
    # ------------------------------------------------------------------
    
    def _classification_worker(self) -> None:
        """
        Worker that processes classification queue (FIFO).
        
        Classifies tracks from both FLIK and DOT sources.
        """
        logger.info("Classification worker started")
        
        # Recover any pending from crash
        self.classification_queue.recover()
        
        while not self.stop_event.is_set():
            result = self.classification_queue.get_next()
            
            if result is None:
                time.sleep(0.5)
                continue
            
            filepath, entry = result
            
            try:
                if entry.entry_type == "flik":
                    self._classify_flik_track(entry)
                else:
                    self._classify_dot_track(entry)
                
                self.classification_queue.remove(filepath)
                
            except Exception as e:
                logger.error(f"Classification failed for {filepath.name}: {e}", exc_info=True)
                should_retry = self.classification_queue.mark_failed(filepath, entry, str(e))
                if should_retry:
                    time.sleep(1.0)
                else:
                    # Permanently failed — still count as completed for .done check
                    self._check_classification_complete(Path(entry.output_dir))
        
        logger.info("Classification worker stopped")
    
    def _classify_flik_track(self, entry: QueueEntry) -> None:
        """Classify a FLIK track from queue entry."""
        track_dir = Path(entry.track_dir)
        output_dir = Path(entry.output_dir)
        
        if not track_dir.exists():
            logger.warning(f"Track directory not found: {track_dir}")
            self._check_classification_complete(output_dir)
            return
        
        logger.info(f"CLASSIFY FLIK: {entry.track_id} ({entry.num_crops} crops)")
        
        # Load crops
        crop_files = sorted(track_dir.glob("frame_*.jpg"))
        if not crop_files:
            logger.warning(f"No crops found in {track_dir}")
            self._check_classification_complete(output_dir)
            return
        
        # Ensure classifier is initialized
        if self.processor._classifier is None:
            self.processor._classifier = HailoClassifier(self.processor.classification_config)
        
        # Classify
        classifications = []
        frames = []
        
        for crop_path in crop_files:
            crop = cv2.imread(str(crop_path))
            if crop is None:
                continue
            
            frame_num = int(crop_path.stem.split("_")[1])
            classification = self.processor._classifier.classify(crop)
            classifications.append(classification)
            
            frames.append({
                "frame_number": frame_num,
                "prediction": {
                    "family": classification.family,
                    "genus": classification.genus,
                    "species": classification.species,
                    "family_confidence": classification.family_confidence,
                    "genus_confidence": classification.genus_confidence,
                    "species_confidence": classification.species_confidence,
                }
            })
        
        if not classifications:
            self._check_classification_complete(output_dir)
            return
        
        # Hierarchical aggregation
        final_pred = self.processor._classifier.hierarchical_aggregate(classifications)
        if not final_pred:
            self._check_classification_complete(output_dir)
            return
        
        logger.info(f"  {final_pred['family']} / {final_pred['genus']} / {final_pred['species']} "
                   f"({final_pred['species_confidence']:.1%})")
        
        # Load existing results
        results_path = output_dir / "results.json"
        results = self._load_existing_results(results_path)
        
        # Load detection metadata to enrich results
        detection_meta = self._load_detection_meta(output_dir)
        
        # Deduplicate track_id if this is a retry after crash
        track_id = self._deduplicate_track_id(entry.track_id, results)
        
        # Enrich results with detection metadata (first track writes top-level fields)
        if detection_meta and not results.get("video_file"):
            results["video_file"] = detection_meta.get("video_file")
            results["video_timestamp"] = detection_meta.get("video_timestamp")
            results["model_id"] = detection_meta.get("model_id")
            if detection_meta.get("video_info"):
                results["video_info"] = detection_meta["video_info"]
            results["date"] = detection_meta.get("date", entry.date)
        results["source_device"] = entry.source_device
        results["processing_timestamp"] = datetime.now().isoformat()
        
        # Build per-track frame data, enriched with detection metadata
        track_frames = frames
        track_meta = detection_meta.get("tracks", {}).get(entry.track_id, {}) if detection_meta else {}
        frame_dets = detection_meta.get("frame_detections", {}).get(entry.track_id, []) if detection_meta else []
        
        if frame_dets or track_meta:
            frame_det_map = {fd["frame_number"]: fd for fd in frame_dets if fd.get("frame_number") is not None}
            enriched_frames = []
            for f in frames:
                fd = frame_det_map.get(f.get("frame_number"))
                enriched = dict(f)
                if fd:
                    if fd.get("timestamp_seconds") is not None:
                        enriched["timestamp_seconds"] = fd["timestamp_seconds"]
                    if fd.get("bbox") is not None:
                        enriched["bbox"] = fd["bbox"]
                enriched_frames.append(enriched)
            track_frames = enriched_frames
        
        # Update results
        track_result = {
            "track_id": track_id,
            "timestamp": entry.time,
            "final_prediction": final_pred,
            "num_detections": len(track_frames),
            "frames": track_frames,
        }
        if track_meta.get("first_seen_seconds") is not None:
            track_result["first_seen_seconds"] = track_meta["first_seen_seconds"]
        if track_meta.get("last_seen_seconds") is not None:
            track_result["last_seen_seconds"] = track_meta["last_seen_seconds"]
        if track_meta.get("duration_seconds") is not None:
            track_result["duration_seconds"] = track_meta["duration_seconds"]
        if track_meta.get("topology_metrics") is not None:
            track_result["topology_metrics"] = track_meta["topology_metrics"]
        
        results["tracks"].append(track_result)
        
        # Update summary from detection metadata if available, otherwise count classified tracks
        if detection_meta and "summary" in detection_meta:
            results["summary"]["total_detections"] = detection_meta["summary"].get("total_detections", 0)
            results["summary"]["total_tracks"] = detection_meta["summary"].get("total_tracks", 0)
            results["summary"]["confirmed_tracks"] = detection_meta["summary"].get("confirmed_tracks", 0)
            results["summary"]["unconfirmed_tracks"] = detection_meta["summary"].get("unconfirmed_tracks", 0)
        else:
            results["summary"]["total_tracks"] = len(results["tracks"])
            results["summary"]["confirmed_tracks"] = len(results["tracks"])
            results["summary"]["total_detections"] = sum(t.get("num_detections", 0) for t in results["tracks"])
        
        # Write results
        self.writer.write_results(results=results, output_dir=output_dir)
        
        # Check if all tracks for this output directory are done
        self._check_classification_complete(output_dir)
    
    def _classify_dot_track(self, entry: QueueEntry) -> None:
        """Classify a DOT track from queue entry."""
        track_dir = Path(entry.track_dir)
        output_dir = Path(entry.output_dir)
        
        if not track_dir.exists():
            logger.warning(f"Track directory not found: {track_dir}")
            self._check_classification_complete(output_dir)
            return
        
        logger.info(f"CLASSIFY DOT: {entry.track_id} ({entry.num_crops} crops)")
        
        # Classify using existing method
        track_result = self.processor.classify_dot_track(
            track_dir, entry.track_id, entry.time
        )
        
        if not track_result:
            self._check_classification_complete(output_dir)
            return
        
        final = track_result.get("final_prediction", {})
        logger.info(f"  {final.get('family', 'N/A')} / {final.get('genus', 'N/A')} / "
                   f"{final.get('species', 'N/A')} ({final.get('species_confidence', 0):.1%})")
        
        # Create composite if background available
        if entry.background_path:
            background_path = Path(entry.background_path)
            labels_path = Path(entry.labels_path) if entry.labels_path else None
            composite_dir = output_dir / "composites"
            composite_dir.mkdir(parents=True, exist_ok=True)
            
            track_dir_name = f"{entry.track_id}_{entry.time}" if entry.time else entry.track_id
            composite_path = composite_dir / f"{track_dir_name}.jpg"
            
            try:
                if labels_path and labels_path.exists():
                    self.processor.create_dot_composite(
                        track_dir, background_path, labels_path, composite_path
                    )
                    logger.debug(f"  Composite saved")
            except Exception as e:
                logger.warning(f"  Could not create composite: {e}")
        
        # Load existing results
        results_path = output_dir / "results.json"
        results = self._load_existing_results(results_path)
        
        # Deduplicate track_id if this is a retry after crash
        track_id = self._deduplicate_track_id(track_result["track_id"], results)
        track_result["track_id"] = track_id
        
        # Update results
        results["tracks"].append(track_result)
        results["source_device"] = entry.source_device
        results["date"] = entry.date
        results["processing_timestamp"] = datetime.now().isoformat()
        
        # Update summary
        results["summary"]["total_tracks"] = len(results["tracks"])
        results["summary"]["confirmed_tracks"] = len(results["tracks"])
        results["summary"]["total_detections"] = sum(t.get("num_detections", 0) for t in results["tracks"])
        
        # Write results
        self.writer.write_results(results=results, output_dir=output_dir)
        
        # Check if all tracks for this output directory are done
        self._check_classification_complete(output_dir)
    
    def _delete_video(self, video_path: Path) -> None:
        """Delete processed video."""
        try:
            video_path.unlink()
            logger.debug(f"Deleted: {video_path.name}")
        except Exception as e:
            logger.error(f"Could not delete {video_path.name}: {e}")
    
    @staticmethod
    def _load_detection_meta(output_dir: Path) -> dict:
        """Load detection metadata sidecar if available."""
        meta_path = output_dir / ".detection.json"
        if meta_path.exists():
            try:
                return json.loads(meta_path.read_text())
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Could not read detection metadata: {e}")
        return {}
    
    @staticmethod
    def _check_classification_complete(output_dir: Path) -> None:
        """
        Increment completed count and check if all tracks for this dir are done.
        
        When detection enqueues tracks, it writes .expected_tracks with the count.
        Each call to this method increments .completed_tracks. When
        completed >= expected, writes .done to signal the upload thread.
        Also called on graceful failures (missing crops, empty dirs) and
        permanent queue failures to ensure .done is always written eventually.
        """
        expected_path = output_dir / ".expected_tracks"
        if not expected_path.exists():
            return
        
        try:
            expected = int(expected_path.read_text().strip())
        except (ValueError, OSError):
            return
        
        # Atomically increment completed count
        completed_path = output_dir / ".completed_tracks"
        try:
            completed = int(completed_path.read_text().strip()) + 1
        except (ValueError, OSError):
            completed = 1
        completed_path.write_text(str(completed))
        
        if completed >= expected:
            done_path = output_dir / ".done"
            done_path.write_text(f"classified={completed}\nexpected={expected}\n")
            logger.info(f"Classification complete: {completed}/{expected} tracks in {output_dir.name}")
            expected_path.unlink(missing_ok=True)
            completed_path.unlink(missing_ok=True)
            detection_meta_path = output_dir / ".detection.json"
            detection_meta_path.unlink(missing_ok=True)
    
    # ------------------------------------------------------------------
    # Pipeline Control
    # ------------------------------------------------------------------
    
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
        
        # Start detection worker
        if self.enable_processing and self.processor:
            self.detection_thread = threading.Thread(
                target=self._detection_worker,
                daemon=False,
                name="Detection"
            )
            self.detection_thread.start()
            logger.info("Detection thread started")
            
            # Start classification worker
            if self.enable_classification:
                self.classification_thread = threading.Thread(
                    target=self._classification_worker,
                    daemon=False,
                    name="Classification"
                )
                self.classification_thread.start()
                logger.info("Classification thread started")
        
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
            
            pending = self.classification_queue.count()
            if pending > 0:
                logger.info(f"Pending classifications: {pending}")
    
    def stop(self) -> None:
        """Stop the pipeline gracefully."""
        logger.info("=" * 60)
        logger.info("STOPPING PIPELINE")
        logger.info("=" * 60)
        
        # Stop recorder first
        self.stop_recording()
        
        # Stop threads
        self.stop_event.set()
        
        if self.detection_thread:
            self.detection_thread.join(timeout=30.0)
            logger.info("Detection thread stopped")
        
        if self.classification_thread:
            self.classification_thread.join(timeout=30.0)
            logger.info("Classification thread stopped")
        
        logger.info("Pipeline stopped cleanly")
    
    def wait(self) -> None:
        """Wait for pipeline (blocks until stopped)."""
        # Wait for recorder to finish (if running)
        if self.recorder_thread:
            self.recorder_thread.join()
        
        # Wait for detection thread to finish (if running)
        if self.detection_thread:
            self.detection_thread.join()
        
        # Wait for classification thread to finish (if running)
        if self.classification_thread:
            self.classification_thread.join()
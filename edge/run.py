import time
import os
import threading
import queue
import argparse
import random
import logging
import requests
import cv2
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Import our refactored components
from main.record_video import VideoRecorder
from main.inference_from_video import VideoInferenceProcessor, process_video
from sensing_garden_client import SensingGardenClient
from models.insect_tracker import InsectTracker

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ContinuousPipeline:
    def __init__(self, video_dir="recordings", recording_duration=300, upload_percentage=10, 
                 device_id="pipeline", fps=15, resolution=(640, 640), enable_uploads=True,
                 confidence_threshold=0.35, class_names_path="data/london_invertebrates.txt",
                 recording_start_hour=6, recording_end_hour=22):
        """
        Initialize the continuous pipeline using imported components.
        """
        self.video_dir = Path(video_dir)
        self.upload_percentage = upload_percentage
        self.device_id = device_id
        self.enable_uploads = enable_uploads
        self.confidence_threshold = confidence_threshold
        self.resolution = resolution
        self.recording_start_hour = recording_start_hour
        self.recording_end_hour = recording_end_hour
        
        # Threading controls
        self.stop_event = threading.Event()
        self.video_queue = queue.Queue()

        # --- Centralized State Management ---
        self.global_frame_count = 0
        self.tracker = None
        
        # --- Centralized Taxonomy Initialization ---
        logger.info("Initializing taxonomy...")
        try:
            self.class_names = self.load_class_names(class_names_path)
            self.families, self.genera, self.genus_to_family, self.species_to_genus = self.build_taxonomy()
            logger.info("✅ Taxonomy initialized successfully.")
        except Exception as e:
            logger.error(f"❌ Failed to initialize taxonomy: {e}. Exiting.")
            raise
        
        # --- Centralized Tracker Initialization ---
        logger.info("Initializing insect tracker...")
        try:
            width, height = self.resolution
            self.tracker = InsectTracker(height, width, max_frames=30, w_dist=0.7, w_area=0.3, cost_threshold=0.8)
            logger.info("✅ Insect tracker initialized successfully.")
        except Exception as e:
            logger.error(f"❌ Failed to initialize insect tracker: {e}. Exiting.")
            raise
        
        # Initialize components
        self.recorder = VideoRecorder(
            output_dir=str(self.video_dir),
            fps=fps,
            resolution=resolution,
            recording_duration=recording_duration,
            device_id=self.device_id,
            video_queue=self.video_queue,
            recording_start_hour=self.recording_start_hour,
            recording_end_hour=self.recording_end_hour
        )
        self.sgc = None
        if self.enable_uploads:
            self.sgc = self.initialize_sensing_garden_client()
        
        # Threads
        self.recorder_thread = None
        self.processor_thread = None
        
        logger.info("🚀 Continuous Pipeline initialized")
        logger.info(f"⏰ Recording schedule: {self.recording_start_hour:02d}:00 - {self.recording_end_hour:02d}:00")
        logger.info("ℹ️  Video processing will continue 24/7, but new recordings only during scheduled hours")

    def load_class_names(self, class_names_path):
        with open(class_names_path, 'r') as f:
            class_names = [line.strip() for line in f.readlines()]
        logger.info(f"Loaded {len(class_names)} class names")
        return class_names
    
    def build_taxonomy(self):
        if not self.class_names:
            return [], [], {}, {}
        taxonomy = self.get_taxonomy_from_gbif(self.class_names)
        families = taxonomy[1]
        genus_to_family = taxonomy[2]
        species_to_genus = taxonomy[3]
        genera = list(genus_to_family.keys())
        logger.info(f"Built taxonomy: {len(families)} families, {len(genera)} genera")
        return families, genera, genus_to_family, species_to_genus
    
    def get_taxonomy_from_gbif(self, species_list):
        taxonomy = {1: [], 2: {}, 3: {}}
        logger.info(f"\nBuilding taxonomy for {len(species_list)} species from GBIF...")
        for species_name in species_list:
            url = f"https://api.gbif.org/v1/species/match?name={species_name}&verbose=true"
            response = requests.get(url)
            data = response.json()
            if data.get('status') in ['ACCEPTED', 'SYNONYM']:
                family, genus = data.get('family'), data.get('genus')
                if family and genus:
                    if family not in taxonomy[1]: taxonomy[1].append(family)
                    taxonomy[2][genus] = family
                    taxonomy[3][species_name] = genus
                else: raise RuntimeError(f"{species_name} - missing family/genus data")
            else: raise RuntimeError(f"{species_name} not found in GBIF")
        taxonomy[1] = sorted(list(set(taxonomy[1])))
        return taxonomy

    def initialize_sensing_garden_client(self):
        try:
            return SensingGardenClient(
                base_url=os.environ.get('API_BASE_URL'),
                api_key=os.environ.get('SENSING_GARDEN_API_KEY'),
                aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
                aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
                aws_region=os.environ.get('AWS_REGION', 'us-east-1')
            )
        except Exception as e:
            logger.error(f"Failed to initialize SensingGardenClient: {e}")
            return None

    def processor_worker(self):
        """Worker thread to process videos from the queue."""
        logger.info("🔍 Starting video processor worker...")
        
        while not self.stop_event.is_set() or not self.video_queue.empty():
            try:
                video_path = self.video_queue.get(timeout=1)
                
                logger.info(f"--- Processing Video: {video_path.name} ---")
                
                self.run_inference_on_video(video_path)
                self.upload_video_file(video_path)
                self.delete_video(video_path)
                
                self.video_queue.task_done()
                
            except queue.Empty:
                if self.stop_event.is_set():
                    break
                continue
            except Exception as e:
                logger.error(f"❌ Processor worker error: {e}", exc_info=True)
        
        logger.info("🔍 Video processor worker stopped")

    def run_inference_on_video(self, video_path):
        """Run the full inference process on a video file."""
        logger.info(f"🧠 Running inference on {video_path.name}")
        
        # Log tracking state before processing
        if self.tracker:
            stats = self.tracker.get_tracking_stats()
            logger.info(f"📊 Tracker state before {video_path.name}: {stats['active_tracks']} active, {stats['lost_tracks']} lost tracks")
            if stats['active_tracks'] > 0:
                logger.info(f"🔗 Cross-video tracking: Continuing with existing tracks: {stats['active_track_ids'][:3]}{'...' if len(stats['active_track_ids']) > 3 else ''}")
        
        try:
            processor = VideoInferenceProcessor(
                # Pass the pre-loaded taxonomy data
                class_names=self.class_names,
                families=self.families,
                genera=self.genera,
                genus_to_family=self.genus_to_family,
                species_to_genus=self.species_to_genus,
                # Pass other configs
                enable_uploads=self.enable_uploads,
                device_id=self.device_id,
                confidence_threshold=self.confidence_threshold
            )
            frames_processed = process_video(
                video_path=str(video_path), 
                processor=processor,
                tracker=self.tracker,
                start_frame_count=self.global_frame_count
            )
            self.global_frame_count += frames_processed
            
            # Log tracking state after processing
            if self.tracker:
                stats_after = self.tracker.get_tracking_stats()
                logger.info(f"📊 Tracker state after {video_path.name}: {stats_after['active_tracks']} active, {stats_after['lost_tracks']} lost tracks")
            
            if self.enable_uploads:
                processor.upload_all_detections()

        except Exception as e:
            logger.error(f"Error during inference for {video_path.name}: {e}")

    def should_upload_video(self):
        """Determine if this video should be uploaded based on percentage."""
        return random.randint(1, 100) <= self.upload_percentage

    def upload_video_file(self, video_path):
        """
        Extracts a random segment of the video and uploads it.
        The duration of the segment is determined by self.upload_percentage.
        """
        if not self.enable_uploads or not self.sgc or self.upload_percentage == 0:
            if self.upload_percentage > 0:
                logger.warning(f"Uploads disabled, skipping video upload for {video_path.name}")
            return
        
        if not (0 < self.upload_percentage <= 100):
            logger.error(f"Invalid upload percentage: {self.upload_percentage}. Must be between 1 and 100.")
            return

        cap = None
        out = None
        temp_segment_path = None
        try:
            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                logger.error(f"Could not open video file to create segment: {video_path.name}")
                return

            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

            if total_frames == 0 or fps == 0:
                logger.error(f"Video {video_path.name} has no frames or invalid FPS, cannot create segment.")
                return

            # Calculate segment length in frames
            segment_length_frames = int(total_frames * (self.upload_percentage / 100.0))
            if segment_length_frames <= 0:
                logger.warning(f"Calculated segment length is 0 frames for {video_path.name}. Skipping upload.")
                return

            # Determine random start frame
            max_start_frame = total_frames - segment_length_frames
            start_frame = random.randint(0, max_start_frame) if max_start_frame > 0 else 0

            # Create a temporary path for the segment
            temp_segment_path = video_path.with_name(f"segment_{video_path.name}")

            logger.info(f"📤 Creating a {self.upload_percentage}% ({segment_length_frames / fps:.1f}s) segment from {video_path.name}")
            
            # Set up writer for the segment
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(str(temp_segment_path), fourcc, fps, (width, height))

            # Position the capture to the start frame
            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
            
            frames_written = 0
            while frames_written < segment_length_frames:
                ret, frame = cap.read()
                if not ret:
                    break
                out.write(frame)
                frames_written += 1

            # Release resources before upload
            cap.release()
            cap = None
            out.release()
            out = None

            if not temp_segment_path.exists() or temp_segment_path.stat().st_size == 0:
                logger.error("Failed to create a valid video segment. Skipping upload.")
                return

            # --- Derive timestamp from original filename ---
            timestamp_date_str = video_path.stem.split('_')[1]
            timestamp_time_str = video_path.stem.split('_')[2]
            timestamp_str = timestamp_date_str + "_" + timestamp_time_str
            video_datetime = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
            iso_timestamp = video_datetime.isoformat()
            
            logger.info(f"📤 Uploading video segment: {temp_segment_path.name} with timestamp {iso_timestamp}")
            with open(temp_segment_path, "rb") as f:
                video_data = f.read()

            self.sgc.videos.upload_video(
                device_id=self.device_id,
                timestamp=iso_timestamp,
                video_path_or_data=video_data,
                content_type="video/mp4"
            )
            logger.info(f"✅ Video segment uploaded successfully: {temp_segment_path.name}")
        except Exception as e:
            logger.error(f"❌ Error creating or uploading video segment for {video_path.name}: {e}", exc_info=True)
        finally:
            if cap:
                cap.release()
            if out:
                out.release()
            if temp_segment_path and temp_segment_path.exists():
                try:
                    temp_segment_path.unlink()
                    logger.info(f"🗑️ Deleted temporary segment: {temp_segment_path.name}")
                except Exception as e:
                    logger.error(f"⚠️ Could not delete temporary segment {temp_segment_path.name}: {e}")
            
    def delete_video(self, video_path):
        """Delete a video file after processing."""
        try:
            video_path.unlink()
            logger.info(f"🗑️ Deleted video: {video_path.name}")
        except Exception as e:
            logger.error(f"⚠️ Could not delete video {video_path.name}: {e}")

    def start(self):
        """Start the continuous pipeline."""
        logger.info("🚀 Starting Continuous Pipeline...")
        
        # Scan for and queue any existing videos from previous runs
        logger.info(f"Scanning for existing videos in {self.video_dir}...")
        try:
            existing_videos = sorted(self.video_dir.glob("*.mp4"))
            if existing_videos:
                logger.info(f"Found {len(existing_videos)} existing video(s). Adding to processing queue.")
                for video_path in existing_videos:
                    self.video_queue.put(video_path)
            else:
                logger.info("No existing videos found.")
        except Exception as e:
            logger.error(f"Error scanning for existing videos: {e}")

        #self.recorder_thread = threading.Thread(target=self.recorder.start_continuous_recording, daemon=True)
        self.processor_thread = threading.Thread(target=self.processor_worker, daemon=True)
        self.recorder_thread.start()
        self.processor_thread.start()
        logger.info("✅ All worker threads started")
        
    def stop(self):
        """Stop the continuous pipeline gracefully, ensuring all work is finished."""
        logger.info("🔄 Stopping pipeline... recorder will finish current segment.")
        
        # 1. Signal recorder to stop. It will finish its current segment and push it to the queue.
        self.recorder.stop()
        # 2. Wait for the recorder thread to finish its job.
        if self.recorder_thread and self.recorder_thread.is_alive():
            self.recorder_thread.join()
        logger.info("✅ Recorder thread has stopped.")
        
        # 3. Wait for the processor to clear the queue.
        logger.info("...waiting for processor to finish all remaining videos...")
        self.video_queue.join()
        
        # 4. Signal the processor worker to stop now that the queue is empty.
        self.stop_event.set()
        if self.processor_thread and self.processor_thread.is_alive():
            self.processor_thread.join()
        logger.info("✅ Processor thread has stopped.")
        
        logger.info("✅ Pipeline stopped gracefully.")

def main():
    parser = argparse.ArgumentParser(description='Continuous video recording and inference pipeline.')
    parser.add_argument('--video-dir', type=str, default='recordings', help='Directory to save and monitor videos.')
    parser.add_argument('--duration', type=int, default=300, help='Duration of each video segment in seconds.')
    parser.add_argument('--upload-percentage', type=int, default=10, help='Percentage of video *duration* to upload as a random segment (0-100).')
    parser.add_argument('--device-id', type=str, default='pipeline', help='Device identifier for uploads.')
    parser.add_argument('--fps', type=int, default=15, help='Recording frame rate.')
    parser.add_argument('--resolution', type=str, default='640x640', help='Recording resolution in WIDTHxHEIGHT format.')
    parser.add_argument('--confidence', type=float, default=0.35, help='Confidence threshold for detections.')
    parser.add_argument('--disable-uploads', action='store_true', help='Disable all database uploads (detections and videos).')
    parser.add_argument('--recording-start-hour', type=int, default=6, help='Hour to start recording (24-hour format, default 6 = 6am).')
    parser.add_argument('--recording-end-hour', type=int, default=22, help='Hour to stop recording (24-hour format, default 22 = 10pm).')
    
    args = parser.parse_args()
    
    try:
        width, height = map(int, args.resolution.split('x'))
        resolution = (width, height)
    except ValueError:
        logger.error(f"Error: Invalid resolution format '{args.resolution}'. Use WIDTHxHEIGHT.")
        return 1
    
    # Validate recording hours
    if not (0 <= args.recording_start_hour <= 23) or not (0 <= args.recording_end_hour <= 23):
        logger.error(f"Error: Recording hours must be between 0 and 23. Got start={args.recording_start_hour}, end={args.recording_end_hour}")
        return 1
    
    if args.recording_start_hour >= args.recording_end_hour:
        logger.error(f"Error: Recording start hour ({args.recording_start_hour}) must be less than end hour ({args.recording_end_hour})")
        return 1
    
    pipeline = ContinuousPipeline(
        video_dir=args.video_dir,
        recording_duration=args.duration,
        upload_percentage=args.upload_percentage,
        device_id=args.device_id,
        fps=args.fps,
        resolution=resolution,
        enable_uploads=not args.disable_uploads,
        confidence_threshold=args.confidence,
        recording_start_hour=args.recording_start_hour,
        recording_end_hour=args.recording_end_hour
    )
    
    try:
        pipeline.start()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("🛑 Shutdown initiated by user.")
    except Exception as e:
        logger.error(f"💥 Fatal error in main loop: {e}", exc_info=True)
    finally:
        pipeline.stop()
    
    return 0

if __name__ == "__main__":
    exit(main())

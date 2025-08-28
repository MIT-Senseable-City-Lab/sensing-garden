import cv2
import time
import numpy as np
from detection import run_inference
from classification import infer_image
from picamera2 import Picamera2
import threading
import requests
import json
from streamserver import StreamServer
import queue



class MothDetection: 
    def __init__(self, class_names_path="/home/sg/sensing-garden/moth/36_species.txt", confidence_threshold=0.55,
                 model_path="/home/sg/sensing-garden/resources/yolov11s.hef",
                 classification_model="/home/sg/sensing-garden/moth/bplusplus-multitask-36.hef"):
        
        self.class_names_path = class_names_path
        self.confidence_threshold = confidence_threshold
        self.model_path = model_path
        self.classification_model = classification_model

        # --- Centralized Taxonomy Initialization ---
        print("Initializing taxonomy...")
        try:
            self.class_names = self.load_class_names()            
            with open('36_species.json') as f:
                d = json.load(f)
                for key, value in d.items():
                    if key == "1":
                        self.families = value
                    elif key == "2":
                        self.genus_to_family = value
                    elif key == "3":
                        self.species_to_genus = value

            self.genera = list(self.genus_to_family.keys())
            print(f"Built taxonomy: {len(self.families)} families, {len(self.genera)} genera")
            
            print("✅ Taxonomy initialized successfully.")
        except Exception as e:
            print(f"❌ Failed to initialize taxonomy: {e}. Exiting.")
            raise

        # defining buffer for livestream processing
        self.frame_buffer = queue.Queue(maxsize=5)
        self.raw_buffer = queue.Queue(maxsize=5)
        self.process_thread = None

    def load_class_names(self):
        with open(self.class_names_path, 'r') as f:
            class_names = [line.strip() for line in f.readlines()]
        print(f"Loaded {len(class_names)} class names")
        return class_names

    def process_classification_results(self, classification_results, detection_data):
            class_names = self.class_names
            nr_genus = 33 # TODO edit
            nr_family = 9 # TODO edit
            nr_species = 36 # TODO edit
            for stream_name, result in classification_results.items():
                max_prob = np.max(result)
                top_indices = np.where(result >= (max_prob - 0.01))[0]
                if result.shape == (nr_species,):  # Species
                    detection_data["species"] = " | ".join([
                        class_names[idx] if idx < len(class_names) else f"Species {idx}" 
                        for idx in top_indices
                    ])
                    detection_data["species_confidence"] = float(max_prob)
                
                elif result.shape == (nr_genus,):  # Genus
                    detection_data["genus"] = " | ".join([
                        self.genera[idx] if idx < len(self.genera) else f"Genus {idx}" 
                        for idx in top_indices
                    ])
                    detection_data["genus_confidence"] = float(max_prob)
                elif result.shape == (nr_family,):  # Family
                    detection_data["family"] = " | ".join([
                        self.families[idx] if idx < len(self.families) else f"Family {idx}" 
                        for idx in top_indices
                    ])
                    detection_data["family_confidence"] = float(max_prob)
            
            return detection_data
    
    def draw_detection(self, frame, x, y, x2, y2, confidence, detection_data):
        COLORS = {
            "box": (31, 193, 149),       # old (149, 193, 31)
            "species": (0,0,0),    # warm amber
            "genus": (0,0,0),       # green
            "family": (0, 0, 0)     # purple
        }
        # Draw bounding box
        cv2.rectangle(frame, (x, y), (x2, y2), COLORS["box"], 2)

        # Confidence label (white text on semi-transparent background)
        #conf_text = f"{confidence:.2f}"
        conf_text = f"{detection_data['species_confidence']:.2f}"
        (tw, th), _ = cv2.getTextSize(conf_text, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
        cv2.rectangle(frame, (x, y - th - 6), (x + tw + 4, y), (31, 193, 149), -1)  # solid rect
        cv2.putText(frame, conf_text, (x + 2, y - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)

        # Vertical spacing for labels
        label_y = y2 + 20
        label_gap = 22

        

        if detection_data["species"]:
            text = f"{detection_data['species']}"
            cv2.putText(frame, text, (x, label_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, COLORS["species"], 1)
            label_y += label_gap

        if detection_data["genus"]:
            text = f"Genus: {detection_data['genus']}"
            cv2.putText(frame, text, (x, label_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, COLORS["genus"], 1)
            label_y += label_gap

        if detection_data["family"]:
            text = f"Family: {detection_data['family']}"
            cv2.putText(frame, text, (x, label_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, COLORS["family"], 1)
            
        return frame

    def process_frame(self, frame, batch_size=1):
            """Process a single frame from the video."""
            
            # Convert BGR to RGB for inference
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb_frame_float32 = rgb_frame.astype(np.float32)
            
            infer_results = run_inference(
                net=self.model_path,
                input=rgb_frame_float32,
                batch_size=batch_size,
                labels=self.class_names_path,
                save_stream_output=False
            )
        
            
            # First pass: collect all valid detections for tracking
            valid_detections = []
            valid_detection_data = []
            
            if len(infer_results) > 0:
                height, width = frame.shape[:2]
                
                for detection in infer_results:
                    #if len(detection) != 5:
                    #    continue
                    y_min, x_min, y_max, x_max, confidence = detection
                    
                    if confidence < self.confidence_threshold:
                        continue
                    
                    # Convert to pixel coordinates
                    x, y = int(x_min * width), int(y_min * height)
                    x2, y2 = int(x_max * width), int(y_max * height)
                    
                    # Clamp coordinates
                    x, y, x2, y2 = max(0, x), max(0, y), min(width, x2), min(height, y2)
                    
                    if x2 <= x or y2 <= y:
                        continue
                    
                    # Store detection for tracking (x1, y1, x2, y2 format)
                    valid_detections.append([x, y, x2, y2])
                    valid_detection_data.append({
                        'detection': detection,
                        'x': x, 'y': y, 'x2': x2, 'y2': y2,
                        'confidence': confidence
                    })
            
            print('num detections: ', len(valid_detections))
            # Classify each detection 
            for i, det_data in enumerate(valid_detection_data):
                x, y, x2, y2 = det_data['x'], det_data['y'], det_data['x2'], det_data['y2']
                confidence = det_data['confidence']

                # Perform classification on the RGB frame crop
                cropped_region = cv2.resize(rgb_frame[y:y2, x:x2], (224, 224))
                classification_results = infer_image(cropped_region, hef_path=self.classification_model)
                

                detection_data = {
                "family": None, "genus": None, "species": None,
                "family_confidence": None, "genus_confidence": None, "species_confidence": None}
                
                detection_data = self.process_classification_results(classification_results, detection_data)
                
                print('species: ', detection_data["species"], ' confidence: ', detection_data["species_confidence"])

                # Draw bounding box and track ID if showing boxes
                frame = self.draw_detection(frame, x, y, x2, y2, confidence, detection_data)
                
            cv2.imwrite('test-multiple-moths.jpeg', frame)    
            # add frame to buffer for threading
            return frame
    
    def process_raw_frames(self):
        while True:

            try:
                frame = self.raw_buffer.get(block=True, timeout=1)
            except queue.Empty:
                continue  # Or sleep briefly and retry

            processed_frame = self.process_frame(frame)

            try:
                self.frame_buffer.put(processed_frame, block=False)
            except queue.Full:
                self.frame_buffer.get()  # Remove oldest to make space
                self.frame_buffer.put(processed_frame)





    def process_video_stream(self):
        picam2 = Picamera2()
        fps = 1
        video_configuration = picam2.create_video_configuration(
            main={"size": (1080, 1080), "format": "RGB888"}
        )
        picam2.configure(video_configuration)
        picam2.set_controls({"FrameRate": fps, "AeEnable": True})
        picam2.start()

        try:
            print("Camera initializing...")
            time.sleep(2)
            print("Camera ready.")
            frame_interval = 1 / fps

            while True:
                start_time = time.time()
                array = picam2.capture_array()
                try:
                    self.raw_buffer.put(array, block=True, timeout=1)
                except queue.Full:
                    # Buffer full; could skip frame or log warning
                    pass
                
                elapsed = time.time() - start_time
                sleep_time = max(0, frame_interval - elapsed)
                time.sleep(sleep_time)
        except Exception as e:
            print(f"Failed to initialize camera: {e}", exc_info=True)
            raise
        finally:
            picam2.stop()

    


    def start(self):
        self.process_thread = threading.Thread(target=self.process_video_stream)
        self.process_thread.start()
        print("threads started")


#from PIL import Image
#pipeline = MothDetection()
#img = cv2.imread("/home/sg/sensing-garden/moth/cropped-moth-test-2.jpg")
#imgarray = np.asarray(img) 
#pipeline.process_frame(imgarray)


def main():

    pipeline = MothDetection()
    server = StreamServer(pipeline.frame_buffer)
    threading.Thread(target=server.run, daemon=True).start()
    threading.Thread(target=pipeline.process_raw_frames).start()

        
    try:
        pipeline.start()

        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("🛑 Shutdown initiated by user.")
    except Exception as e:
        print(f"💥 Fatal error in main loop: {e}", exc_info=True)
    finally:
        pipeline.stop()
    
    return 0

if __name__ == "__main__":
    exit(main())


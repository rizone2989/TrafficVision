# detector.py
from ultralytics import YOLO
import cv2
import numpy as np

class TrafficDetector:
    def __init__(self, vehicle_model_path, ambulance_model_path):
        """
        Initializes the object detector with TWO YOLOv8 models.
        """
        self.vehicle_model = YOLO(vehicle_model_path)
        self.ambulance_model = YOLO(ambulance_model_path)

        # --- Vehicle Model Config ---
        self.vehicle_model.classes_to_detect = [2, 3, 5, 7] # car, motorcycle, bus, truck
        self.vehicle_class_names = {
            2: 'Car',
            3: 'Motorcycle',
            5: 'Bus',
            7: 'Truck'
        }
        
        # --- Ambulance Model Config ---
        self.ambulance_model.classes_to_detect = [0] # 'Ambulance'
        self.ambulance_class_names = {
            0: 'Ambulance'
        }
        
        self.ambulance_threshold = 0.70
        
        # --- Plotting Config ---
        all_names = list(self.vehicle_class_names.values()) + list(self.ambulance_class_names.values())
        self.colors = np.random.uniform(0, 255, size=(len(all_names), 3))
        self.class_name_to_color_index = {name: i for i, name in enumerate(all_names)}

        print("Vehicle and Ambulance models loaded successfully.")

    def yolo2bbox(self, bboxes):
        """Converts YOLO format to [xmin, ymin, xmax, ymax]"""
        xmin, ymin = bboxes[0] - bboxes[2] / 2, bboxes[1] - bboxes[3] / 2
        xmax, ymax = bboxes[0] + bboxes[2] / 2, bboxes[1] + bboxes[3] / 2
        return xmin, ymin, xmax, ymax

    def plot_box(self, image, bboxes, labels, confs):
        """Draws boxes and labels on the image."""
        h, w, _ = image.shape
        for box_num, box in enumerate(bboxes):
            x1, y1, x2, y2 = self.yolo2bbox(box)
            xmin, ymin, xmax, ymax = int(x1 * w), int(y1 * h), int(x2 * w), int(y2 * h)
            
            class_name = labels[box_num]
            confidence = confs[box_num]
            
            color = self.colors[self.class_name_to_color_index[class_name]]

            cv2.rectangle(image, (xmin, ymin), (xmax, ymax), color=color, thickness=2)

            font_scale = min(1, max(3, int(w / 500)))
            font_thickness = min(2, max(10, int(w / 50)))
            
            label = f"{class_name} {confidence:.2f}"
            cv2.putText(image, label, (xmin + 1, ymin - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255, 255, 255), font_thickness)
        return image
    
    def process_frame(self, frame):
        """
        Processes a frame and returns detailed counts and ambulance status.
        :return: A tuple containing:
                 - processed_frame: The frame with filtered boxes drawn.
                 - ambulance_detected: Boolean (True if ambulance > 70% conf).
                 - detailed_counts: Dict of vehicle counts {'Car': X, 'Bus': Y, ...}
        """
        
        bboxes_to_plot = []
        labels_to_plot = []
        confs_to_plot = []
        
        # This dictionary will hold the counts for THIS frame
        detailed_counts = {'Car': 0, 'Bus': 0, 'Truck': 0, 'Motorcycle': 0, 'Ambulance': 0}
        ambulance_detected = False
        frame_height, frame_width = frame.shape[:2]

        # 1. Run detection for standard vehicles
        vehicle_results = self.vehicle_model(
            frame, 
            classes=self.vehicle_model.classes_to_detect, 
            verbose=False
        )
        
        for det in vehicle_results[0].boxes:
            cls = int(det.cls[0].item())
            class_name = self.vehicle_class_names[cls]
            detailed_counts[class_name] += 1
            
            # Add to plot list
            xywh = det.xywh[0].cpu().numpy()
            bboxes_to_plot.append([
                xywh[0] / frame_width, xywh[1] / frame_height,
                xywh[2] / frame_width, xywh[3] / frame_height
            ])
            labels_to_plot.append(class_name)
            confs_to_plot.append(det.conf[0].item())

        # 2. Run detection for ambulances
        ambulance_results = self.ambulance_model(
            frame, 
            classes=self.ambulance_model.classes_to_detect, 
            verbose=False
        )
        
        for det in ambulance_results[0].boxes:
            conf = det.conf[0].item() # Get the confidence score
            
            if conf >= self.ambulance_threshold:
                ambulance_detected = True
                detailed_counts['Ambulance'] += 1
                
                # Add to plot list
                cls = int(det.cls[0].item())
                class_name = self.ambulance_class_names[cls]
                xywh = det.xywh[0].cpu().numpy()
                bboxes_to_plot.append([
                    xywh[0] / frame_width, xywh[1] / frame_height,
                    xywh[2] / frame_width, xywh[3] / frame_height
                ])
                labels_to_plot.append(class_name)
                confs_to_plot.append(conf)

        # 3. Plot all valid boxes
        processed_frame = self.plot_box(frame, bboxes_to_plot, labels_to_plot, confs_to_plot)
        
        return processed_frame, ambulance_detected, detailed_counts
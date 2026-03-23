import time
import threading

class TrafficLogic:
    """
    Manages the state of the traffic light system and tracks statistics.
    
    NEW:
    - Tracks cumulative vehicle counts for analysis.
    - Tracks the last green time duration for each lane.
    - get_analysis_data() provides all data for the new dashboard.
    """
    
    def __init__(self):
        # --- Standard Lane State ---
        self.lanes = {
            1: {'density': 0, 'ambulance': False, 'status': 'red', 'current_vehicle_counts': self._create_empty_count()},
            2: {'density': 0, 'ambulance': False, 'status': 'red', 'current_vehicle_counts': self._create_empty_count()},
            3: {'density': 0, 'ambulance': False, 'status': 'red', 'current_vehicle_counts': self._create_empty_count()},
            4: {'density': 0, 'ambulance': False, 'status': 'red', 'current_vehicle_counts': self._create_empty_count()}
        }
        
        # --- NEW: Statistics Storage ---
        self.cumulative_counts = {
            1: self._create_empty_count(),
            2: self._create_empty_count(),
            3: self._create_empty_count(),
            4: self._create_empty_count()
        }
        self.last_green_times = {1: 0, 2: 0, 3: 0, 4: 0}
        
        # --- Timers and Configuration ---
        self.timer = 0
        self.base_green_time = 5
        self.orange_light_duration = 3
        self.max_extra_time = 15
        
        self.ambulance_override = False
        self.lock = threading.Lock() 

        # --- Fixed Cycle Logic ---
        self.priority_order = [1, 2, 3, 4]
        self.current_priority_index = 0 
        self.current_active_lane = self.priority_order[self.current_priority_index] # Lane 1
        
        self.lanes[self.current_active_lane]['status'] = 'green'
        self.current_green_duration = self.base_green_time 
        
        self.is_first_run = True
        
        self.logic_thread = threading.Thread(target=self._run_logic, daemon=True)
        self.logic_thread.start()

    def _create_empty_count(self):
        """Helper to create a zeroed-out count dictionary."""
        return {'Car': 0, 'Bus': 0, 'Truck': 0, 'Motorcycle': 0, 'Ambulance': 0}

    def update_lane_data(self, lane_id, density, ambulance, detailed_counts):
        """Called by the Flask video processor to update real-time data."""
        with self.lock:
            self.lanes[lane_id]['density'] = density
            self.lanes[lane_id]['ambulance'] = ambulance
            # Store the latest snapshot of vehicle types
            self.lanes[lane_id]['current_vehicle_counts'] = detailed_counts

    def get_system_state(self):
        """Called by the main dashboard API."""
        with self.lock:
            state_copy = {}
            time_remaining = 0
            
            for i in range(1, 5):
                lane = self.lanes[i]
                state_copy[i] = {
                    'status': lane['status'],
                    'density': lane['density'],
                    'ambulance': lane['ambulance']
                }

            # Check for the active lane, as it's the only one with a timer
            if self.current_active_lane in state_copy:
                active_status = state_copy[self.current_active_lane]['status']
                
                if active_status == 'green':
                    time_remaining = self.current_green_duration - self.timer
                elif active_status == 'orange':
                    time_remaining = self.orange_light_duration - self.timer
                
                state_copy[self.current_active_lane]['time_remaining'] = max(0, time_remaining)

            return state_copy

    def get_analysis_data(self):
        """Called by the new analysis page API."""
        with self.lock:
            # Send all the data needed for the graphs
            return {
                'cumulative_counts': self.cumulative_counts,
                'current_density': {i: self.lanes[i]['density'] for i in range(1, 5)},
                'last_green_times': self.last_green_times
            }

    def _run_logic(self):
        """The main logic loop."""
        while True:
            time.sleep(1)
            
            with self.lock:
                
                # --- 1. Startup Logic ---
                if self.is_first_run:
                    print("System startup: Calculating initial green time for Lane 1.")
                    self._set_green_light(self.current_active_lane) 
                    self.is_first_run = False
                    self.timer = 0
                    continue

                # --- 2. Ambulance Override Logic ---
                ambulance_lanes_detected = [i for i in range(1, 5) if self.lanes[i]['ambulance']]
                
                if ambulance_lanes_detected:
                    priority_ambulance_lane = min(ambulance_lanes_detected) # Give priority to Lane 1, then 2, etc.

                    if not self.ambulance_override:
                        print(f"AMBULANCE DETECTED! Priority to Lane {priority_ambulance_lane}.")
                    self.ambulance_override = True
                    
                    if self.lanes[priority_ambulance_lane]['status'] == 'green':
                        self.timer = 0 # Keep it green
                    else:
                        if self.lanes[self.current_active_lane]['status'] != 'red':
                            print(f"Ambulance override: Forcing Lane {self.current_active_lane} to Red.")
                            # When forcing a lane red, we *don't* count its vehicles as "passed"
                            self.lanes[self.current_active_lane]['status'] = 'red'
                        
                        self._set_green_light(priority_ambulance_lane, is_ambulance=True)
                    
                    continue 
                
                # --- 3. Ambulance Reset Logic ---
                if self.ambulance_override and not ambulance_lanes_detected:
                    print("Ambulance clear. Resuming normal cycle.")
                    self.ambulance_override = False
                    
                    if self.lanes[self.current_active_lane]['status'] == 'green':
                        print(f"Finishing ambulance cycle for Lane {self.current_active_lane}.")
                        self._set_orange_light(self.current_active_lane)
                
                # --- 4. NORMAL FIXED-CYCLE (Green -> Orange -> Red) ---
                self.timer += 1
                
                current_status = self.lanes[self.current_active_lane]['status']

                if current_status == 'green' and self.timer >= self.current_green_duration:
                    self._set_orange_light(self.current_active_lane)
                
                elif current_status == 'orange' and self.timer >= self.orange_light_duration:
                    
                    # --- NEW: UPDATE CUMULATIVE COUNTS ---
                    # The light is now red. Count all vehicles that were in the lane.
                    current_counts = self.lanes[self.current_active_lane].get('current_vehicle_counts', self._create_empty_count())
                    for vehicle, count in current_counts.items():
                        self.cumulative_counts[self.current_active_lane][vehicle] += count
                    print(f"Lane {self.current_active_lane} turning red. Added {current_counts} to cumulative total.")
                    
                    # 1. Set current lane to red
                    self.lanes[self.current_active_lane]['status'] = 'red'
                    
                    # 2. Get the next lane
                    self.current_priority_index = (self.current_priority_index + 1) % len(self.priority_order)
                    
                    if self.current_priority_index == 0:
                        print("\n--- Full cycle complete. Restarting from Lane 1. ---")

                    next_lane = self.priority_order[self.current_priority_index]
                        
                    print(f"Switching light: Next Lane {next_lane} (Green)")
                    self._set_green_light(next_lane)
    
    def _set_orange_light(self, lane_id):
        """Helper function to set a lane to orange."""
        self.lanes[lane_id]['status'] = 'orange'
        self.timer = 0
        print(f"Lane {lane_id} is now Orange for {self.orange_light_duration}s")

    def _set_green_light(self, lane_id, is_ambulance=False):
        """
        Helper function to set a lane to green and calculate its duration.
        """
        for i in range(1, 5):
            if i != lane_id:
                self.lanes[i]['status'] = 'red'
        
        self.lanes[lane_id]['status'] = 'green'
        self.current_active_lane = lane_id
        
        if is_ambulance:
            self.current_green_duration = self.base_green_time + self.max_extra_time
            # Don't store ambulance override time in the analysis
        else:
            density = self.lanes[lane_id]['density']
            extra_time = min(density, self.max_extra_time)
            self.current_green_duration = self.base_green_time + extra_time
            # Store this duration for the analysis graph
            self.last_green_times[lane_id] = self.current_green_duration
        
        self.timer = 0 
        print(f"Lane {lane_id} is Green for {self.current_green_duration}s (Density: {self.lanes[lane_id]['density']})")
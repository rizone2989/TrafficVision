import os
import cv2
import traceback
import sqlite3
import hashlib
from flask import Flask, render_template, request, redirect, url_for, Response, jsonify, session, flash
from detector import TrafficDetector
from traffic_logic import TrafficLogic

# --- Configuration ---
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv'}
DATABASE = 'users.db'

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['SECRET_KEY'] = 'your_super_secret_key_for_sessions' # Change this in a real application

# --- Database Setup ---
def setup_database():
    """Creates the database and user table if they don't exist."""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    # Create table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        )
    ''')
    
    # Check if the admin user already exists
    cursor.execute("SELECT * FROM users WHERE username = ?", ('traffic-admin',))
    if cursor.fetchone() is None:
        # Hash the password before storing
        password = 'adminpassword'
        hashed_password = hashlib.sha256(password.encode()).hexdigest()
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", ('traffic-admin', hashed_password))
        print("Admin user created.")

    conn.commit()
    conn.close()

# --- Global Variables & Initializations ---
video_paths = { 1: None, 2: None, 3: None, 4: None }
video_caps = { 1: None, 2: None, 3: None, 4: None }

try:
    detector = TrafficDetector(vehicle_model_path='yolov8n.pt', ambulance_model_path='best.pt')
except Exception as e:
    print(f"Error loading YOLO models: {e}")
    detector = None

traffic_manager = TrafficLogic()

# --- Helper Functions (No Change) ---
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def draw_ui_elements(frame, lane_id, density, ambulance, status):
    # This function remains unchanged from the previous version
    cv2.rectangle(frame, (10, 10), (70, 170), (50, 50, 50), -1) 
    cv2.rectangle(frame, (10, 10), (70, 170), (255, 255, 255), 1)
    red_color = (0,0,255) if status=='red' else (40,40,40)
    orange_color = (0,165,255) if status=='orange' else (40,40,40)
    green_color = (0,255,0) if status=='green' else (40,40,40)
    cv2.circle(frame, (40, 40), 20, red_color, -1) 
    cv2.circle(frame, (40, 90), 20, orange_color, -1)
    cv2.circle(frame, (40, 140), 20, green_color, -1) 
    cv2.putText(frame, f"Lane: {lane_id}", (10, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(frame, f"Density: {density}", (10, 230), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    if ambulance:
        cv2.putText(frame, "AMBULANCE!", (10, 260), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2, cv2.LINE_AA)
    return frame

# --- Video Streaming Generator (Modified to use new detector logic) ---
def generate_frames(lane_id):
    # This function remains unchanged from the previous version
    global video_caps
    video_path = video_paths.get(lane_id)
    if not video_path: return

    if video_caps[lane_id] is None:
        try:
            video_caps[lane_id] = cv2.VideoCapture(video_path)
            if not video_caps[lane_id].isOpened(): return
        except Exception as e: return
            
    cap = video_caps[lane_id]
    while True:
        try:
            ret, frame = cap.read()
            if not ret:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
            
            if detector:
                processed_frame, ambulance_detected, detailed_counts = detector.process_frame(frame)
                density = sum(detailed_counts.values())
            else:
                processed_frame, density, ambulance_detected, detailed_counts = frame, 0, False, {}
            
            traffic_manager.update_lane_data(lane_id, density, ambulance_detected, detailed_counts)
            current_state = traffic_manager.get_system_state()
            lane_status = current_state[lane_id]['status']
            final_frame = draw_ui_elements(processed_frame, lane_id, density, ambulance_detected, lane_status)
            
            (flag, encodedImage) = cv2.imencode(".jpg", final_frame)
            if not flag: continue

            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + bytearray(encodedImage) + b'\r\n')
        except Exception as e:
            traceback.print_exc()
            break 
    print(f"Stopping stream for lane {lane_id}.")

# --- MODIFIED & NEW FLASK ROUTES ---

@app.route('/', methods=['GET', 'POST'])
def login():
    """Handles user login."""
    if 'logged_in' in session:
        return redirect(url_for('home')) # Redirect if already logged in

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        # Hash the input password to compare with the stored hash
        hashed_password = hashlib.sha256(password.encode()).hexdigest()

        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, hashed_password))
        user = cursor.fetchone()
        conn.close()

        if user:
            session['logged_in'] = True
            session['username'] = username
            flash('Login successful!', 'success')
            return redirect(url_for('home'))
        else:
            flash('Invalid credentials. Please try again.', 'danger')

    return render_template('login.html')

@app.route('/home')
def home():
    """Serves the main project home page (post-login)."""
    if 'logged_in' not in session:
        return redirect(url_for('login'))
    return render_template('project_home.html')

@app.route('/logout')
def logout():
    """Logs the user out."""
    session.pop('logged_in', None)
    session.pop('username', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/upload', methods=['GET', 'POST'])
def upload_page():
    """Handles video uploads."""
    if 'logged_in' not in session:
        return redirect(url_for('login'))
        
    global video_paths, video_caps
    if request.method == 'POST':
        video_caps = {1: None, 2: None, 3: None, 4: None}
        for i in range(1, 5):
            file_key = f'video{i}'
            if file_key not in request.files: continue
            file = request.files[file_key]
            if file.filename == '' or not allowed_file(file.filename): continue
            filename = f'lane_{i}.' + file.filename.rsplit('.', 1)[1].lower()
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(save_path)
            video_paths[i] = save_path
        return redirect(url_for('dashboard'))
    return render_template('upload.html')

@app.route('/dashboard')
def dashboard():
    """Serves the main traffic dashboard."""
    if 'logged_in' not in session:
        return redirect(url_for('login'))
    if not all(video_paths.values()):
        return redirect(url_for('upload_page'))
    return render_template('dashboard.html')

@app.route('/analysis')
def analysis_page():
    """Serves the analysis page."""
    if 'logged_in' not in session:
        return redirect(url_for('login'))
    return render_template('analysis.html')

# --- API Routes (Protected) ---
@app.route('/video_feed/<int:lane_id>')
def video_feed(lane_id):
    if 'logged_in' not in session:
        return "Unauthorized", 401
    if lane_id not in [1, 2, 3, 4]:
        return "Invalid Lane ID", 404
    return Response(generate_frames(lane_id), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/status_api')
def status_api():
    if 'logged_in' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(traffic_manager.get_system_state())

@app.route('/api/analysis_data')
def analysis_data():
    if 'logged_in' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(traffic_manager.get_analysis_data())

# --- Run Application ---
if __name__ == '__main__':
    setup_database() # This will create the DB and user on first run
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
    app.run(debug=False, host='0.0.0.0', threaded=True)
import os
import logging
import requests
import math
import uuid
from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import timedelta
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "s3cr3t")  # Use environment variable
app.permanent_session_lifetime = timedelta(days=5)  # Session timeout

API_KEY = os.getenv("API_KEY", "AlzaSyWJ9k6bHLXTPasPZHDKQRzA7Z8O3bVT6Tx")

# Config for upload folder
app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "static", "uploads")
# Create upload folder if it doesn't exist
if not os.path.exists(app.config["UPLOAD_FOLDER"]):
    os.makedirs(app.config["UPLOAD_FOLDER"])

# Create users.txt if it doesn't exist
if not os.path.exists("users.txt"):
    with open("users.txt", "w") as f:
        # Create default admin user
        f.write(f"admin:{generate_password_hash('admin')}\n")
    logger.info("Created users.txt with default admin user")

# Create missing_reports.txt if it doesn't exist
if not os.path.exists("missing_reports.txt"):
    with open("missing_reports.txt", "w") as f:
        pass
    logger.info("Created empty missing_reports.txt")

# Create chat files if they don't exist
for chat_file in ["chat.txt", "report_chat.txt", "private_chat.txt"]:
    if not os.path.exists(chat_file):
        with open(chat_file, "w") as f:
            pass
        logger.info(f"Created empty {chat_file}")

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0  # Earth radius in kilometers
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (math.sin(delta_phi / 2.0)**2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0)**2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def get_directions(origin, destination):
    api_url = f"https://maps.gomaps.pro/maps/api/directions/json?destination={destination}&origin={origin}&key={API_KEY}"
    try:
        response = requests.get(api_url)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as error:
        print(f"Error calling API for directions: {error}")
        return None

def get_nearby_police_stations(lat, lng):
    api_url = f"https://maps.gomaps.pro/maps/api/place/nearbysearch/json?location={lat},{lng}&radius=5000&type=police&key={API_KEY}"
    try:
        response = requests.get(api_url)
        response.raise_for_status()
        try:
            return response.json()
        except ValueError as json_error:
            print(f"Error decoding JSON for nearby police stations: {json_error}")
            return None
    except requests.exceptions.RequestException as error:
        print(f"Error fetching nearby police stations: {error}")
        return None

def get_lat_lng(address):
    api_url = f"https://maps.gomaps.pro/maps/api/geocode/json?address={address}&key={API_KEY}"
    try:
        response = requests.get(api_url)
        response.raise_for_status()
        data = response.json()
        if data.get("results"):
            loc = data["results"][0]["geometry"]["location"]
            return loc["lat"], loc["lng"]
        else:
            return None, None
    except requests.exceptions.RequestException as error:
        print(f"Error geocoding address: {error}")
        return None, None

# --- CHAT HELPER FUNCTIONS ---
def load_chat_messages(chat_file):
    messages = []
    if os.path.exists(chat_file):
        with open(chat_file, "r") as f:
            for line in f:
                parts = line.strip().split("|", 2)
                if len(parts) == 2:  # Global chat: sender|message
                    messages.append({"sender": parts[0], "message": parts[1]})
                elif len(parts) == 3:  # Report-specific chat: report_index|sender|message
                    messages.append({
                        "report_index": int(parts[0]),
                        "sender": parts[1],
                        "message": parts[2]
                    })
    return messages

def save_chat_message(chat_file, *fields):
    with open(chat_file, "a") as f:
        f.write("|".join(str(field) for field in fields) + "\n")

# --- PRIVATE CHAT HELPER FUNCTIONS ---
def load_private_messages(chat_file, user1, user2):
    messages = []
    if os.path.exists(chat_file):
        with open(chat_file, "r") as f:
            for line in f:
                parts = line.strip().split("|", 2)
                if len(parts) == 3:
                    sender, receiver, message = parts
                    if ((sender == user1 and receiver == user2) or (sender == user2 and receiver == user1)):
                        messages.append({"sender": sender, "message": message})
    return messages

def save_private_message(chat_file, sender, receiver, message):
    with open(chat_file, "a") as f:
        f.write(f"{sender}|{receiver}|{message}\n")

# Add this function to handle password migration
def migrate_users_to_hashed_passwords():
    """Migrate users from plaintext to hashed passwords if needed"""
    if not os.path.exists("users.txt"):
        logger.info("No users.txt file exists, creating with default admin user")
        with open("users.txt", "w") as f:
            f.write(f"admin:{generate_password_hash('admin')}\n")
        return
        
    try:
        # Check if passwords are already hashed (sample check)
        needs_migration = False
        with open("users.txt", "r") as f:
            for line in f:
                if line.strip() and ":" in line and "$" not in line:  # Simple check for hash marker
                    needs_migration = True
                    break
        
        if needs_migration:
            logger.info("Migrating users from plaintext to hashed passwords")
            users = []
            with open("users.txt", "r") as f:
                for line in f:
                    if ":" in line:
                        parts = line.strip().split(":", 1)
                        if len(parts) == 2:
                            username, password = parts
                            hashed_password = generate_password_hash(password)
                            users.append((username, hashed_password))
            
            # Write back users with hashed passwords
            with open("users.txt", "w") as f:
                for username, hashed_password in users:
                    f.write(f"{username}:{hashed_password}\n")
            logger.info(f"Successfully migrated {len(users)} users to hashed passwords")
    except Exception as e:
        logger.error(f"Error during user migration: {str(e)}")

# Call the migration function during startup
migrate_users_to_hashed_passwords()

# Insert a context processor to inject the common style (using the CSS file from static/css)
@app.context_processor
def inject_common_style():
    return dict(common_style=url_for("static", filename="css/dashboard.css"),
                base_template="base.html",  # added base template for standard design
                home_url=url_for("dashboard"))  # updated to redirect to dashboard

# Landing page: Dashboard
@app.route("/", methods=["GET", "POST"])
def dashboard():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    
    # Get statistics for dashboard
    stats = {
        'total_reports': 0,
        'resolved_reports': 0,
        'police_stations': 0
    }
    
    recent_reports = []
    
    # Count reports
    if os.path.exists("missing_reports.txt"):
        with open("missing_reports.txt", "r") as f:
            reports = f.readlines()
            stats['total_reports'] = len(reports)
            
            # Get 3 most recent reports for display
            if reports:
                recent_count = min(3, len(reports))
                for i in range(recent_count):
                    parts = reports[i].strip().split("|")
                    if len(parts) >= 13:
                        recent_reports.append({
                            "id": parts[0],
                            "reporter": parts[1],
                            "address": parts[2],
                            "lat": parts[3],
                            "lng": parts[4],
                            "missing_name": parts[5],
                            "contact": parts[6],
                            "photo": parts[7],
                            "description": parts[8],
                            "age": parts[9],
                            "last_seen_date": parts[10],
                            "contact_email": parts[11],
                            "contact_name": parts[12]
                        })
    
    # Handle direction requests
    if request.method == "POST":
        origin = request.form.get("origin")
        destination = request.form.get("destination")
        directions = get_directions(origin, destination)
        if directions:
            try:
                leg = directions["routes"][0]["legs"][0]
                start_lat = leg["start_location"]["lat"]
                start_lng = leg["start_location"]["lng"]
                end_lat = leg["end_location"]["lat"]
                end_lng = leg["end_location"]["lng"]
                route_distance = leg["distance"]["text"]
                police_data = get_nearby_police_stations(start_lat, start_lng)
                stations = []
                if police_data and police_data.get("results"):
                    for station in police_data["results"]:
                        name = station.get("name")
                        loc = station.get("geometry", {}).get("location", {})
                        station_lat = loc.get("lat")
                        station_lng = loc.get("lng")
                        if station_lat is not None and station_lng is not None:
                            dist = haversine(start_lat, start_lng, station_lat, station_lng)
                            stations.append((name, dist))
                    stations.sort(key=lambda x: x[1])
                    stations = stations[:3]
                else:
                    stations = None
                result = {
                    "origin": {"lat": start_lat, "lng": start_lng},
                    "destination": {"lat": end_lat, "lng": end_lng},
                    "route_distance": route_distance,
                    "stations": stations
                }
                return render_template("dashboard.html", result=result, stats=stats, recent_reports=recent_reports, design_fixed=True)
            except (KeyError, IndexError) as e:
                error_msg = f"Error parsing API response: {e}"
                return render_template("dashboard.html", error_msg=error_msg, stats=stats, recent_reports=recent_reports, design_fixed=True)
        else:
            error_msg = "Failed to retrieve directions."
            return render_template("dashboard.html", error_msg=error_msg, stats=stats, recent_reports=recent_reports, design_fixed=True)
    return render_template("dashboard.html", result=None, stats=stats, recent_reports=recent_reports, design_fixed=True)

@app.route("/login", methods=["GET", "POST"])
def login():
    error_msg = None
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        if not username or not password:
            error_msg = "Username and password are required."
            return render_template("login.html", error_msg=error_msg)
        
        if os.path.exists("users.txt"):
            with open("users.txt", "r") as f:
                for line in f:
                    try:
                        if ":" not in line:
                            continue
                        
                        user, pwd_data = line.strip().split(":", 1)
                        if user != username:
                            continue
                            
                        # Try password hash verification first
                        if check_password_hash(pwd_data, password):
                            session.permanent = True
                            session["logged_in"] = True
                            session["username"] = username
                            # Special check for admin users
                            session["admin"] = (username == "admin" or username == "mihir")
                            logger.info(f"User {username} logged in successfully")
                            return redirect(url_for("dashboard"))
                        # Fallback for plaintext passwords during transition (should be temporary)
                        elif pwd_data == password:
                            # Migrate this user's password now
                            logger.info(f"Migrating password for user {username} during login")
                            migrate_single_user(username, password)
                            
                            session.permanent = True
                            session["logged_in"] = True
                            session["username"] = username
                            session["admin"] = (username == "admin" or username == "mihir")
                            return redirect(url_for("dashboard"))
                        else:
                            error_msg = "Invalid password for user."
                            break
                    except ValueError:
                        continue
                else:
                    error_msg = "Username not found."
        else:
            error_msg = "User database not found."
        
        logger.warning(f"Failed login attempt for username: {username}")
    
    return render_template("login.html", error_msg=error_msg)

# Add this helper function for single user migration
def migrate_single_user(username, plaintext_password):
    """Migrate a single user's password from plaintext to hashed"""
    try:
        users = []
        with open("users.txt", "r") as f:
            for line in f:
                if line.strip():
                    parts = line.strip().split(":", 1)
                    if len(parts) == 2:
                        user, pwd = parts
                        if user == username:
                            hashed_password = generate_password_hash(plaintext_password)
                            users.append((user, hashed_password))
                        else:
                            users.append((user, pwd))
        
        with open("users.txt", "w") as f:
            for user, pwd in users:
                f.write(f"{user}:{pwd}\n")
        logger.info(f"Successfully migrated password for user: {username}")
    except Exception as e:
        logger.error(f"Error migrating single user password: {str(e)}")

@app.route("/register", methods=["GET", "POST"])
def register():
    error_msg = None
    success_msg = None
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        if not username or not password:
            error_msg = "Username and password are required."
            return render_template("register.html", error_msg=error_msg)
            
        if len(password) < 6:
            error_msg = "Password must be at least 6 characters."
            return render_template("register.html", error_msg=error_msg)
        
        if os.path.exists("users.txt"):
            with open("users.txt", "r") as f:
                for line in f:
                    try:
                        user, _ = line.strip().split(":")
                        if user == username:
                            error_msg = "Username already exists. Please choose another."
                            return render_template("register.html", error_msg=error_msg)
                    except ValueError:
                        continue
                        
        password_hash = generate_password_hash(password)
        with open("users.txt", "a") as f:
            f.write(f"{username}:{password_hash}\n")
        
        logger.info(f"New user registered: {username}")
        success_msg = "Registration successful. You can now log in."
        return render_template("register.html", success_msg=success_msg)
    
    return render_template("register.html", error_msg=error_msg)

@app.route("/home")
def home():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    return render_template("home.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/reports")
def reports():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    
    reports_list = []
    if os.path.exists("missing_reports.txt"):
        with open("missing_reports.txt", "r") as f:
            for line in f:
                parts = line.strip().split("|")
                if len(parts) >= 13:
                    reports_list.append({
                        "id": parts[0],
                        "reporter": parts[1],
                        "address": parts[2],
                        "lat": parts[3],
                        "lng": parts[4],
                        "missing_name": parts[5],
                        "contact": parts[6],
                        "photo": parts[7],
                        "description": parts[8],
                        "age": parts[9],
                        "last_seen_date": parts[10],
                        "contact_email": parts[11],
                        "contact_name": parts[12]
                    })
    
    # Sort reports by date (newest first)
    reports_list.sort(key=lambda x: x["last_seen_date"], reverse=True)
    
    # Load chat messages for reports
    chat_messages = {}
    if os.path.exists("report_chat.txt"):
        with open("report_chat.txt", "r") as f:
            for line in f:
                parts = line.strip().split("|", 2)
                if len(parts) == 3:
                    report_id, sender, message = parts
                    if report_id not in chat_messages:
                        chat_messages[report_id] = []
                    chat_messages[report_id].append({
                        "sender": sender,
                        "message": message
                    })
    
    return render_template("reports.html", reports=reports_list, chat_messages=chat_messages)

@app.route("/submit_report", methods=["GET", "POST"])
def submit_report():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    error_msg = None
    if request.method == "POST":
        reporter = session.get("username")
        missing_name = request.form.get("missing_name")
        contact = request.form.get("contact")
        description = request.form.get("description")
        last_known_address = request.form.get("last_known")
        age = request.form.get("age")
        last_seen_date = request.form.get("last_seen_date")
        contact_email = request.form.get("contact_email")
        contact_name = request.form.get("contact_name")
        photo = request.files.get("photo")
        # Check that all required fields are provided
        if (reporter and missing_name and contact and description and last_known_address and photo
                and age and last_seen_date and contact_email and contact_name):
            filename = secure_filename(photo.filename)
            upload_folder = app.config["UPLOAD_FOLDER"]
            if not os.path.exists(upload_folder):
                os.makedirs(upload_folder)
            photo.save(os.path.join(upload_folder, filename))
            photo_url = url_for("static", filename="uploads/" + filename)
            lat, lng = get_lat_lng(last_known_address)
            if lat is None or lng is None:
                error_msg = "Could not determine coordinates for the provided address."
                return render_template("submit_report.html", error_msg=error_msg)
            report_id = str(uuid.uuid4())
            # New report format includes additional fields after description
            with open("missing_reports.txt", "a") as f:
                f.write(f"{report_id}|{reporter}|{last_known_address}|{lat}|{lng}|{missing_name}|{contact}|{photo_url}|{description}|{age}|{last_seen_date}|{contact_email}|{contact_name}\n")
            session["last_known_lat"] = lat
            session["last_known_lng"] = lng
            session["missing_name"] = missing_name
            return redirect(url_for("report_submitted"))
        else:
            error_msg = "All fields are required."
    return render_template("submit_report.html", error_msg=error_msg)

@app.route("/report_submitted")
def report_submitted():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    reporter = session.get("username")
    missing_name = session.get("missing_name", "the missing person")
    lat = session.get("last_known_lat")
    lng = session.get("last_known_lng")

    stations = []
    if lat is not None and lng is not None:
        police_data = get_nearby_police_stations(lat, lng)
        if police_data and police_data.get("results"):
            for station in police_data["results"]:
                name = station.get("name")
                loc = station.get("geometry", {}).get("location", {})
                station_lat = loc.get("lat")
                station_lng = loc.get("lng")
                if station_lat is not None and station_lng is not None:
                    dist = haversine(lat, lng, station_lat, station_lng)
                    stations.append((name, dist))
            stations.sort(key=lambda x: x[1])
            stations = stations[:3]
    return render_template("report_submitted.html", reporter=reporter, missing_name=missing_name, stations=stations)

@app.route("/delete_report/<report_id>")
def delete_report(report_id):
    if not session.get("admin"):
        return redirect(url_for("reports"))
    reports = []
    filename = "missing_reports.txt"
    if os.path.exists(filename):
        with open(filename, "r") as f:
            reports = f.readlines()
    new_reports = [line for line in reports if not line.startswith(report_id + "|")]
    with open(filename, "w") as f:
        f.writelines(new_reports)
    return redirect(url_for("reports"))

@app.route("/edit_report/<report_id>", methods=["GET", "POST"])
def edit_report(report_id):
    if not session.get("admin"):
        return redirect(url_for("reports"))
    filename = "missing_reports.txt"
    reports = []
    if os.path.exists(filename):
        with open(filename, "r") as f:
            reports = f.readlines()
    report_fields = None
    report_line_index = None
    for i, line in enumerate(reports):
        if line.startswith(report_id + "|"):
            report_fields = line.strip().split("|")
            report_line_index = i
            break
    if report_fields is None:
        return redirect(url_for("reports"))
    if request.method == "POST":
        reporter = request.form.get("reporter")
        last_known_address = request.form.get("last_known")
        missing_name = request.form.get("missing_name")
        contact = request.form.get("contact")
        photo_url = request.form.get("photo_url")
        description = request.form.get("description")
        age = request.form.get("age")
        last_seen_date = request.form.get("last_seen_date")
        contact_email = request.form.get("contact_email")
        contact_name = request.form.get("contact_name")
        lat, lng = get_lat_lng(last_known_address)
        if lat is None or lng is None:
            error_msg = "Could not determine coordinates for the provided address."
            return render_template("edit_report.html", error_msg=error_msg, report_id=report_id, report=report_fields)
        new_report = f"{report_id}|{reporter}|{last_known_address}|{lat}|{lng}|{missing_name}|{contact}|{photo_url}|{description}|{age}|{last_seen_date}|{contact_email}|{contact_name}\n"
        reports[report_line_index] = new_report
        with open(filename, "w") as f:
            f.writelines(reports)
        return redirect(url_for("reports"))
    return render_template("edit_report.html", report_id=report_id, report=report_fields)

@app.route("/global_chat", methods=["GET", "POST"])
def global_chat():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    error_msg = None
    chat_file = "chat.txt"
    if request.method == "POST":
        message = request.form.get("message")
        if message:
            sender = session["username"]
            save_chat_message(chat_file, sender, message)
        else:
            error_msg = "Message cannot be empty."
    messages = load_chat_messages(chat_file)
    return render_template("chat.html", messages=messages, error_msg=error_msg)

@app.route("/chat_for_report/<report_id>", methods=["POST"])
def chat_for_report(report_id):
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    message = request.form.get("message")
    if message:
        sender = session["username"]
        save_chat_message("report_chat.txt", report_id, sender, message)
    return redirect(url_for("reports"))

@app.route("/dashboard_messages")
def dashboard_messages():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    return render_template("dashboard_messages.html", my_reports=[])

@app.route("/contacts")
def contacts():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    current_user = session.get("username")
    users = []
    if os.path.exists("users.txt"):
        with open("users.txt", "r") as f:
            for line in f:
                parts = line.strip().split(":")
                if parts and parts[0] != current_user:
                    users.append(parts[0])
    return render_template("contacts.html", users=users)

@app.route("/private_chat/<recipient>", methods=["GET", "POST"])
def private_chat(recipient):
    if not session.get("logged_in") or not session.get("username"):
        return redirect(url_for("login"))
    current_user = session.get("username")
    error_msg = None
    chat_file = "private_chat.txt"

    if request.method == "POST":
        text = request.form.get("message")
        image = request.files.get("image")
        if not text and not image:
            error_msg = "Please enter a message or select an image."
        else:
            if image:
                filename = secure_filename(image.filename)
                upload_folder = app.config["UPLOAD_FOLDER"]
                if not os.path.exists(upload_folder):
                    os.makedirs(upload_folder)
                image.save(os.path.join(upload_folder, filename))
                image_url = url_for("static", filename="uploads/" + filename)
                message = "image:" + image_url
            else:
                message = text
            save_private_message(chat_file, current_user, recipient, message)

    messages = load_private_messages(chat_file, current_user, recipient)
    return render_template("private_chat.html", recipient=recipient, messages=messages, error_msg=error_msg)

@app.route("/search_reports", methods=["GET"])
def search_reports():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    query = request.args.get("q", "").strip().lower()
    results = []
    if os.path.exists("missing_reports.txt"):
        with open("missing_reports.txt", "r") as f:
            for line in f:
                parts = line.strip().split("|")
                if len(parts) >= 13:
                    report = {
                        "id": parts[0],
                        "reporter": parts[1],
                        "address": parts[2],
                        "lat": parts[3],
                        "lng": parts[4],
                        "missing_name": parts[5],
                        "contact": parts[6],
                        "photo": parts[7],
                        "description": parts[8],
                        "age": parts[9],
                        "last_seen_date": parts[10],
                        "contact_email": parts[11],
                        "contact_name": parts[12]
                    }
                    # Search in missing_name, address, and description fields
                    search_fields = f"{report['missing_name']} {report['address']} {report['description']}".lower()
                    if query in search_fields:
                        results.append(report)
    return render_template("search_reports.html", query=query, results=results)

# NEW: Route to display active Amber Alerts (missing person reports)
@app.route("/amber_alert", methods=["GET"])
def amber_alert():
    # Redirect to home page or dashboard instead of showing amber alert page
    return redirect(url_for("dashboard"))  # or redirect to "home" if you prefer

# Error handlers
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    logger.error(f"Internal server error: {str(e)}")
    return render_template('500.html'), 500

if __name__ == "__main__":
    app.run(debug=False, host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
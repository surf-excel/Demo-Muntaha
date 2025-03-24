import os
import requests
import math
import uuid
from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "s3cr3t"  # required for session management

API_KEY = "AlzaSyWJ9k6bHLXTPasPZHDKQRzA7Z8O3bVT6Tx"

# Config for upload folder
app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "static", "uploads")

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

# Landing page: Dashboard
@app.route("/", methods=["GET", "POST"])
def dashboard():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
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
                return render_template("dashboard.html", result=result)
            except (KeyError, IndexError) as e:
                error_msg = f"Error parsing API response: {e}"
                return render_template("dashboard.html", error_msg=error_msg)
        else:
            error_msg = "Failed to retrieve directions."
            return render_template("dashboard.html", error_msg=error_msg)
    return render_template("dashboard.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    error_msg = None
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if os.path.exists("users.txt"):
            with open("users.txt", "r") as f:
                for line in f:
                    try:
                        user, pwd = line.strip().split(":")
                        if user == username and pwd == password:
                            session["logged_in"] = True
                            session["username"] = username
                            session["admin"] = (username == "mihir" and password == "mihir")
                            return redirect(url_for("dashboard"))
                    except ValueError:
                        continue
        error_msg = "Invalid credentials. Please try again."
    return render_template("login.html", error_msg=error_msg)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    error_msg = None
    success_msg = None
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
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
        with open("users.txt", "a") as f:
            f.write(f"{username}:{password}\n")
        success_msg = "Registration successful. You can now log in."
        return render_template("register.html", success_msg=success_msg)
    return render_template("register.html", error_msg=error_msg)

@app.route("/reports")
def reports():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    reports_list = []
    if os.path.exists("missing_reports.txt"):
        with open("missing_reports.txt", "r") as f:
            for line in f:
                parts = line.strip().split("|")
                if len(parts) >= 9:
                    reports_list.append({
                        "id": parts[0],
                        "reporter": parts[1],
                        "address": parts[2],
                        "lat": parts[3],
                        "lng": parts[4],
                        "missing_name": parts[5],
                        "contact": parts[6],
                        "photo": parts[7],
                        "description": parts[8]
                    })
    return render_template("reports.html", reports=reports_list, chat_messages={})

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
        photo = request.files.get("photo")
        if (reporter and missing_name and contact and description and last_known_address and photo):
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
            with open("missing_reports.txt", "a") as f:
                f.write(f"{report_id}|{reporter}|{last_known_address}|{lat}|{lng}|{missing_name}|{contact}|{photo_url}|{description}\n")
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
        lat, lng = get_lat_lng(last_known_address)
        if lat is None or lng is None:
            error_msg = "Could not determine coordinates for the provided address."
            return render_template("edit_report.html", error_msg=error_msg, report_id=report_id, report=report_fields)
        new_report = f"{report_id}|{reporter}|{last_known_address}|{lat}|{lng}|{missing_name}|{contact}|{photo_url}|{description}\n"
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

if __name__ == "__main__":
    app.run(debug=True)
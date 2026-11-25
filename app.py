import os
import uuid
import io
import requests
from datetime import datetime, time, timezone, timedelta
from flask import Flask, render_template, request, redirect, url_for, send_file, flash, Response, make_response
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from PIL import Image, ImageDraw, ImageFont

# --- CLOUDINARY CONFIGURATION ---
import cloudinary
import cloudinary.uploader

cloudinary.config(
  cloud_name = "adqoktfc",
  api_key = "264368975959274",
  api_secret = "O8MLzxZOS4I4cIgt2KKRzN6f4l8"
)

app = Flask(__name__)
app.secret_key = "super_secret_bus_pass_key"

# --- IST TIMEZONE (UTC+5:30) ---
IST = timezone(timedelta(hours=5, minutes=30))

# --- ALLOWED CITIES ---
ALLOWED_CITIES = {
    "Nadiad", "Anand", "Bharuch",
    "Karjan", "Dabhoi", "Halol", "Godhra"
}

# --- SHIFT & TIME OF TRAVEL CONFIGURATION (IST) ---
SHIFT_WINDOWS = {
    "Morning Shift": {
        "Morning": {
            "range": (time(4, 30), time(8, 0)),
            "label": "4:30 AM – 8:00 AM"
        },
        "Afternoon": {
            "range": (time(13, 0), time(16, 0)),
            "label": "1:00 PM – 4:00 PM"
        }
    },
    "Admin Shift": {
        "Morning": {
            "range": (time(7, 0), time(9, 30)),
            "label": "7:00 AM – 9:30 AM"
        },
        "Afternoon": {
            "range": (time(16, 30), time(19, 30)),
            "label": "4:30 PM – 7:30 PM"
        }
    }
}

ALLOWED_TRAVEL_TIMES = {"Morning", "Afternoon"}

def get_ist_now():
    return datetime.now(IST)

def get_travel_date(record):
    return str(record.get('Date of Travel') or record.get('From Date') or record.get('To Date') or '').strip()

def is_within_allowed_window(shift_name, time_of_travel, now_ist):
    shift_cfg = SHIFT_WINDOWS.get(str(shift_name).strip())
    if not shift_cfg:
        return False, "No valid shift assigned"
    slot_cfg = shift_cfg.get(str(time_of_travel).strip())
    if not slot_cfg:
        return False, "No valid travel time assigned"
    start_t, end_t = slot_cfg["range"]
    current_t = now_ist.time()
    return (start_t <= current_t <= end_t), slot_cfg["label"]

def check_admin_auth():
    auth = request.authorization
    return auth and auth.username == 'admin' and auth.password == 'supersecret'

# --- GOOGLE SHEETS CONFIGURATION ---
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
try:
    CREDS = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", SCOPE)
    CLIENT = gspread.authorize(CREDS)
    SHEET = CLIENT.open("Temporary_Bus_Pass_DB").sheet1
except Exception as e:
    print(f"Google Sheets Connection Error: {e}")
    SHEET = None

# --- IMAGE COMPRESSION HELPER ---
def compress_image(upload_file, max_size=(1024, 1024), quality=70):
    try:
        img = Image.open(upload_file)
        img = img.convert("RGB")
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='JPEG', quality=quality)
        img_byte_arr.seek(0)
        return img_byte_arr
    except Exception as e:
        print(f"Compression failed: {e}")
        upload_file.seek(0)
        return upload_file

# --- PASS IMAGE GENERATOR HELPER ---
def generate_pass_image(record):
    template_path = "temporary-bus-pass.jpg"
    img = Image.open(template_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    
    try:
        font_25 = ImageFont.truetype("Roboto-Bold.ttf", 25)
        font_20 = ImageFont.truetype("Roboto-Bold.ttf", 20)
    except IOError:
        font_25 = ImageFont.load_default()
        font_20 = ImageFont.load_default()

    text_color = (0, 43, 91)
    
    # 1. Paste Passenger Photo
    photo_url = record.get('Passenger Photo URL')
    if photo_url:
        try:
            photo_response = requests.get(photo_url, stream=True)
            if photo_response.status_code == 200:
                passenger_img = Image.open(photo_response.raw).convert("RGB")
                passenger_img = passenger_img.resize((230, 286), Image.Resampling.LANCZOS)
                img.paste(passenger_img, (743, 270))
        except Exception as e:
            print(f"Error fetching/pasting passenger photo: {e}")

    # 2. Draw Text Values
    x_pos = 479
    draw.text((x_pos, 406), str(record.get('Name', '')), fill=text_color, font=font_25)
    draw.text((x_pos, 493), str(record.get('Enrollment ID', '')), fill=text_color, font=font_25)
    draw.text((x_pos, 582), str(record.get('Contact Number', '')), fill=text_color, font=font_25)
    draw.text((x_pos, 676), str(record.get('University Email', '')), fill=text_color, font=font_20)
    draw.text((x_pos, 763), str(record.get('Date', '')), fill=text_color, font=font_25)
    draw.text((x_pos, 874), str(record.get('Institute', '')), fill=text_color, font=font_25)
    draw.text((x_pos, 960), str(record.get('Department', '')), fill=text_color, font=font_25)
    draw.text((x_pos, 1052), get_travel_date(record), fill=text_color, font=font_25)
    draw.text((x_pos, 1229), str(record.get('From Destination', '')), fill=text_color, font=font_25)
    draw.text((x_pos, 1315), str(record.get('To Destination', '')), fill=text_color, font=font_25)
    draw.text((x_pos, 1392), str(record.get('Number of travels', '1')), fill=text_color, font=font_25)

    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='JPEG')
    img_byte_arr.seek(0)
    return img_byte_arr

def get_record_by_id(pass_id):
    cell = SHEET.find(str(pass_id))
    if not cell:
        return None
    row_data = SHEET.row_values(cell.row)
    headers = SHEET.row_values(1)
    return dict(zip(headers, row_data))

@app.route('/')
def index():
    search_query = request.args.get('search_email')
    user_passes = []
    now_ist = get_ist_now()
    today_ist = now_ist.strftime('%Y-%m-%d')
    
    if search_query and SHEET:
        all_records = SHEET.get_all_records()
        user_passes = [r for r in all_records if str(r.get('University Email')).strip().lower() == search_query.strip().lower()]
        
        for p in user_passes:
            travel_date = get_travel_date(p)
            p['display_travel_date'] = travel_date
            if p.get('Status') == 'Approved' and travel_date and travel_date < today_ist:
                p['Status'] = 'Expired'
            
            can_view, timing_label = is_within_allowed_window(
                p.get('Shift', ''),
                p.get('Time of Travel', ''),
                now_ist
            )
            p['can_view_now'] = (p.get('Status') == 'Approved' and can_view)
            p['shift_timing_label'] = timing_label
                
    return render_template('index.html', user_passes=user_passes, search_query=search_query, today_ist=today_ist)

@app.route('/submit', methods=['POST'])
def submit_form():
    if not SHEET:
        return "Database connection error.", 500
        
    name = request.form.get('name')
    enrollment = request.form.get('enrollment')
    contact = request.form.get('contact')
    email = request.form.get('email')
    date = get_ist_now().strftime('%Y-%m-%d')
    institute = request.form.get('institute')
    department = request.form.get('department')
    travel_date = request.form.get('travel_date')
    shift = request.form.get('shift')
    time_of_travel = request.form.get('time_of_travel')
    travels = "1"

    # Validate Shift & Time of Travel
    if shift not in SHIFT_WINDOWS:
        flash("Please select a valid Shift.")
        return redirect(url_for('index'))

    if time_of_travel not in ALLOWED_TRAVEL_TIMES:
        flash("Please select a valid Time of Travel.")
        return redirect(url_for('index'))

    # Resolve & Validate From / To Destinations
    from_dest_type = request.form.get('from_dest_type')
    to_dest_type = request.form.get('to_dest_type')
    from_city = request.form.get('from_city')
    to_city = request.form.get('to_city')

    if from_dest_type not in ("Parul University", "City") or to_dest_type not in ("Parul University", "City") or from_dest_type == to_dest_type:
        flash("Please select valid From and To destinations (Parul University and City).")
        return redirect(url_for('index'))

    if from_dest_type == "Parul University":
        from_dest = "Parul University"
    else:
        if from_city not in ALLOWED_CITIES:
            flash("Please select a valid From City.")
            return redirect(url_for('index'))
        from_dest = from_city

    if to_dest_type == "Parul University":
        to_dest = "Parul University"
    else:
        if to_city not in ALLOWED_CITIES:
            flash("Please select a valid To City.")
            return redirect(url_for('index'))
        to_dest = to_city
    
    screenshot_file = request.files.get('screenshot')
    photo_file = request.files.get('passenger_photo')
    
    screenshot_url = ""
    photo_url = ""
    
    if screenshot_file:
        try:
            compressed_screenshot = compress_image(screenshot_file)
            upload_result = cloudinary.uploader.upload(compressed_screenshot)
            screenshot_url = upload_result.get('secure_url')
        except Exception as e:
            flash(f"Payment Screenshot Upload Failed: {str(e)}")
            return redirect(url_for('index'))

    if photo_file:
        try:
            compressed_photo = compress_image(photo_file)
            upload_photo_result = cloudinary.uploader.upload(compressed_photo)
            photo_url = upload_photo_result.get('secure_url')
        except Exception as e:
            flash(f"Passenger Photo Upload Failed: {str(e)}")
            return redirect(url_for('index'))

    pass_id = str(uuid.uuid4())[:8]
    headers = SHEET.row_values(1)
    
    form_data_map = {
        "ID": pass_id,
        "Name": name,
        "Enrollment ID": enrollment,
        "Contact Number": contact,
        "University Email": email,
        "Date": date,
        "Institute": institute,
        "Department": department,
        "Date of Travel": travel_date,
        "From Date": travel_date,
        "From Destination": from_dest,
        "To Destination": to_dest,
        "Shift": shift,
        "Time of Travel": time_of_travel,
        "Number of travels": travels,
        "Passenger Photo URL": photo_url,
        "Screenshot URL": screenshot_url,
        "Status": "Pending"
    }
    
    row_data = [form_data_map.get(str(header).strip(), "") for header in headers]
    if not headers or len(headers) < 5:
        row_data = [pass_id, name, enrollment, contact, email, date, institute, department, travel_date, from_dest, to_dest, shift, time_of_travel, travels, photo_url, screenshot_url, "Pending"]

    SHEET.append_row(row_data)
    
    flash("Application submitted successfully!")
    return redirect(url_for('index'))

@app.route('/view_pass/<pass_id>')
def view_pass(pass_id):
    if not SHEET:
        return "Database error.", 500
        
    record = get_record_by_id(pass_id)
    if not record:
        return "Pass not found.", 404
        
    now_ist = get_ist_now()
    today_ist = now_ist.strftime('%Y-%m-%d')
    travel_date = get_travel_date(record)
    
    if record.get('Status') != 'Approved':
        return "Unauthorized. Pass is not approved.", 403
    if travel_date and travel_date < today_ist:
        return "Unauthorized. This pass has expired.", 403
        
    can_view, timing_label = is_within_allowed_window(
        record.get('Shift', ''),
        record.get('Time of Travel', ''),
        now_ist
    )
    if not can_view:
        return f"Unauthorized. Pass is only visible during your allotted timings ({timing_label}).", 403

    img_byte_arr = generate_pass_image(record)
    response = make_response(send_file(img_byte_arr, mimetype='image/jpeg', as_attachment=False))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    return response

@app.route('/admin')
def admin_dashboard():
    if not check_admin_auth():
        return Response('Access Denied', 401, {'WWW-Authenticate': 'Basic realm="Login Required"'})
    
    if not SHEET:
        return "Database connection error.", 500
        
    requests_list = SHEET.get_all_records()
    today_ist = get_ist_now().strftime('%Y-%m-%d')
    
    for req in requests_list:
        travel_date = get_travel_date(req)
        req['display_travel_date'] = travel_date
        if req.get('Status') == 'Approved' and travel_date and travel_date < today_ist:
            req['Status'] = 'Expired'
            
    return render_template('admin.html', requests=requests_list)

@app.route('/admin/action/<pass_id>/<action>')
def admin_action(pass_id, action):
    if not check_admin_auth():
        return Response('Access Denied', 401, {'WWW-Authenticate': 'Basic realm="Login Required"'})
    if not SHEET:
        return "Database error.", 500
        
    status_map = {"approve": "Approved", "reject": "Rejected"}
    new_status = status_map.get(action, "Pending")
    
    cell = SHEET.find(str(pass_id))
    if cell:
        headers = SHEET.row_values(1)
        status_col = headers.index("Status") + 1 if "Status" in headers else len(headers)
        SHEET.update_cell(cell.row, status_col, new_status)
        
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/download/<pass_id>')
def admin_download_pass(pass_id):
    if not check_admin_auth():
        return Response('Access Denied', 401, {'WWW-Authenticate': 'Basic realm="Login Required"'})
    if not SHEET:
        return "Database error.", 500
        
    record = get_record_by_id(pass_id)
    if not record:
        return "Pass not found.", 404

    img_byte_arr = generate_pass_image(record)
    return send_file(
        img_byte_arr,
        mimetype='image/jpeg',
        as_attachment=True,
        download_name=f"BusPass_{record.get('Enrollment ID')}.jpg"
    )

if __name__ == '__main__':
    app.run(debug=True)

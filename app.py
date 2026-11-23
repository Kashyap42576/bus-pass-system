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

# --- SHIFT TIMINGS CONFIGURATION ---
SHIFT_WINDOWS = {
    "Morning Shift": {
        "ranges": [(time(4, 30), time(8, 0)), (time(13, 0), time(16, 0))],
        "label": "4:30 AM to 8:00 AM & 1:00 PM to 4:00 PM"
    },
    "General Shift": {
        "ranges": [(time(7, 30), time(10, 0)), (time(16, 0), time(18, 30))],
        "label": "7:30 AM to 10:00 AM & 4:00 PM to 6:30 PM"
    },
    "Admin Shift": {
        "ranges": [(time(7, 0), time(9, 30)), (time(16, 30), time(19, 30))],
        "label": "7:00 AM to 9:30 AM & 4:30 PM to 7:30 PM"
    }
}

def get_ist_now():
    return datetime.now(IST)

def is_within_shift(shift_name, now_ist):
    config = SHIFT_WINDOWS.get(str(shift_name).strip())
    if not config:
        return False, "No valid shift assigned"
    current_t = now_ist.time()
    for start_t, end_t in config["ranges"]:
        if start_t <= current_t <= end_t:
            return True, config["label"]
    return False, config["label"]

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
    draw.text((x_pos, 1052), str(record.get('From Date', '')), fill=text_color, font=font_25)
    draw.text((x_pos, 1142), str(record.get('To Date', '')), fill=text_color, font=font_25)
    draw.text((x_pos, 1229), str(record.get('From Destination', '')), fill=text_color, font=font_25)
    draw.text((x_pos, 1315), str(record.get('To Destination', '')), fill=text_color, font=font_25)
    draw.text((x_pos, 1392), str(record.get('Number of travels', '')), fill=text_color, font=font_25)

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
            to_date = str(p.get('To Date', '')).strip()
            if p.get('Status') == 'Approved' and to_date and to_date < today_ist:
                p['Status'] = 'Expired'
            
            can_view, shift_label = is_within_shift(p.get('Shift', ''), now_ist)
            p['can_view_now'] = (p.get('Status') == 'Approved' and can_view)
            p['shift_timing_label'] = shift_label
                
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
    from_date = request.form.get('from_date')
    to_date = request.form.get('to_date')
    from_dest = request.form.get('from_dest')
    to_dest = request.form.get('to_dest')
    shift = request.form.get('shift')  
    travels = request.form.get('travels')

    if shift not in SHIFT_WINDOWS:
        flash("Please select a valid Shift.")
        return redirect(url_for('index'))
    
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
        "From Date": from_date,
        "To Date": to_date,
        "From Destination": from_dest,
        "To Destination": to_dest,
        "Shift": shift,  
        "Number of travels": travels,
        "Passenger Photo URL": photo_url,
        "Screenshot URL": screenshot_url,
        "Status": "Pending"
    }
    
    row_data = [form_data_map.get(str(header).strip(), "") for header in headers]
    if not headers or len(headers) < 5:
        row_data = [pass_id, name, enrollment, contact, email, date, institute, department, from_date, to_date, from_dest, to_dest, shift, travels, photo_url, screenshot_url, "Pending"]

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
    to_date = str(record.get('To Date', '')).strip()
    
    if record.get('Status') != 'Approved':
        return "Unauthorized. Pass is not approved.", 403
    if to_date and to_date < today_ist:
        return "Unauthorized. This pass has expired.", 403
        
    can_view, shift_label = is_within_shift(record.get('Shift', ''), now_ist)
    if not can_view:
        return f"Unauthorized. Pass is only visible during your shift timings ({shift_label}).", 403

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
        to_date = str(req.get('To Date', '')).strip()
        if req.get('Status') == 'Approved' and to_date and to_date < today_ist:
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

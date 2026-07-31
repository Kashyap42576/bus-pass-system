import os
import uuid
import io
import requests
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, send_file, flash, Response
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

# --- GOOGLE SHEETS CONFIGURATION ---
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
try:
    CREDS = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", SCOPE)
    CLIENT = gspread.authorize(CREDS)
    SHEET = CLIENT.open("Temporary_Bus_Pass_DB").sheet1
except Exception as e:
    print(f"Google Sheets Connection Error: {e}")
    SHEET = None

@app.route('/')
def index():
    search_query = request.args.get('search_email')
    user_passes = []
    
    if search_query and SHEET:
        all_records = SHEET.get_all_records()
        user_passes = [r for r in all_records if str(r.get('University Email')).strip().lower() == search_query.strip().lower()]
        
        today = datetime.now().strftime('%Y-%m-%d')
        for p in user_passes:
            if p.get('Status') == 'Approved' and p.get('To Date', '') < today:
                p['Status'] = 'Expired'
                
    return render_template('index.html', user_passes=user_passes, search_query=search_query)

@app.route('/submit', methods=['POST'])
def submit_form():
    if not SHEET:
        return "Database connection error.", 500
        
    name = request.form.get('name')
    enrollment = request.form.get('enrollment')
    contact = request.form.get('contact')
    email = request.form.get('email')
    date = request.form.get('date')
    institute = request.form.get('institute')
    department = request.form.get('department')
    from_date = request.form.get('from_date')
    to_date = request.form.get('to_date')
    from_dest = request.form.get('from_dest')
    to_dest = request.form.get('to_dest')
    shift = request.form.get('shift')  
    travels = request.form.get('travels')
    
    screenshot_file = request.files.get('screenshot')
    photo_file = request.files.get('passenger_photo')
    
    screenshot_url = ""
    photo_url = ""
    
    # 1. Upload Payment Screenshot to Cloudinary
    if screenshot_file:
        try:
            upload_result = cloudinary.uploader.upload(screenshot_file)
            screenshot_url = upload_result.get('secure_url')
        except Exception as e:
            flash(f"Payment Screenshot Upload Failed: {str(e)}")
            return redirect(url_for('index'))

    # 2. Upload Passenger Photo to Cloudinary
    if photo_file:
        try:
            upload_photo_result = cloudinary.uploader.upload(photo_file)
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

@app.route('/admin')
def admin_dashboard():
    auth = request.authorization
    if not auth or auth.username != 'admin' or auth.password != 'supersecret':
        return Response('Access Denied', 401, {'WWW-Authenticate': 'Basic realm="Login Required"'})
    
    if not SHEET:
        return "Database connection error.", 500
        
    requests_list = SHEET.get_all_records()
    
    today = datetime.now().strftime('%Y-%m-%d')
    for req in requests_list:
        if req.get('Status') == 'Approved' and req.get('To Date', '') < today:
            req['Status'] = 'Expired'
            
    return render_template('admin.html', requests=requests_list)

@app.route('/admin/action/<pass_id>/<action>')
def admin_action(pass_id, action):
    if not SHEET:
        return "Database error.", 500
        
    status_map = {"approve": "Approved", "reject": "Rejected"}
    new_status = status_map.get(action, "Pending")
    
    cell = SHEET.find(str(pass_id))
    if cell:
        headers = SHEET.row_values(1)
        if "Status" in headers:
            status_col = headers.index("Status") + 1
        else:
            status_col = len(headers)
            
        SHEET.update_cell(cell.row, status_col, new_status)
        
    return redirect(url_for('admin_dashboard'))

@app.route('/download/<pass_id>')
def download_pass(pass_id):
    if not SHEET:
        return "Database error.", 500
        
    cell = SHEET.find(str(pass_id))
    if not cell:
        return "Pass not found.", 404
        
    row_data = SHEET.row_values(cell.row)
    headers = SHEET.row_values(1)
    record = dict(zip(headers, row_data))
    
    today = datetime.now().strftime('%Y-%m-%d')
    if record.get('Status') != 'Approved':
        return "Unauthorized. Pass is not approved.", 403
    if record.get('To Date', '') < today:
        return "Unauthorized. This pass has expired.", 403

    template_path = "temporary-bus-pass.jpg"
    img = Image.open(template_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    
    # --- FONTS SETUP ---
    try:
        font_25 = ImageFont.truetype("Roboto-Bold.ttf", 25)
        font_20 = ImageFont.truetype("Roboto-Bold.ttf", 20)
    except IOError:
        font_25 = ImageFont.load_default()
        font_20 = ImageFont.load_default()

    text_color = (0, 43, 91) # Dark Navy Blue matching template header
    
    # --- 1. PASTE PASSENGER PHOTO ---
    # Position: X = 743, Y = 270 | Size: 230px (W) x 286px (H)
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

    # --- 2. DRAW TEXT VALUES ---
    # Shared X-Position = 479
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
    
    return send_file(img_byte_arr, mimetype='image/jpeg', as_attachment=True, download_name=f"BusPass_{record.get('Enrollment ID')}.jpg")

if __name__ == '__main__':
    app.run(debug=True)

import os
import uuid
import io
import base64
import requests
from flask import Flask, render_template, request, redirect, url_for, send_file, flash
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)
app.secret_key = "super_secret_bus_pass_key"

# --- IMGBB CONFIGURATION ---
IMGBB_API_KEY = "607e45d2db089e704822b7fa34ea37ad"  # <--- PASTE YOUR KEY HERE

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
    travels = request.form.get('travels')
    
    # Handle ImgBB Upload
    file = request.files.get('screenshot')
    screenshot_url = ""
    
    if file:
        image_data = base64.b64encode(file.read()).decode('utf-8')
        response = requests.post(
            "https://api.imgbb.com/1/upload",
            data={
                "key": IMGBB_API_KEY,
                "image": image_data
            }
        )
        if response.status_code == 200:
            screenshot_url = response.json()['data']['url']
        else:
            flash("Error uploading screenshot to cloud. Please try again.")
            return redirect(url_for('index'))

    pass_id = str(uuid.uuid4())[:8]
    
    SHEET.append_row([
        pass_id, name, enrollment, contact, email, date, 
        institute, department, from_date, to_date, 
        from_dest, to_dest, travels, screenshot_url, "Pending"
    ])
    
    flash("Application submitted successfully! Please check status using your email below.")
    return redirect(url_for('index'))

@app.route('/admin')
def admin_dashboard():
    if not SHEET:
        return "Database connection error.", 500
    requests_list = SHEET.get_all_records()
    return render_template('admin.html', requests=requests_list)

@app.route('/admin/action/<pass_id>/<action>')
def admin_action(pass_id, action):
    if not SHEET:
        return "Database error.", 500
        
    status_map = {"approve": "Approved", "reject": "Rejected"}
    new_status = status_map.get(action, "Pending")
    
    cell = SHEET.find(str(pass_id))
    if cell:
        SHEET.update_cell(cell.row, 15, new_status)
        
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
    
    if record.get('Status') != 'Approved':
        return "Unauthorized. This pass is not approved yet.", 403

    template_path = "temporary-bus-pass.jpg"
    if not os.path.exists(template_path):
        return "Template image background missing on server.", 500
        
    img = Image.open(template_path)
    draw = ImageDraw.Draw(img)
    
    try:
        font = ImageFont.truetype("arial.ttf", 26)
    except IOError:
        font = ImageFont.load_default()

    text_color = (0, 43, 91) 
    
    draw.text((500, 195), str(record.get('Name')), fill=text_color, font=font)
    draw.text((500, 255), str(record.get('Enrollment ID')), fill=text_color, font=font)
    draw.text((500, 315), str(record.get('Contact Number')), fill=text_color, font=font)
    draw.text((500, 375), str(record.get('University Email')), fill=text_color, font=font)
    draw.text((500, 435), str(record.get('Date')), fill=text_color, font=font)
    draw.text((500, 495), str(record.get('Institute')), fill=text_color, font=font)
    draw.text((500, 555), str(record.get('Department')), fill=text_color, font=font)
    draw.text((500, 615), str(record.get('From Date')), fill=text_color, font=font)
    draw.text((500, 675), str(record.get('To Date')), fill=text_color, font=font)
    draw.text((500, 735), str(record.get('From Destination')), fill=text_color, font=font)
    draw.text((500, 795), str(record.get('To Destination')), fill=text_color, font=font)
    draw.text((500, 855), str(record.get('Number of travels')), fill=text_color, font=font)

    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='JPEG')
    img_byte_arr.seek(0)
    
    return send_file(
        img_byte_arr, 
        mimetype='image/jpeg', 
        as_attachment=True, 
        download_name=f"BusPass_{record.get('Enrollment ID')}.jpg"
    )

if __name__ == '__main__':
    app.run(debug=True)
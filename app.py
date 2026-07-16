import os
import uuid
import io
import base64
import requests
from flask import Flask, render_template, request, redirect, url_for, send_file, flash, Response
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)
app.secret_key = "super_secret_bus_pass_key"

# --- IMGBB CONFIGURATION ---
IMGBB_API_KEY = "YOUR_IMGBB_API_KEY_HERE"  # <--- PASTE YOUR KEY HERE

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
    
    # Handle ImgBB Upload for Screenshots
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
    # --- SECURITY LOGIN CHECK ---
    # You can change 'admin' and 'supersecret' to your preferred login details
    auth = request.authorization
    if not auth or auth.username != 'admin' or auth.password != 'supersecret':
        return Response('Access Denied', 401, {'WWW-Authenticate': 'Basic realm="Login Required"'})
    # ----------------------------
    
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
        # Update column 15 (Status)
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
    
    # --- FONT & SIZING FIX ---
    try:
        font = ImageFont.truetype("Roboto-Bold.ttf", 32)
    except IOError:
        return "Font file missing! Please upload Roboto-Bold.ttf to your repository.", 500

    text_color = (0, 43, 91) 
    
    # --- LAYOUT ALIGNMENT FIX ---
    draw.text((490, 215), str(record.get('Name')), fill=text_color, font=font)
    draw.text((490, 282), str(record.get('Enrollment ID')), fill=text_color, font=font)
    draw.text((490, 349), str(record.get('Contact Number')), fill=text_color, font=font)
    draw.text((490, 416), str(record.get('University Email')), fill=text_color, font=font)
    draw.text((490, 483), str(record.get('Date')), fill=text_color, font=font)
    draw.text((490, 550), str(record.get('Institute')), fill=text_color, font=font)
    draw.text((490, 617), str(record.get('Department')), fill=text_color, font=font)
    draw.text((490, 684), str(record.get('From Date')), fill=text_color, font=font)
    draw.text((490, 751), str(record.get('To Date')), fill=text_color, font=font)
    draw.text((490, 818), str(record.get('From Destination')), fill=text_color, font=font)
    draw.text((490, 885), str(record.get('To Destination')), fill=text_color, font=font)
    draw.text((490, 952), str(record.get('Number of travels')), fill=text_color, font=font)

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

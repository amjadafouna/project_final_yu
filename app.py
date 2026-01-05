import os
import io
import json
import base64
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from flask_sqlalchemy import SQLAlchemy 
from sqlalchemy import Numeric
from PIL import Image
import numpy as np
import base64
from io import BytesIO
import face_recognition
from pyngrok import ngrok
import dlib
import cv2
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.secret_key = 'secretkey'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'users.db')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
cnn_face_detector = dlib.cnn_face_detection_model_v1("mmod_human_face_detector.dat")
db = SQLAlchemy(app)
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    dob = db.Column(db.String(30), nullable=False)
    phone = db.Column(db.String(10), unique=True, nullable=False)
    balance = db.Column(Numeric(12,2), nullable=True)
    face_encoding_json = db.Column(db.Text, nullable=True) 

    def get_encoding(self):
        if not self.face_encoding_json:
            return None
        return np.array(json.loads(self.face_encoding_json))

def save_base64_image(data_url, prefix='face'):
    header, encoded = data_url.split(',', 1)
    data = base64.b64decode(encoded)
    img = Image.open(io.BytesIO(data)).convert('RGB')
    filename = f"{prefix}_{int(datetime.utcnow().timestamp())}.jpg"
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    img.save(path, format='JPEG')
    return filename, path

def compare_encodings(enc1, enc2, tolerance=0.3):
    if enc1 is None or enc2 is None:
        return False
    dist = np.linalg.norm(enc1 - enc2)
    return (dist <= tolerance)

def get_user_by_phone(phone):
    return User.query.filter_by(phone=phone).first()


@app.route('/deposit', methods=['POST'])
def deposit():
    user_id = session.get('user_id')
    if not user_id:
        flash('الرجاء تسجيل الدخول أولًا.', 'warning')
        return redirect(url_for('login'))
    
    amount = float(request.form['amount'])
    user = User.query.get(session['user_id'])
    
    if user:
        user.balance = float(user.balance) + amount
        db.session.commit()
    
    return redirect('/bank')


@app.route('/transfer', methods=['POST'])
def transfer():
    user_id = session.get('user_id')
    if not user_id:
        flash('الرجاء تسجيل الدخول أولًا.', 'warning')
        return redirect(url_for('login'))
    phone = request.form['phone']
    amount = float(request.form['amount'])

    sender = User.query.get(session['user_id'])
    receiver = get_user_by_phone(phone)

    if sender and receiver and float(sender.balance) >= amount:
        sender.balance = float(sender.balance) - amount
        receiver.balance = float(receiver.balance) +  amount
        db.session.commit()

    return redirect('/bank')


@app.route('/pay', methods=['POST'])
def pay():
    user_id = session.get('user_id')
    if not user_id:
        flash('الرجاء تسجيل الدخول أولًا.', 'warning')
        return redirect(url_for('login'))
    
    amount = float(request.form['amount'])
    user = User.query.get(session['user_id'])

    if user and user.balance >= amount:
        user.balance = float(user.balance) - amount
        db.session.commit()

    return redirect('/bank')
     
@app.route('/', methods=['GET'])
def index():
    return redirect(url_for('login'))   
 
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        phone = request.form.get('phone', '').strip()
        face_data = request.form.get('face_image', None)
        user = User.query.filter_by(phone=phone).first()
        
        if not user:
            flash('.الرقم غير موجود', 'danger')
            return redirect(url_for('register'))
            
        if not face_data:
            flash('.الرجاء التقاط صورة الوجه', 'danger')
            return redirect(url_for('login'))
            
        try:
            
            image_data = base64.b64decode(face_data.split(',')[1])
            image = Image.open(BytesIO(image_data))
            image = np.array(image)
            
            rgb_image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
            detections = cnn_face_detector(rgb_image, 1)
            if len(detections) == 0:
                flash('No complete face detected or face is covered', 'danger')
                return redirect(url_for('login'))
                
            encs = face_recognition.face_encodings(image)
            
            if not encs:
                flash('.لم يتم العثور على وجه في الصورة. حاول مجدداً', 'danger')
                return redirect(url_for('login'))
                
            login_encoding = encs[0]
            registered_encoding = user.get_encoding()
            
            match = compare_encodings(registered_encoding, login_encoding, tolerance=0.6)
            
            if match:
                session['user_id'] = user.id
                return redirect(url_for('bank'))
            else:
                flash('خطأ: الوجه غير مطابق', 'danger')
                return redirect(url_for('login'))
                
        except Exception as e:
            print(e)
            flash('حدث خطأ أثناء التحقق', 'danger')
            return redirect(url_for('login'))
            
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        dob = request.form.get('dob', '').strip()
        phone = request.form.get('phone', '').strip()
        face_data = request.form.get('face_image', None)

        if not (name and dob and phone and face_data):
            flash('الرجاء ملء الحقول المطلوبة .', 'danger')
            return redirect(url_for('register'))
        if User.query.filter_by(phone=phone).first():
            flash('هذا الرقم مسجل مسبقًا. حاول تسجيل الدخول بدلاً من ذلك.', 'warning')
            return redirect(url_for('login'))
            
        try:
            filename, path = save_base64_image(face_data, prefix='reg')            
            image = face_recognition.load_image_file(path)
            encs = face_recognition.face_encodings(image)
            if not encs:
                flash('لم يتم العثور على وجه واضح في الصورة. حاول مجددًا.', 'danger')
                return redirect(url_for('register'))
            if len(encs)>1:
                flash('يوجد اكثر من وجه بالصورة', 'danger')
                return redirect(url_for('register'))    
                
            encoding = encs[0].tolist()
            user = User(name=name, dob=dob, phone=str(phone), balance=0 , face_encoding_json=json.dumps(encoding))
            db.session.add(user)
            db.session.commit()
            flash('تم إنشاء الحساب بنجاح. يمكنك الآن تسجيل الدخول.', 'success')
            return redirect(url_for('login'))
        except :
            flash('حدث خطأ: ', 'danger')
            return redirect(url_for('register'))
    return render_template('register.html')
@app.route('/bank')
def bank():
    user_id = session.get('user_id')
    if not user_id:
        flash('الرجاء تسجيل الدخول أولًا.', 'warning')
        return redirect(url_for('login'))
    user = User.query.get(user_id)
    if not user:
        flash('المستخدم غير موجود.', 'danger')
        return redirect(url_for('login'))
    return render_template('bank.html', user=user)

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('تم تسجيل الخروج.', 'info')
    return redirect(url_for('login'))

if __name__ == '__main__':
    with app.app_context():
      db.create_all()
    public_url = ngrok.connect(5000)
    print("Ngrok URL:", public_url)
    app.run(host='0.0.0.0', port=5000, debug=False)

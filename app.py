import os
import sqlite3
import base64
from flask import Flask, render_template, redirect, url_for, request, flash
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from google import genai
from google.genai import types

app = Flask(__name__)
app.config['SECRET_KEY'] = 'mahesh_premium_secret_key_123'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', max_http_buffer_size=10 * 1024 * 1024)

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

client = genai.Client()
DATABASE_FILE = 'chat_history.db'

class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT id, username FROM users WHERE id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return User(row[0], row[1])
    return None

# ================= DATABASE INITIALIZATION & SCHEMA =================
def init_db():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    # Users Table
    cursor.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, password TEXT NOT NULL)')
    
    # Public Channels Table
    cursor.execute('CREATE TABLE IF NOT EXISTS rooms (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE)')
    
    # Extended Messages Table (Supports Room Channels & Direct DMs)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            username TEXT NOT NULL, 
            text TEXT NOT NULL, 
            time TEXT NOT NULL,
            room_id INTEGER,
            receiver_id INTEGER,
            FOREIGN KEY(room_id) REFERENCES rooms(id),
            FOREIGN KEY(receiver_id) REFERENCES users(id)
        )
    ''')
    
    # Default Default Public Channels
    try:
        cursor.execute("INSERT INTO rooms (name) VALUES ('General')")
        cursor.execute("INSERT INTO rooms (name) VALUES ('AI-Talks')")
        conn.commit()
    except sqlite3.IntegrityError:
        pass 
    
    conn.close()

def save_message(username, text, time, room_id=None, receiver_id=None):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO messages (username, text, time, room_id, receiver_id) VALUES (?, ?, ?, ?, ?)', 
                   (username, text, time, room_id, receiver_id))
    conn.commit()
    conn.close()

init_db()

# ================= HTTP WEB ROUTES =================
@app.route('/')
@login_required
def index():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    # Fetch all public rooms
    cursor.execute('SELECT id, name FROM rooms')
    all_rooms = [{'id': r[0], 'name': r[1]} for r in cursor.fetchall()]
    
    # Fetch all registered users for DMs sidebar panel
    cursor.execute('SELECT id, username FROM users WHERE username != ?', (current_user.username,))
    all_users = [{'id': r[0], 'username': r[1]} for r in cursor.fetchall()]
    conn.close()
    
    return render_template('index.html', username=current_user.username, rooms=all_rooms, users=all_users)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username').strip()
        password = request.form.get('password')
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT id, username, password FROM users WHERE username = ?', (username,))
        row = cursor.fetchone()
        conn.close()
        if row and check_password_hash(row[2], password):
            login_user(User(row[0], row[1]))
            return redirect(url_for('index'))
        flash('Invalid username or password!')
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username').strip()
        password = request.form.get('password')
        if not username or not password:
            flash('Fields cannot be empty!')
            return redirect(url_for('signup'))
        try:
            conn = sqlite3.connect(DATABASE_FILE)
            cursor = conn.cursor()
            cursor.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, generate_password_hash(password, method='scrypt')))
            conn.commit()
            conn.close()
            flash('Account created successfully! Please login.')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username already exists!')
    return render_template('signup.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ================= REAL-TIME SOCKET WORKFLOWS =================
@socketio.on('join')
def on_join(data):
    username = data.get('username')
    room_type = data.get('room_type') 
    target_id = data.get('target_id') 
    
    # Generate unique signature room string
    if room_type == 'public':
        session_room = f"room_{target_id}"
    else:
        # DM communication room format: dm_minId_maxId
        session_room = f"dm_{min(int(current_user.id), int(target_id))}_{max(int(current_user.id), int(target_id))}"
    
    join_room(session_room)
    
    # Fetch targeted stream logs history
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    if room_type == 'public':
        cursor.execute('SELECT username, text, time FROM messages WHERE room_id = ? ORDER BY id ASC', (target_id,))
    else:
        # Direct Message explicit validation lookup selection filter
        cursor.execute('''
            SELECT username, text, time FROM messages 
            WHERE (username = ? AND receiver_id = ?) OR (username = ? AND receiver_id = ?) 
            ORDER BY id ASC
        ''', (current_user.username, target_id, data.get('target_username'), current_user.id))
        
    rows = cursor.fetchall()
    conn.close()
    
    history = [{'username': r[0], 'text': r[1], 'time': r[2]} for r in rows]
    emit('load_history', history)

@socketio.on('message')
def handle_message(data):
    username = data.get('username')
    message_text = data.get('text', '').strip()
    current_time = data.get('time', '')
    image_data = data.get('image', None)
    
    room_type = data.get('room_type', 'public')
    target_id = data.get('target_id')
    
    if room_type == 'public':
        session_room = f"room_{target_id}"
    else:
        session_room = f"dm_{min(int(current_user.id), int(target_id))}_{max(int(current_user.id), int(target_id))}"
    
    display_text = message_text
    if image_data:
        display_text = f'<div style="margin-bottom:8px;"><img src="{image_data}" style="max-width:200px; border-radius:8px; display:block;"/></div>' + message_text
    
    data['text'] = display_text
    
    # DB Sync
    if room_type == 'public':
        save_message(username, display_text, current_time, room_id=target_id)
    else:
        save_message(username, display_text, current_time, receiver_id=target_id)
        
    emit('message', data, to=session_room)
    
    # Multimodal Multimodal AI Pipeline Execution Engine
    if message_text.startswith('@ai'):
        user_query = message_text.replace('@ai', '').strip()
        emit('ai_typing', 'start', to=session_room)
        
        contents_payload = []
        if image_data:
            try:
                header, encoded = image_data.split(",", 1)
                mime_type = header.split(";")[0].split(":")[1]
                image_bytes = base64.b64decode(encoded)
                contents_payload.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type))
            except Exception as e:
                print(f"Image structural failure: {e}")
                
        contents_payload.append(user_query if user_query else "Describe this image context details.")
        
        try:
            response = client.models.generate_content(model='gemini-2.5-flash', contents=contents_payload)
            ai_response_text = response.text
        except Exception as e:
            ai_response_text = f"Sorry, I had an issue analyzing that request. Technical logs: {str(e)}"
            
        ai_data = {'username': '🤖 AI Assistant', 'text': ai_response_text, 'time': current_time}
        
        if room_type == 'public':
            save_message('🤖 AI Assistant', ai_response_text, current_time, room_id=target_id)
        else:
            save_message('🤖 AI Assistant', ai_response_text, current_time, receiver_id=target_id)
            
        emit('message', ai_data, to=session_room)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=True, allow_unsafe_werkzeug=True)
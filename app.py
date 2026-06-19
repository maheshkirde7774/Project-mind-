import os
import sqlite3
import base64
from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from google import genai
from google.genai import types

app = Flask(__name__)
app.config['SECRET_KEY'] = 'mahesh_premium_secret_key_123'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', max_http_buffer_size=25 * 1024 * 1024)

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

client = genai.Client()
DATABASE_FILE = 'chat_history.db'
session_user_map = {}

# Dynamic in-memory cluster to hold live pad states per room channel
shared_pads = {}

class User(UserMixin):
    def __init__(self, id, username, is_online=0):
        self.id = id
        self.username = username
        self.is_online = is_online

@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT id, username, is_online FROM users WHERE id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return User(row[0], row[1], row[2])
    return None

def init_db():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            username TEXT NOT NULL UNIQUE, 
            password TEXT NOT NULL,
            is_online INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('CREATE TABLE IF NOT EXISTS rooms (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE)')
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

def update_user_status(user_id, status_code):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET is_online = ? WHERE id = ?', (status_code, user_id))
    conn.commit()
    conn.close()

init_db()

# ================= WORKSPACE ANALYTICS API ENDPOINT =================
@app.route('/api/analytics')
@login_required
def get_analytics():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM messages")
    total_messages = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM messages WHERE username LIKE '%AI%'")
    ai_messages = cursor.fetchone()[0]
    
    human_messages = total_messages - ai_messages
    
    cursor.execute("""
        SELECT r.name, COUNT(m.id) FROM rooms r 
        LEFT JOIN messages m ON r.id = m.room_id 
        GROUP BY r.id
    """)
    channel_data = cursor.fetchall()
    channels = [row[0] for row in channel_data]
    channel_counts = [row[1] for row in channel_data]
    
    cursor.execute("SELECT COUNT(*) FROM messages WHERE receiver_id IS NOT NULL")
    private_dm_count = cursor.fetchone()[0]
    
    channels.append("Private DMs")
    channel_counts.append(private_dm_count)
    
    conn.close()
    
    return jsonify({
        'total_users': total_users,
        'total_messages': total_messages,
        'ai_queries': ai_messages,
        'human_messages': human_messages,
        'channels': channels,
        'channel_counts': channel_counts
    })

# ================= HTTP ROUTES =================
@app.route('/')
@login_required
def index():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT id, name FROM rooms')
    all_rooms = [{'id': r[0], 'name': r[1]} for r in cursor.fetchall()]
    cursor.execute('SELECT id, username, is_online FROM users WHERE username != ?', (current_user.username,))
    all_users = [{'id': r[0], 'username': r[1], 'is_online': r[2]} for r in cursor.fetchall()]
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
            cursor.execute('INSERT INTO users (username, password, is_online) VALUES (?, ?, 0)', (username, generate_password_hash(password, method='scrypt')))
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
    update_user_status(current_user.id, 0)
    logout_user()
    return redirect(url_for('login'))

# ================= REAL-TIME SOCKET WORKFLOWS =================
@socketio.on('connect')
def handle_socket_connect():
    if current_user.is_authenticated:
        session_user_map[request.sid] = current_user.id
        update_user_status(current_user.id, 1)
        emit('user_presence_change', {'user_id': current_user.id, 'is_online': 1}, broadcast=True)

@socketio.on('disconnect')
def handle_socket_disconnect():
    if request.sid in session_user_map:
        user_id = session_user_map[request.sid]
        del session_user_map[request.sid]
        if user_id not in session_user_map.values():
            update_user_status(user_id, 0)
            emit('user_presence_change', {'user_id': user_id, 'is_online': 0}, broadcast=True)

@socketio.on('join')
def on_join(data):
    room_type = data.get('room_type') 
    target_id = data.get('target_id') 
    if room_type == 'public':
        session_room = f"room_{target_id}"
    else:
        session_room = f"dm_{min(int(current_user.id), int(target_id))}_{max(int(current_user.id), int(target_id))}"
    join_room(session_room)
    
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    if room_type == 'public':
        cursor.execute('SELECT username, text, time FROM messages WHERE room_id = ? ORDER BY id ASC', (target_id,))
    else:
        cursor.execute('''
            SELECT username, text, time FROM messages 
            WHERE (username = ? AND receiver_id = ?) OR (username = ? AND receiver_id = ?) 
            ORDER BY id ASC
        ''', (current_user.username, target_id, data.get('target_username'), current_user.id))
    rows = cursor.fetchall()
    conn.close()
    
    history = [{'username': r[0], 'text': r[1], 'time': r[2]} for r in rows]
    emit('load_history', history)
    
    current_pad_text = shared_pads.get(session_room, "// Welcome to MIND AI Code Sandbox.\n// Start collaborating live here...")
    emit('sync_editor_pad', {'text': current_pad_text})

@socketio.on('code_type_sync')
def handle_code_sync(data):
    room_type = data.get('room_type')
    target_id = data.get('target_id')
    raw_text = data.get('text')
    
    if room_type == 'public':
        session_room = f"room_{target_id}"
    else:
        session_room = f"dm_{min(int(current_user.id), int(target_id))}_{max(int(current_user.id), int(target_id))}"
        
    shared_pads[session_room] = raw_text
    emit('code_type_sync', {'text': raw_text}, to=session_room, include_self=False)

@socketio.on('ai_optimize_code')
def handle_ai_code_optimization(data):
    room_type = data.get('room_type')
    target_id = data.get('target_id')
    code_content = data.get('text', '').strip()
    current_time = data.get('time', '')
    
    if room_type == 'public':
        session_room = f"room_{target_id}"
    else:
        session_room = f"dm_{min(int(current_user.id), int(target_id))}_{max(int(current_user.id), int(target_id))}"
        
    if not code_content:
        return
        
    emit('ai_typing', 'start', to=session_room)
    
    system_instruction = (
        "You are the MIND AI Code Optimization Expert. "
        "Analyze the provided code snippets or text framework. "
        "Identify runtime bugs, structural flaws, and performance bottlenecks. "
        "Strictly output your response using clear bold headings (###), highly detailed bullet points (•), and optimized code segments wrapped in syntax code blocks. "
        "Do not write monolithic prose or long paragraphs."
    )
    
    prompt = f"{system_instruction}\n\nReview and Optimize this Source Code:\n```\n{code_content}\n'''\n"
    
    try:
        response = client.models.generate_content(model='gemini-2.5-flash', contents=[prompt])
        ai_response_text = response.text.replace('\n', '<br>')
    except Exception as e:
        ai_response_text = f"**Code Optimizer Log Failure:**<br>• Engine processing anomaly.<br>• Technical info: {str(e)}"
        
    ai_data = {'username': '🤖 AI Code Optimizer', 'text': ai_response_text, 'time': current_time}
    
    if room_type == 'public':
        save_message('🤖 AI Code Optimizer', ai_response_text, current_time, room_id=target_id)
    else:
        save_message('🤖 AI Code Optimizer', ai_response_text, current_time, receiver_id=target_id)
        
    emit('message', ai_data, to=session_room)
    emit('refresh_analytics_trigger', {}, broadcast=True)

@socketio.on('message')
def handle_message(data):
    username = data.get('username')
    message_text = data.get('text', '').strip()
    current_time = data.get('time', '')
    file_data = data.get('file', None)
    file_name = data.get('file_name', '')
    file_type = data.get('file_type', '')
    
    room_type = data.get('room_type', 'public')
    target_id = data.get('target_id')
    
    if room_type == 'public':
        session_room = f"room_{target_id}"
    else:
        session_room = f"dm_{min(int(current_user.id), int(target_id))}_{max(int(current_user.id), int(target_id))}"
    
    display_text = message_text
    
    if file_data:
        if file_type.startswith('image/'):
            display_text = f'<div style="margin-bottom:8px;"><img src="{file_data}" style="max-width:200px; border-radius:8px; display:block;"/></div>' + message_text
        else:
            display_text = f'<div style="margin-bottom:8px; background:#2d3142; padding:10px; border-radius:6px; display:flex; align-items:center; gap:8px;"><i class="fa-solid fa-file-invoice" style="color:#38bdf8;"></i> <span style="font-size:13px; color:#e2e8f0;">{file_name}</span></div>' + message_text
    
    data['text'] = display_text
    
    if room_type == 'public':
        save_message(username, display_text, current_time, room_id=target_id)
    else:
        save_message(username, display_text, current_time, receiver_id=target_id)
        
    emit('message', data, to=session_room)
    emit('refresh_analytics_trigger', {}, broadcast=True)
    
    if message_text.startswith('@ai'):
        user_query = message_text.replace('@ai', '').strip()
        emit('ai_typing', 'start', to=session_room)
        
        contents_payload = []
        doc_text_extraction = ""
        
        if file_data:
            try:
                header, encoded = file_data.split(",", 1)
                mime_type = header.split(";")[0].split(":")[1]
                file_bytes = base64.b64decode(encoded)
                
                if "wordprocessingml" in mime_type or file_name.endswith('.docx'):
                    doc_text_extraction = f"\n[Attached Document Content Name: {file_name}]\n This is raw text from the file:\n" + file_bytes.decode('utf-8', errors='ignore')
                elif "plain" in mime_type or file_name.endswith('.txt'):
                    doc_text_extraction = f"\n[Attached Text Content Name: {file_name}]\n" + file_bytes.decode('utf-8', errors='ignore')
                else:
                    contents_payload.append(types.Part.from_bytes(data=file_bytes, mime_type=mime_type))
            except Exception as e:
                print(f"File extraction structural anomaly: {e}")
        
        system_instruction = (
            "You are MIND AI Workspace Assistant. STRICT COMPLIANCE RULES:\n"
            "1. NEVER output long, dense paragraphs. Users hate it.\n"
            "2. Always structure the text beautifully using clear bold Headings (###), concise Bullet points (•), or numbered arrays.\n"
            "3. If providing source segments or program logs, encapsulate them in clean Code blocks.\n"
            "4. Maintain maximum scannability and professional brevity."
        )
        
        base_prompt = user_query if user_query else "Analyze the attached file content carefully and summarize it."
        final_prompt = f"{system_instruction}\n\nUser Prompt: {base_prompt} {doc_text_extraction}"
        contents_payload.append(final_prompt)
        
        try:
            response = client.models.generate_content(model='gemini-2.5-flash', contents=contents_payload)
            ai_response_text = response.text.replace('\n', '<br>')
        except Exception as e:
            ai_response_text = f"**Error Context Execution Block:**<br>• Unsupported or heavily encrypted content matrix.<br>• Logs: {str(e)}"
            
        ai_data = {'username': '🤖 AI Assistant', 'text': ai_response_text, 'time': current_time}
        
        if room_type == 'public':
            save_message('🤖 AI Assistant', ai_response_text, current_time, room_id=target_id)
        else:
            save_message('🤖 AI Assistant', ai_response_text, current_time, receiver_id=target_id)
            
        emit('message', ai_data, to=session_room)
        emit('refresh_analytics_trigger', {}, broadcast=True)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=True, allow_unsafe_werkzeug=True)
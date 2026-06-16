import os
import sqlite3
import base64
from flask import Flask, render_template, redirect, url_for, request, flash
from flask_socketio import SocketIO, emit
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from google import genai
from google.genai import types  # <--- Sirf ye ek line rakhein types ke liye

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

def init_db():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, text TEXT NOT NULL, time TEXT NOT NULL)')
    cursor.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, password TEXT NOT NULL)')
    conn.commit()
    conn.close()

def save_message(username, text, time):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO messages (username, text, time) VALUES (?, ?, ?)', (username, text, time))
    conn.commit()
    conn.close()

def get_chat_history():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT username, text, time FROM messages ORDER BY id ASC')
    rows = cursor.fetchall()
    conn.close()
    return [{'username': r[0], 'text': r[1], 'time': r[2]} for r in rows]

init_db()

@app.route('/')
@login_required
def index():
    return render_template('index.html', username=current_user.username)

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

@socketio.on('connect')
def handle_connect():
    emit('load_history', get_chat_history())

@socketio.on('message')
def handle_message(data):
    username = data.get('username', 'Anonymous')
    message_text = data.get('text', '').strip()
    current_time = data.get('time', '')
    image_data = data.get('image', None)

    display_text = message_text
    if image_data:
        display_text = f'<div style="margin-bottom:8px;"><img src="{image_data}" style="max-width:200px; border-radius:8px; display:block;"/></div>' + message_text
    
    data['text'] = display_text
    save_message(username, display_text, current_time)
    emit('message', data, broadcast=True)
    
    if message_text.startswith('@ai'):
        user_query = message_text.replace('@ai', '').strip()
        emit('ai_typing', 'start', broadcast=True)
        
        contents_payload = []
        
        # Sahi and updated Multi-modal syntax for google-genai SDK
        if image_data:
            try:
                header, encoded = image_data.split(",", 1)
                mime_type = header.split(";")[0].split(":")[1]
                image_bytes = base64.b64decode(encoded)
                
                # Naye SDK ka standard object creator helper bina extra imports ke
                from google.genai import types
                contents_payload.append(
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
                )
            except Exception as e:
                print(f"Image processing failed: {e}")
                
        # Context handling
        if user_query.lower() == 'summarize' and not image_data:
            chat_context = "".join([f"{m['username']}: {m['text']}\n" for m in get_chat_history() if m['username'] != '🤖 AI Assistant'])
            contents_payload.append(f"Analyze this conversation log and give a bullet-point summary:\n\n{chat_context}")
        else:
            contents_payload.append(user_query if user_query else "Describe this image context details.")

        try:
            # Calling standard flash model with explicit content list
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=contents_payload
            )
            ai_response_text = response.text
        except Exception as e:
            ai_response_text = f"Sorry, I had an issue analyzing that request. Technical logs: {str(e)}"

        ai_data = {'username': '🤖 AI Assistant', 'text': ai_response_text, 'time': current_time}
        save_message(ai_data['username'], ai_data['text'], ai_data['time'])
        emit('message', ai_data, broadcast=True)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    # debug=True kijiye taaki error screen par aaye
    socketio.run(app, host='0.0.0.0', port=port, debug=True, allow_unsafe_werkzeug=True)
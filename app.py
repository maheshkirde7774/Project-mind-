import os
import sqlite3
from flask import Flask, render_template
from flask_socketio import SocketIO, emit
from google import genai

app = Flask(__name__)
app.config['SECRET_KEY'] = 'my_local_secret_key_123'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Initialize Gemini Client
client = genai.Client()

DATABASE_FILE = 'chat_history.db'

def init_db():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            text TEXT NOT NULL,
            time TEXT NOT NULL
        )
    ''')
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
    
    history = []
    for row in rows:
        history.append({'username': row[0], 'text': row[1], 'time': row[2]})
    return history

init_db()

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    history = get_chat_history()
    emit('load_history', history)

@socketio.on('message')
def handle_message(data):
    username = data.get('username', 'Anonymous')
    message_text = data.get('text', '').strip()
    current_time = data.get('time', '')

    save_message(username, message_text, current_time)
    emit('message', data, broadcast=True)
    
    if message_text.startswith('@ai'):
        user_query = message_text.replace('@ai', '').strip()
        
        # Trigger real-time Typing Indicator to everyone in room
        emit('ai_typing', 'start', broadcast=True)
        
        if user_query.lower() == 'summarize':
            full_history = get_chat_history()
            chat_context = ""
            for msg in full_history:
                if msg['username'] != '🤖 AI Assistant':
                    chat_context += f"{msg['username']}: {msg['text']}\n"
            
            system_prompt = f"Analyze the following chat conversation log and provide a very concise, professional summary in bullet points:\n\n{chat_context}"
            
            try:
                response = client.models.generate_content(model='gemini-2.5-flash', contents=system_prompt)
                ai_response_text = "📋 **Chat Room Summary:**\n" + response.text
            except Exception as e:
                ai_response_text = "Sorry, I couldn't generate the summary of the logs."
        
        else:
            if user_query:
                try:
                    response = client.models.generate_content(model='gemini-2.5-flash', contents=user_query)
                    ai_response_text = response.text
                except Exception as e:
                    ai_response_text = "Sorry, I am facing an issue connecting to my Gemini brain right now."
            else:
                emit('ai_typing', 'stop', broadcast=True)
                return

        ai_data = {'username': '🤖 AI Assistant', 'text': ai_response_text, 'time': current_time}
        
        save_message(ai_data['username'], ai_data['text'], ai_data['time'])
        # Broadcast message hides typing bubble automatically on user view
        emit('message', ai_data, broadcast=True)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
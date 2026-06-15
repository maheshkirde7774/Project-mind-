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
        history.append({
            'username': row[0],
            'text': row[1],
            'time': row[2]
        })
    return history

init_db()

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    print("Client connected. Loading full database history...")
    history = get_chat_history()
    emit('load_history', history)

@socketio.on('message')
def handle_message(data):
    print(f"Server log - Received: {data}")
    
    username = data.get('username', 'Anonymous')
    message_text = data.get('text', '').strip()
    current_time = data.get('time', '')

    # Save user's chat message to DB and broadcast to view
    save_message(username, message_text, current_time)
    emit('message', data, broadcast=True)
    
    # Check for AI core commands
    if message_text.startswith('@ai'):
        user_query = message_text.replace('@ai', '').strip()
        
        # 🚀 NEW SUB-FEATURE: Chat Log Summarizer
        if user_query.lower() == 'summarize':
            # 1. Fetch entire logs from database
            full_history = get_chat_history()
            
            # 2. Format history records into a readable string context for LLM
            chat_context = ""
            for msg in full_history:
                # We skip previous AI summary messages to avoid recursive loops
                if msg['username'] != '🤖 AI Assistant':
                    chat_context += f"{msg['username']}: {msg['text']}\n"
            
            # 3. Formulate the summarization prompt
            system_prompt = f"Analyze the following chat conversation log and provide a very concise, professional summary in bullet points:\n\n{chat_context}"
            
            try:
                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=system_prompt,
                )
                ai_response_text = "📋 **Chat Room Summary:**\n" + response.text
            except Exception as e:
                print(f"Gemini Summarize Error: {e}")
                ai_response_text = "Sorry, I couldn't generate the summary of the logs at the moment."
        
        # Standard general queries (like weather or greetings)
        else:
            if user_query:
                try:
                    response = client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=user_query,
                    )
                    ai_response_text = response.text
                except Exception as e:
                    print(f"Gemini API Error: {e}")
                    ai_response_text = "Sorry, I am facing an issue connecting to my Gemini brain right now."
            else:
                return

        # Prepare AI transmission packet
        ai_data = {
            'username': '🤖 AI Assistant',
            'text': ai_response_text,
            'time': current_time
        }
        
        # Save AI's response to database and broadcast to everyone
        save_message(ai_data['username'], ai_data['text'], ai_data['time'])
        emit('message', ai_data, broadcast=True)

if __name__ == '__main__':
    # Production servers automatically set the PORT variable
    port = int(os.environ.get("PORT", 5000))
    # Using allow_unsafe_werkzeug=True for production environments where eventlet isn't explicitly configured
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
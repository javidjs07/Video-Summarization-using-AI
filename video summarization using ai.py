import streamlit as st
from werkzeug.utils import secure_filename
import os
import hashlib
import sqlite3
from pydub import AudioSegment
import speech_recognition as sr
from concurrent.futures import ThreadPoolExecutor
from pytube import YouTube
import requests
import tempfile

# Ensure ffmpeg is correctly set up
AudioSegment.converter = "ffmpeg"  # Set this to the path of ffmpeg if not in PATH

# Database connection
conn = sqlite3.connect('data.db', check_same_thread=False)
c = conn.cursor()

# Create tables
c.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT, password TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS summaries (id INTEGER PRIMARY KEY, username TEXT, summary TEXT)''')
conn.commit()

# Functions to handle database operations
def create_user(username, password):
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    c.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, password_hash))
    conn.commit()

def authenticate_user(username, password):
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    c.execute('SELECT * FROM users WHERE username = ? AND password = ?', (username, password_hash))
    return c.fetchone()

def save_summary(username, summary):
    c.execute('INSERT INTO summaries (username, summary) VALUES (?, ?)', (username, summary))
    conn.commit()

def get_summaries(username):
    c.execute('SELECT summary FROM summaries WHERE username = ?', (username,))
    return c.fetchall()

# Functions for video processing
def extract_audio(video_path, duration=60000):
    try:
        audio_path = 'audio.wav'
        video = AudioSegment.from_file(video_path)
        audio = video[:duration]  # Limit to first `duration` milliseconds
        audio.export(audio_path, format='wav')
        return audio_path
    except Exception as e:
        st.error(f"Error extracting audio: {e}")
        return None

def transcribe_audio_chunk(chunk_path):
    recognizer = sr.Recognizer()
    try:
        with sr.AudioFile(chunk_path) as audio_file:
            audio = recognizer.record(audio_file)
            return recognizer.recognize_google(audio)  # Using Google's faster API
    except sr.UnknownValueError:
        return "Could not understand audio"
    except sr.RequestError as e:
        return f"Google API error; {e}"

def transcribe_audio_parallel(audio_path, num_workers=8):
    audio = AudioSegment.from_wav(audio_path)
    chunk_size = len(audio) // num_workers
    chunks = [audio[i*chunk_size:(i+1)*chunk_size] for i in range(num_workers)]
    
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(transcribe_audio_chunk, chunk.export(format='wav')) for chunk in chunks]
    
    results = [f.result() for f in futures]
    return " ".join(results)

def summarize_text(text):
    sentences = text.split('. ')
    return '. '.join(sentences[:2])

def download_youtube_video(url, output_path='downloads'):
    try:
        yt = YouTube(url)
        video = yt.streams.filter(only_audio=True).first()
        out_file = video.download(output_path=output_path)
        base, ext = os.path.splitext(out_file)
        new_file = base + '.mp4'
        os.rename(out_file, new_file)
        return new_file
    except Exception as e:
        st.error(f"Error downloading video: {e}")
        return None

# Streamlit app
def main():
    st.set_page_config(page_title="Video Summary App", layout="wide")
    
    # Debugging print
    st.write("Streamlit app loaded")

    # Login/Signup
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
    
    if st.session_state.logged_in:
        st.sidebar.write(f"Welcome, {st.session_state.username}")
        if st.sidebar.button("Logout"):
            st.session_state.logged_in = False
            st.experimental_rerun()
        
        st.title("Video Summary App")

        st.sidebar.header("Upload Video or Enter YouTube Link")
        uploaded_file = st.sidebar.file_uploader("Upload a video", type=["mp4"])
        youtube_url = st.sidebar.text_input("YouTube URL")

        if uploaded_file is not None or youtube_url:
            st.sidebar.write("Processing...")
            progress_bar = st.sidebar.progress(0)

            if uploaded_file:
                video_path = os.path.join("uploads", secure_filename(uploaded_file.name))
                os.makedirs("uploads", exist_ok=True)
                os.makedirs("audio_chunks", exist_ok=True)
                with open(video_path, "wb") as f:
                    f.write(uploaded_file.getvalue())
            elif youtube_url:
                video_path = download_youtube_video(youtube_url)
                if video_path is None:
                    return

            st.video(open(video_path, 'rb').read())

            progress_bar.progress(25)
            st.write("Extracting audio...")
            audio_path = extract_audio(video_path)
            
            if audio_path is None:
                return

            progress_bar.progress(50)
            st.write("Transcribing audio...")

            text = transcribe_audio_parallel(audio_path)

            progress_bar.progress(75)
            st.write("Summarizing text...")
            summary = summarize_text(text)

            progress_bar.progress(100)
            st.sidebar.success("Processing complete!")

            st.subheader("Summary:")
            st.write(summary)

            if st.button("Save Summary"):
                save_summary(st.session_state.username, summary)
                st.success("Summary saved successfully!")

        st.subheader("Previous Summaries:")
        summaries = get_summaries(st.session_state.username)
        for s in summaries:
            st.write(s[0])
    
    else:
        option = st.sidebar.selectbox("Login / Signup", ["Login", "Signup"])

        username = st.sidebar.text_input("Username")
        password = st.sidebar.text_input("Password", type="password")

        if option == "Signup":
            if st.sidebar.button("Signup"):
                create_user(username, password)
                st.sidebar.success("User created successfully!")
        elif option == "Login":
            if st.sidebar.button("Login"):
                user = authenticate_user(username, password)
                if user:
                    st.session_state.logged_in = True
                    st.session_state.username = username
                    st.experimental_rerun()
                else:
                    st.sidebar.error("Invalid username or password")

if __name__ == "__main__":
    main()

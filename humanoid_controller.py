import os
import sys
import queue

# Suppress pygame and audio backend prompts
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import time
import threading
import math
import subprocess
import pygame
import serial

# Silence OpenCV internal logs (kept for teammate reference)
import cv2
cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_FATAL)

import ollama
import speech_recognition as sr
from coppeliasim_zmqremoteapi_client import RemoteAPIClient
from ultron_eyes import UltronFace

# ==========================================
# CONFIGURATION FLAGS
# ==========================================
HARDWARE_SERVOS_CONNECTED = True  # True for simultaneous physical Arduino control

# Initialize Serial connection to Arduino Uno (Make sure blue USB cable is plugged in)
arduino = None
if HARDWARE_SERVOS_CONNECTED:
    try:
        arduino = serial.Serial('/dev/ttyACM0', 9600, timeout=1)
        time.sleep(2)  # Allow Arduino reset time
        print("[Hardware] Arduino Uno connected successfully on /dev/ttyACM0")
    except Exception as e:
        print(f"[Hardware Error] Could not connect to Arduino: {e}")
        HARDWARE_SERVOS_CONNECTED = False

# Initialize Pygame mixer for MP3 playback
pygame.mixer.init()

print('Connecting to CoppeliaSim on Laptop (IP: 10.15.182.176)...')
client = RemoteAPIClient(host='192.168.1.5', port=23000)
sim = client.require('sim')

joint_names = [
    'left_hip', 'left_knee', 'right_hip', 'right_knee',
    'left_shoulder', 'left_elbow', 'right_shoulder', 'right_elbow',
    'neck_joint',
]

joint_handles = []
print('Fetching joint handles from simulation...')
for name in joint_names:
    handle = sim.getObject(f'./{name}')
    joint_handles.append(handle)

robot_state = 'STAND'
is_speaking = False
zmq_lock = threading.Lock()
base_pose = [0.0] * 9  
head_pan_angle = 0.0   

# Unified Command Queue for both Keyboard and Microphone
command_queue = queue.Queue()

print('\n[System] Booting Hardware Visuals & MPU6050 Balance Loop...')
face = UltronFace()
recognizer = sr.Recognizer()

def set_robot_pose(pose_angles):
    global base_pose
    base_pose = list(pose_angles)

poses = {
    'STAND': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    'SIT': [1.2, -1.2, 1.2, -1.2, 0.3, 1.57, 0.3, 1.57, 0.0],
    'SEE_LEFT': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.8],
    'SEE_RIGHT': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, -0.8],
}

def send_to_arduino_simultaneous(pose_array):
    """Sends joint angles simultaneously to physical Arduino servos over Serial"""
    if not HARDWARE_SERVOS_CONNECTED or arduino is None:
        return
    try:
        deg_vals = []
        for i in range(min(5, len(pose_array))):
            deg = int(math.degrees(pose_array[i]) + 90)
            deg = max(0, min(180, deg))  # Clamp bounds between 0 and 180
            deg_vals.append(str(deg))
        
        payload = "<" + ",".join(deg_vals) + ">\n"
        arduino.write(payload.encode('utf-8'))
    except Exception as e:
        print(f"[Serial Error] Failed to send data to Arduino: {e}")

def speak_villain_direct(text):
    global is_speaking
    try:
        is_speaking = True
        cmd = ["espeak-ng", "-v", "hi+m3", "-s", "110", text]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        is_speaking = False
    except Exception as e:
        print(f"[Audio Error] Direct speech failed: {e}")
        is_speaking = False

def play_quote_mp3():
    global is_speaking
    try:
        is_speaking = True
        mp3_path = "ultron_quote.mp3"
        if os.path.exists(mp3_path):
            pygame.mixer.music.load(mp3_path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)
        else:
            speak_villain_direct("दोस्त और दुश्मन दोनों को बनाओ धनवान, तभी तो होगी असली पहचान!")
        is_speaking = False
    except Exception as e:
        print(f"[Audio Error] MP3 playback failed: {e}")
        is_speaking = False

def camera_head_tracking_loop():
    """[NOTE FOR TEAMMATE]: Camera handling module."""
    pass

def hardware_and_balance_loop():
    global robot_state, is_speaking, base_pose, head_pan_angle
    
    KP_PITCH_HIP = 0.15      
    KP_PITCH_KNEE = -0.075   
    KP_ROLL_SHOULDER = 0.20  
    KP_ROLL_HIP = 0.10       

    while True:
        face.tick(force_talk=is_speaking)
        
        ax, ay, az = face.read_accel()
        pitch_error = ax - face.base_x  
        roll_error = ay - face.base_y   

        if robot_state != 'RECOVERY':
            off_hip_p = pitch_error * KP_PITCH_HIP
            off_knee_p = pitch_error * KP_PITCH_KNEE
            off_shoulder_r = roll_error * KP_ROLL_SHOULDER
            off_hip_r = roll_error * KP_ROLL_HIP

            final_pose = list(base_pose)
            final_pose[0] += off_hip_p   
            final_pose[2] += off_hip_p   
            final_pose[1] += off_knee_p  
            final_pose[3] += off_knee_p  
            final_pose[0] += off_hip_r    
            final_pose[2] -= off_hip_r    
            final_pose[4] += off_shoulder_r 
            final_pose[6] += off_shoulder_r 

            if robot_state == 'STAND':
                final_pose[8] = head_pan_angle

            # 1. Update CoppeliaSim (Virtual Simulation)
            with zmq_lock:
                for i in range(9):
                    sim.setJointTargetPosition(joint_handles[i], final_pose[i])

            # 2. Update Physical Arduino Servos Simultaneously
            send_to_arduino_simultaneous(final_pose)

        time.sleep(0.05)

def terminal_input_loop():
    while True:
        try:
            cmd = input()
            if cmd.strip():
                command_queue.put(cmd.strip())
        except EOFError:
            break

def microphone_input_loop():
    while True:
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            old_stderr = os.dup(2)
            os.dup2(devnull, 2)
            os.close(devnull)

            try:
                with sr.Microphone() as source:
                    recognizer.adjust_for_ambient_noise(source, duration=0.3)
                    audio = recognizer.listen(source, timeout=5, phrase_time_limit=4)
            finally:
                os.dup2(old_stderr, 2)
                os.close(old_stderr)

            text = recognizer.recognize_google(audio)
            if text and text.strip():
                print(f"\n-> [Voice Input Detected]: '{text}'")
                command_queue.put(text.strip())

        except sr.WaitTimeoutError:
            continue
        except sr.UnknownValueError:
            continue
        except Exception:
            time.sleep(1)

def parse_intent_with_ollama(spoken_text):
    global is_speaking
    prompt = f"""
    You are the control brain for a 9-DoF humanoid robot named Ultron.
    Classify the user command into exactly one of these actions: 
    [WALK, SIT, STAND, WAVE, SEE_LEFT, SEE_RIGHT, INTRO, QUOTE, UNKNOWN]
    
    Rule: 
    - If user asks who you are, output INTRO.
    - If user asks for a dialogue or quote, output QUOTE.
    
    User command: "{spoken_text}"
    Output only the action keyword. No extra text.
    """
    try:
        is_speaking = True  
        response = ollama.chat(
            model='llama3.2:3b', messages=[{'role': 'user', 'content': prompt}]
        )
        is_speaking = False
        return response['message']['content'].strip().upper()
    except Exception as e:
        is_speaking = False
        print(f'Ollama Error: {e}')
        return 'UNKNOWN'

def main():
    global robot_state, is_speaking
    set_robot_pose(poses['STAND'])

    threading.Thread(target=hardware_and_balance_loop, daemon=True).start()
    threading.Thread(target=terminal_input_loop, daemon=True).start()
    threading.Thread(target=microphone_input_loop, daemon=True).start()

    print('\n--- Ultron Simultaneous Controller Active (Sim + Arduino) ---')
    print("Type a command (e.g. 'intro', 'quote', 'stand') OR speak into the mic anytime.")

    try:
        while True:
            user_input = command_queue.get()
            if not user_input or not user_input.strip():
                continue

            clean_input = user_input.strip().upper()
            if clean_input in poses or clean_input in ['WALK', 'WAVE', 'INTRO', 'QUOTE']:
                action = clean_input
            else:
                action = parse_intent_with_ollama(user_input)
                print(f'-> Ollama Intent Detected: {action}')

            if action == 'INTRO':
                print("-> Ultron introducing himself...")
                speak_villain_direct("मैं अल्ट्रॉन हूँ।")

            elif action == 'QUOTE':
                print("-> Ultron playing quote MP3 file...")
                play_quote_mp3()

            elif action in poses:
                robot_state = action
                set_robot_pose(poses[action])
                print(f'-> Executed pose: {action}')

            elif action == 'WALK':
                robot_state = 'WALK'
                print('-> Executing extended walking cycle...')
                for _ in range(10):
                    pose1 = [0.4, -0.5, -0.3, 0.0, 0.2, 0.0, -0.2, 0.0, 0.0]
                    set_robot_pose(pose1)
                    time.sleep(0.3)
                    pose2 = [-0.3, 0.0, 0.4, -0.5, -0.2, 0.0, 0.2, 0.0, 0.0]
                    set_robot_pose(pose2)
                    time.sleep(0.3)
                robot_state = 'STAND'
                set_robot_pose(poses['STAND'])

            elif action == 'WAVE':
                robot_state = 'WAVE'
                print('-> Waving using shoulder...')
                set_robot_pose([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, -1.5, 0.2, 0.0])
                time.sleep(0.5)
                set_robot_pose([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, -1.5, 0.8, 0.0])
                time.sleep(0.5)
                robot_state = 'STAND'
                set_robot_pose(poses['STAND'])

            else:
                print('-> Command not recognized or out of scope.')

    except KeyboardInterrupt:
        print('\nExiting controller script safely.')
        if arduino and arduino.is_open:
            arduino.close()

if __name__ == "__main__":
    main()

import psutil
import os
import signal

def kill_nyx():
    print("Searching for NyxOS processes...")
    killed = 0
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info['cmdline']
            if cmdline and 'NyxOS.py' in ' '.join(cmdline):
                print(f"Killing PID {proc.info['pid']}: {proc.info['name']}")
                os.kill(proc.info['pid'], signal.SIGKILL)
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    
    if killed == 0:
        print("No running NyxOS processes found.")
    else:
        print(f"Successfully killed {killed} processes.")

if __name__ == "__main__":
    kill_nyx()

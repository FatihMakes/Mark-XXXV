import subprocess
import sys

print("Installing requirements...")
subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], check=True)

print("\n✅ Setup complete! Run 'python main.py' to start MARK XXV.")


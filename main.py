import os, subprocess

subprocess.Popen([
    'python', 'web-app.py'
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

os.system('python bot.py')
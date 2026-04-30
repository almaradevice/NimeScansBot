import os, subprocess

print(">>>", subprocess.Popen([
    'python', 'bot.py'
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True))

os.system('python web-app.py')

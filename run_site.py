'''
import sys
import os
current_directory = os.path.dirname(os.path.abspath(__file__))
target_directory = os.path.join(current_directory, '.')
sys.path.insert(0, target_directory)

from site_bot.site_flusk_run import run

run()
'''
from site_bot.site_flusk_run import app

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8000)
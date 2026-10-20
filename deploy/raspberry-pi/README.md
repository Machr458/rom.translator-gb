# Raspberry Pi install

The installer targets 64-bit Debian 12 on Raspberry Pi 3B. It keeps the existing Mainsail listener untouched, serves this app on port 8081, binds the API to localhost:8001, and stores SQLite data plus ROM files under `/var/lib/rom-translator`.

Build the frontend on the development computer so the Pi does not need Node.js:

```sh
REACT_APP_BACKEND_URL= yarn --cwd frontend build
```

Copy the runtime source, build, and deployment files to the Pi. Do not copy `backend/.env` or any local database/session data:

```sh
rsync -av --exclude='.env' --exclude='rom_sessions/' --exclude='data/' --exclude='tests/' --exclude='__pycache__/' --exclude='.pytest_cache/' --exclude='requirements.txt' backend/ pi@192.168.0.120:/home/pi/rom-translator/backend/
rsync -av frontend/build/ pi@192.168.0.120:/home/pi/rom-translator/frontend/build/
rsync -av deploy/raspberry-pi/ pi@192.168.0.120:/home/pi/rom-translator/deploy/raspberry-pi/
```

Then connect to the Pi and install:

```sh
ssh pi@192.168.0.120
cd /home/pi/rom-translator
sudo bash deploy/raspberry-pi/install.sh
```

Open `http://192.168.0.120:8081/` from a device on the same LAN. The app is not protected by login; do not forward port 8081 to the public internet. Enter a provider key in the app's settings. FreeTheAI works through the OpenAI-compatible provider; the Emergent provider is omitted because its SDK depends on a private wheel.

Useful service commands:

```sh
sudo systemctl status rom-translator
sudo journalctl -u rom-translator -f
sudo systemctl restart rom-translator
```
# ROM Translator

Run the app locally on Windows, macOS, or Linux. The backend stores sessions and
translations in a local SQLite database; MongoDB and a Raspberry Pi are not required.

## Requirements

- Python 3.10 or newer
- Node.js 20 LTS with Corepack
- Git

## One-command start

The launch script installs the Python and frontend dependencies on its first
run, then starts both parts of the app. Run it from the repository root.

macOS/Linux:

```sh
bash run-local.sh
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\run-local.ps1
```

Open [http://localhost:3000](http://localhost:3000) and press Ctrl+C in the
terminal to stop the app. The backend and SQLite data remain local to your PC.

## Start the backend

Clone the repository, then run these commands from its root.

macOS/Linux:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements-pi.txt
cd backend
python -m uvicorn server:app --reload --host 127.0.0.1 --port 8001
```

Windows PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend/requirements-pi.txt
cd backend
python -m uvicorn server:app --reload --host 127.0.0.1 --port 8001
```

Leave the backend terminal running.

## Start the frontend

Open a second terminal in the repository and run:

```sh
cd frontend
corepack yarn install
corepack yarn start
```

Open [http://localhost:3000](http://localhost:3000). The development server
forwards `/api` requests to the local backend on port 8001. No `.env` file is
needed for local development.

To translate text, configure an AI provider and your own API key in the app's
settings. Translation usage may incur charges from that provider.

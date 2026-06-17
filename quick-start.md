# Quick start guide

Place the provided wheel file in the desired directory, and then navigate to that directory, create a virtual environment, start it and install Civex.

On Windows
```bash
python -m venv venv
source venv/bin/activate
pip install "civex-0.0.3-py3-none-any.whl[server]"
```

On MacOS
```bash
python -m venv venv
venv\Scripts\activate.bat
pip install "civex-0.0.3-py3-none-any.whl[server]"
```

And then initialise the repository and start the server.

```bash
civex init --sqlite
civex serve
```

And go to `localhost:8000` on your browser.

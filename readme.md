# OCPP Server

### Local

1. Install requirements `pip install -r requirements.txt`
2. Once all the packages are installed `fastapi dev main.py`. We can expect the development server to start on port 8000.
3. Test websocket with `websocat ws://0.0.0.0:9000/ocpp/CP001 ` direct in bash
4. Test REST API through browser http://127.0.0.1:8000/api/, http://127.0.0.1:8000/api/charge-points, https://127.0.0.1:8000/api/ocpp/logs/CP001, https://127.0.0.1:8000/api/ocpp/logs

Best practice is to install and run in python virtual environment

### Deployment

Current deployment is in render.

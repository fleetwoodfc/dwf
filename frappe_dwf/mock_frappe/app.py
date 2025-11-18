import os
import json
from flask import Flask, request, jsonify

app = Flask(__name__)
DATA_DIR = '/data'
os.makedirs(DATA_DIR, exist_ok=True)

def save_payload(prefix, payload):
    fname = os.path.join(DATA_DIR, f"{prefix}_{len(os.listdir(DATA_DIR)) + 1}.json")
    with open(fname, 'w') as f:
        json.dump(payload, f, indent=2)
    return fname

@app.route('/receive_ian', methods=['POST'])
def receive_ian():
    payload = request.get_json(force=True, silent=True) or {'raw': request.data.decode('utf-8')}
    saved = save_payload('ian', payload)
    return jsonify({'status':'received', 'saved': saved}), 201

@app.route('/create_pps', methods=['POST'])
def create_pps():
    payload = request.get_json(force=True, silent=True) or {'raw': request.data.decode('utf-8')}
    saved = save_payload('pps', payload)
    return jsonify({'status':'received', 'saved': saved}), 201

@app.route('/create_ups', methods=['POST'])
def create_ups():
    payload = request.get_json(force=True, silent=True) or {'raw': request.data.decode('utf-8')}
    saved = save_payload('ups', payload)
    return jsonify({'status':'received', 'saved': saved}), 201

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status':'ok'}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
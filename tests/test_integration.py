import os
import json
import requests

MOCK_URL = os.environ.get('MOCK_URL', 'http://localhost:5000')

def test_health():
    r = requests.get(f"{MOCK_URL}/health", timeout=5)
    assert r.status_code == 200
    assert r.json().get('status') == 'ok'

def test_receive_ian():
    with open('frappe_dwf/mock_frappe/data/sample_ian.json') as f:
        payload = json.load(f)
    r = requests.post(f"{MOCK_URL}/receive_ian", json=payload, timeout=5)
    assert r.status_code == 201
    assert 'saved' in r.json()

def test_create_pps():
    with open('frappe_dwf/mock_frappe/data/sample_pps.json') as f:
        payload = json.load(f)
    r = requests.post(f"{MOCK_URL}/create_pps", json=payload, timeout=5)
    assert r.status_code == 201
    assert 'saved' in r.json()

def test_create_ups():
    with open('frappe_dwf/mock_frappe/data/sample_ups.json') as f:
        payload = json.load(f)
    r = requests.post(f"{MOCK_URL}/create_ups", json=payload, timeout=5)
    assert r.status_code == 201
    assert 'saved' in r.json()
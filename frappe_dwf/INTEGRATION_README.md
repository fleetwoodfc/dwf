```markdown
# Integration test harness (Orthanc + mock webhook)

This folder contains a small docker-compose setup to run Orthanc (PACS) and a mock webhook receiver that simulates the Frappe endpoints for IAN/MPPS/UPS ingestion.

Files:
- docker-compose.integration.yml (repo root) — runs Orthanc and the mock webhook
- frappe_dwf/mock_frappe/* — Dockerfile, app, requirements and sample payloads
- tests/test_integration.py — pytest tests that POST sample payloads to the mock webhook

Quick run (from repo root)
1. Build and start services:
   docker-compose -f docker-compose.integration.yml up --build

2. Wait until mock_frappe is ready (exposes http://localhost:5000)
   You can check health:
     curl http://localhost:5000/health

3. Run integration tests (in another terminal)
   - Install pytest and requests:
       pip install pytest requests
   - Run tests:
       pytest -q tests/test_integration.py::test_health tests/test_integration.py::test_receive_ian tests/test_integration.py::test_create_pps tests/test_integration.py::test_create_ups

Notes
- Orthanc is included so you can extend tests to push DICOM instances and then test real IAN generation. Orthanc UI will be at http://localhost:8042.
- The mock webhook stores JSON payloads to `./frappe_dwf/mock_frappe/data` inside the container, which is volume-mounted to the host. Check that directory to see saved payload files.
- For real integration, replace the mock webhook with the Frappe app endpoints:
   - POST /api/method/frappe_dwf.api.receive_ian
   - POST /api/method/frappe_dwf.api.create_pps
   - POST /api/method/frappe_dwf.api.create_ups
  and secure the endpoints (API keys / mutual TLS).

Security
- The mock service is intentionally simple; do not expose it to untrusted networks.
- When connecting Orthanc to Frappe endpoints, use HTTPS and authenticated clients.
```
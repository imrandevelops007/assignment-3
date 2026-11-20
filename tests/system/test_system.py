"""System tests (Section 5).

Each test uses the provided `system` fixture, which runs serve.py as a
separate process with a fresh database seeded as in SPEC.md. The tests see
the system only through HTTP and its outbox; nothing is imported from src/.
"""

import threading
from collections import Counter

import pytest
import requests

pytestmark = pytest.mark.system

API_KEY = "registrar-key"



# 5(a) End-to-end scenarios

def test_main_success_scenario_student_enrolls_and_everything_agrees(system):
    """REQ-1, REQ-2, REQ-4, REQ-5, REQ-7: S01 (completed CIS350) enrolls in SE413."""
    response = system.enroll("S01", "SE413")

    # the response
    assert response.status_code == 201
    assert response.json() == {"student_id": "S01", "course_code": "SE413",
                               "credits": 3, "total_credits": 3, "fee": 300.0}
    # the schedule
    schedule = system.get("/students/S01/schedule")
    assert schedule.status_code == 200
    assert schedule.json() == {
        "student_id": "S01",
        "courses": [{"code": "SE413", "title": "Software Testing", "credits": 3}],
        "total_credits": 3,
        "fee": 300.0,
    }
    # the course's seats
    assert system.get("/courses/SE413").json()["seats_taken"] == 1
    # the outbox
    assert system.outbox() == [
        {"type": "confirmation", "student_id": "S01", "course_code": "SE413", "fee": 300.0}
    ]


def test_alternative_flow_missing_prerequisite_is_refused_and_notified(system):
    """REQ-1, REQ-5, REQ-7: S13 (completed nothing) cannot enroll in SE413 (needs CIS350)."""
    response = system.enroll("S13", "SE413")

    # the response
    assert response.status_code == 422
    assert response.json() == {"error": "prerequisite CIS350 not completed"}
    # the schedule is unchanged
    assert system.get("/students/S13/schedule").json() == {
        "student_id": "S13", "courses": [], "total_credits": 0, "fee": 0.0,
    }
    # no seat taken
    assert system.get("/courses/SE413").json()["seats_taken"] == 0
    # the outbox holds the rejection with its reason
    assert system.outbox() == [
        {"type": "rejection", "student_id": "S13", "course_code": "SE413",
         "reason": "prerequisite CIS350 not completed"}
    ]



# 5(b) Robustness and security (REQ-8)

BAD_BODIES = [
    pytest.param('{"student_id": "S01"}', id="missing-course_code"),
    pytest.param('{}', id="missing-both-fields"),
    pytest.param('{"student_id": 1, "course_code": "SE413"}', id="wrong-type-number"),
    pytest.param('{"student_id": null, "course_code": "SE413"}', id="wrong-type-null"),
    pytest.param('["S01", "SE413"]', id="non-object-list"),
    pytest.param('"S01"', id="non-object-string"),
    pytest.param('{"student_id": "S01", "course_code": ', id="malformed-json"),
    pytest.param('', id="empty-body"),
    pytest.param('{"student_id": "S01\' OR \'1\'=\'1", "course_code": "SE413"}',
                 id="sql-injection"),
    pytest.param('{"student_id": "<script>alert(1)</script>", "course_code": "SE413"}',
                 id="script-injection"),
    pytest.param('{"student_id": "' + "S" * 10_000 + '", "course_code": "SE413"}',
                 id="oversized-id"),
]


@pytest.mark.parametrize("body", BAD_BODIES)
def test_invalid_or_hostile_enrollment_body_gets_json_400_and_changes_nothing(system, body):
    """REQ-8, REQ-5: a bad body gets a JSON 400; no seat is taken and nothing is sent."""
    response = requests.post(
        f"{system.url}/enrollments", data=body, timeout=10,
        headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert response.headers["Content-Type"].startswith("application/json")
    assert "error" in response.json()
    # nothing changed
    assert system.get("/courses/SE413").json()["seats_taken"] == 0
    assert system.get("/students/S01/schedule").json()["courses"] == []
    assert system.outbox() == []


ENDPOINTS = [
    pytest.param("POST", "/enrollments", id="POST-enrollments"),
    pytest.param("DELETE", "/enrollments/S14/MTH201", id="DELETE-enrollment"),
    pytest.param("GET", "/students/S01/schedule", id="GET-schedule"),
    pytest.param("GET", "/courses/SE413", id="GET-course"),
]
KEYS = [
    pytest.param({}, id="no-key"),
    pytest.param({"X-API-Key": "wrong-key"}, id="wrong-key"),
]


@pytest.mark.parametrize("headers", KEYS)
@pytest.mark.parametrize("method, path", ENDPOINTS)
def test_every_endpoint_except_health_requires_the_api_key(system, method, path, headers):
    """REQ-8: without the right X-API-Key every endpoint answers a JSON 401 and changes nothing."""
    response = requests.request(
        method, system.url + path, headers=headers, timeout=10,
        json={"student_id": "S01", "course_code": "SE413"} if method == "POST" else None,
    )

    assert response.status_code == 401
    assert response.json() == {"error": "missing or invalid API key"}
    assert system.outbox() == []
    assert system.get("/courses/SE413").json()["seats_taken"] == 0
    assert system.get("/courses/MTH201").json()["seats_taken"] == 1  # S14 still enrolled


def test_health_needs_no_api_key(system):
    """REQ-8: GET /health is the one request that needs no key."""
    response = requests.get(f"{system.url}/health", timeout=10)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}






# 5(c) Concurrency (REQ-2)


def test_ten_students_racing_for_three_seats_get_exactly_three(system):
    """REQ-2, REQ-5: 10 simultaneous requests for SE499 (3 seats) -> exactly 3 enrolled."""
    students = [f"S{n:02d}" for n in range(1, 11)]       # S01..S10, all eligible
    barrier = threading.Barrier(len(students))
    statuses = {}

    def request_seat(student_id):
        barrier.wait(timeout=10)                         # all threads start together
        response = requests.post(
            f"{system.url}/enrollments", timeout=30,
            headers={"X-API-Key": API_KEY},
            json={"student_id": student_id, "course_code": "SE499"},
        )
        statuses[student_id] = response.status_code

    threads = [threading.Thread(target=request_seat, args=(s,)) for s in students]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    # HTTP responses: exactly 3 enrolled, 7 refused as full
    assert Counter(statuses.values()) == {201: 3, 409: 7}
    # the database never over-fills
    assert system.get("/courses/SE499").json()["seats_taken"] == 3
    # the outbox agrees with the responses
    outbox = [m for m in system.outbox() if m["course_code"] == "SE499"]
    confirmed = {m["student_id"] for m in outbox if m["type"] == "confirmation"}
    rejected = [m for m in outbox if m["type"] == "rejection"]
    assert len(confirmed) == 3 and len(rejected) == 7
    assert all(m["reason"] == "course is full" for m in rejected)
    assert confirmed == {s for s, code in statuses.items() if code == 201}
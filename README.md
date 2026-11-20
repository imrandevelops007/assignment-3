# Assignment 3 — Integration and System Testing (Starter Code)

This is the starter code for SE 413/513 Assignment 3. The **Course
Registration System** from Assignments 1–2 is now a small, complete
system: an HTTP API, a service, and a SQLite database, built on the same
`can_register()` and `calculate_registration_fee()` you tested before.
Everything in `src/` and `serve.py` is provided and **must not be
modified**. `SPEC.md` is the specification your tests check against.

## Project layout

```
assignment-3/
|-- src/
|   |-- registration.py      can_register(), calculate_registration_fee() (Assignments 1-2)
|   |-- db.py                schema, connect(), seed data
|   |-- repository.py        all SQL (RegistrationRepository)
|   |-- service.py           RegistrationService: enroll(), withdraw(), schedule()
|   |-- notifier.py          OutboxNotifier (used by serve.py)
|   |-- errors.py            exceptions shared by the components
|   `-- api.py               Flask HTTP API
|-- serve.py                 runs the whole system as one process
|-- SPEC.md                  requirements REQ-1..8, HTTP API, seed data
|-- tests/
|   |-- integration/conftest.py       (implement your fixtures here)
|   |-- integration/test_integration.py (implement your tests here)
|   |-- system/conftest.py            (PROVIDED: starts serve.py for each test)
|   `-- system/test_system.py         (implement your tests here)
|-- pyproject.toml
|-- requirements.txt
`-- README.md
```

## Setup

1. (Recommended) Create and activate a virtual environment:

   ```
   python -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   ```

2. Install dependencies:

   ```
   pip install -r requirements.txt
   ```

## Running the system by hand

```
python serve.py
```

prints `READY url=http://127.0.0.1:8000 outbox=...`. In a second terminal:

```
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/enrollments -H 'X-API-Key: registrar-key' \
     -H 'Content-Type: application/json' -d '{"student_id": "S01", "course_code": "SE413"}'
curl http://127.0.0.1:8000/students/S01/schedule -H 'X-API-Key: registrar-key'
```

(On Windows PowerShell, use `curl.exe` and escape the inner quotes, or
use Python's `requests`.) Every start uses a fresh database seeded as in
`SPEC.md`, unless you pass `--db <file>`.

## Running the tests

From the project root:

```
pytest                    # everything
pytest -m integration     # integration tests only
pytest -m system          # system tests only (each starts its own server)
```

## Notes

- Do not modify `src/` or `serve.py`. The starter contains **one known
  defect** (Section 4(d) of the assignment): document it with a test, do
  not fix it.
- Modules in `src/` are importable directly in your tests (no `src.`
  prefix), e.g. `from repository import RegistrationRepository`.
- `xfail_strict = true` is set in `pyproject.toml`: an `xfail` test that
  unexpectedly passes is reported as a failure.
- System tests must not import from `src/`: they see only HTTP and the
  outbox, through the provided `system` fixture.


  
---

## Section 3: Setup check

Started the system with `python serve.py` and, from a second terminal:

```
(.venv) PS E:\assignment-3> python -c "import requests; print(requests.get('http://127.0.0.1:8000/health').json())"
{'status': 'ok'}
(.venv) PS E:\assignment-3> python -c "import requests; r = requests.post('http://127.0.0.1:8000/enrollments', headers={'X-API-Key': 'registrar-key'}, json={'student_id': 'S01', 'course_code': 'SE413'}); print(r.status_code, r.json())"
201 {'course_code': 'SE413', 'credits': 3, 'fee': 300.0, 'student_id': 'S01', 'total_credits': 3}
(.venv) PS E:\assignment-3> python -c "import requests; print(requests.get('http://127.0.0.1:8000/students/S01/schedule', headers={'X-API-Key': 'registrar-key'}).json())"
{'courses': [{'code': 'SE413', 'credits': 3, 'title': 'Software Testing'}], 'fee': 300.0, 'student_id': 'S01', 'total_credits': 3}
```

---

## Section 4: Integration Testing

### 4(a) Integration points

| IP | Components | How they communicate | One thing the two sides could disagree about |
|---|---|---|---|
| IP1 | HTTP client → `api.py` | HTTP + JSON, `X-API-Key` header | The request body: the client might send `studentId` or a number where the API expects a `student_id` string of 1–20 letters/digits, or expect a different status code (e.g. 400 vs 422) for the same problem. |
| IP2 | `api.py` → `RegistrationService` | Python call + exceptions (`errors.py`) | Which exception means what: if the service raised a different exception for a full course, the API would no longer map it to `409 course is full`. Also the keys of the returned dict, which the API sends back as JSON. |
| IP3 | `RegistrationService` → `RegistrationRepository` | Python call + transactions (`with connection:`) | Who commits: the repository never commits, so the service must wrap related writes in one transaction. Also what return values mean, e.g. `take_seat()` returning `False` for "full". |
| IP4 | `RegistrationRepository` → SQLite | SQL against the schema in `db.py` | What the SQL actually selects or changes, e.g. whether a `DELETE` is limited to one student, and which constraints (primary key, `CHECK seats_taken <= capacity`, foreign keys) the database enforces. |
| IP5 | `RegistrationService` → notifier | Python call: `send_confirmation(student_id, course_code, fee)` / `send_rejection(student_id, course_code, reason)` | The arguments (order, fee as a number, the exact reason text) and *when* a message is sent, e.g. a duplicate enrollment must send nothing (REQ-5). |

### 4(b) and 4(c) What the integration tests check

The integration tests use the real `RegistrationRepository` and `RegistrationService`
on a real SQLite file in `tmp_path`, with a small catalog of their own
(`tests/integration/conftest.py`). Only the notifier is replaced, by `FakeNotifier`,
which records every call in a list.

| Test | Integration point | Checks |
|---|---|---|
| `test_take_seat_fills_last_seat_then_refuses_without_changing_anything` | IP4 | The last seat succeeds; one more is refused and `seats_taken` stays at capacity. |
| `test_duplicate_enrollment_is_rejected_by_the_database` | IP4 | The primary key raises `IntegrityError` on a duplicate; only one row remains. |
| `test_current_credits_counts_only_that_students_courses` | IP4 | Only that student's courses are summed; 0 for a student with none. |
| `test_transaction_failing_part_way_leaves_neither_seat_nor_enrollment` | IP3, IP4 | A failure after `take_seat()` rolls back both the seat and the enrollment. |
| `test_successful_enrollment_saves_enrollment_takes_seat_and_confirms_fee` | IP3, IP5 | Enrolled, one seat taken, confirmation with fee $300. |
| `test_full_course_raises_course_full_and_sends_rejection` | IP3, IP5 | `CourseFull`, not enrolled, rejection with `"course is full"`. |
| `test_duplicate_enrollment_raises_already_enrolled_and_sends_nothing` | IP3, IP5 | `AlreadyEnrolled`, no extra seat, nothing sent. |

### 4(d) The known defect

**Defect:** `RegistrationRepository.remove_enrollment()` runs
`DELETE FROM enrollments WHERE course_code = ?` and ignores `student_id`. When one
student withdraws, **every** student's enrollment in that course is deleted, while
`release_seat()` frees only one seat. This violates REQ-6.

`test_withdraw_removes_only_that_students_enrollment` enrolls two students, withdraws
one, and asserts the other is still enrolled. It is marked
`@pytest.mark.xfail(strict=True)` and fails with `assert [] == ['INTRO']`. With a
single student in the course (`test_withdraw_with_one_student_frees_the_seat`), the
defect is invisible, because "delete everyone in the course" and "delete this
student" give the same result.

**Why a unit test with a mocked repository would pass:** with a `Mock` in place of
the repository, `remove_enrollment()` never runs any SQL; it simply returns whatever
the test configured (e.g. `True`). Such a test can only check that `withdraw()`
calls `remove_enrollment(student_id, course_code)` and then
`release_seat(course_code)`, which the service does correctly. The defect is in the
SQL the real repository sends to SQLite (IP4), so only a test against a real
database with two students enrolled can see it.



---

## Section 5: System Testing

System tests use the provided `system` fixture, which starts `serve.py` as a
separate process with a fresh database seeded as in `SPEC.md`. They observe the
system only through HTTP and the outbox; `tests/system/` imports nothing from `src/`.

### 5(a) End-to-end scenarios

| Test | Scenario | Checks |
|---|---|---|
| `test_main_success_scenario_student_enrolls_and_everything_agrees` | S01 (completed CIS350) enrolls in SE413 | 201 with fee $300; schedule lists SE413 with 3 credits and $300; `seats_taken` is 1; outbox holds one confirmation with fee 300.0 |
| `test_alternative_flow_missing_prerequisite_is_refused_and_notified` | S13 (completed nothing) tries SE413, which needs CIS350 | 422 `prerequisite CIS350 not completed`; schedule empty with fee $0; `seats_taken` is 0; outbox holds one rejection with that reason |

### 5(b) Robustness and security (REQ-8)

- `test_invalid_or_hostile_enrollment_body_gets_json_400_and_changes_nothing` is
  parametrized over 11 bodies: missing fields, wrong types (number, `null`),
  non-object bodies (list, string), malformed JSON, an empty body, SQL injection,
  script injection, and a 10,000-character id. Each gets a JSON `400`, no seat is
  taken, S01's schedule stays empty, and the outbox stays empty.
- `test_every_endpoint_except_health_requires_the_api_key` is parametrized over all
  four endpoints × (no key, wrong key). Each gets a JSON `401` and changes nothing.
  The DELETE case targets S14's real MTH201 enrollment, which is still there afterwards.
- `test_health_needs_no_api_key` confirms `/health` answers `200` without a key.

### 5(c) Concurrency (REQ-2)

`test_ten_students_racing_for_three_seats_get_exactly_three` starts one thread per
student (S01–S10), releases them together with a `threading.Barrier`, and has each
send `POST /enrollments` for SE499 (3 seats). It asserts exactly three `201`s and
seven `409`s, `seats_taken == 3`, and three confirmations and seven
`course is full` rejections in the outbox, for the same three students who got `201`.

**Why this must be a system test rather than an integration test:** the integration
tests call the service one call at a time on a single shared connection inside the
test process, so two enrollments can never actually overlap. The race only exists in
the running system, where `serve.py`'s threaded server handles each request on its
own thread with its own database connection. Only real simultaneous HTTP requests
exercise the locking that REQ-2 depends on.




---

## Section 6: Organizing and Running the Test Suite

### 6(a) Markers and commands

Every test carries one marker, applied to the whole file with `pytestmark`:

| Marker | File | Tests |
|---|---|---|
| `integration` | `tests/integration/test_integration.py` | 9 (8 pass, 1 strict xfail) |
| `system` | `tests/system/test_system.py` | 23 |

Run from the project root with the virtual environment activated
(`pip install -r requirements.txt`):

```
pytest                    # full suite
pytest -v                 # full suite, one line per test
pytest -m integration     # integration tests only
pytest -m system          # system tests only (each starts its own server)
pytest -m integration --runxfail -k only_that   # show the known defect's actual failure
```

Every requirement a test checks is listed (REQ-1 to REQ-8) in that test's docstring.

**Test independence:** every integration fixture is function-scoped, so each test
gets a brand-new SQLite file in its own `tmp_path` and a fresh `FakeNotifier`. Each
system test gets its own `serve.py` process with a freshly seeded database and an
empty outbox. No test depends on another's data or execution order.

### 6(b) Evidence that the full suite passes

The strict xfail from 4(d) is the only test that does not pass.

```
(.venv) PS E:\assignment-3> pytest -v
================================== test session starts ==================================
platform win32 -- Python 3.13.5, pytest-9.2.0, pluggy-1.7.0 -- E:\assignment-3\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: E:\assignment-3
configfile: pyproject.toml
testpaths: tests
collected 32 items

tests/integration/test_integration.py::test_take_seat_fills_last_seat_then_refuses_without_changing_anything PASSED [  3%]
tests/integration/test_integration.py::test_duplicate_enrollment_is_rejected_by_the_database PASSED [  6%]
tests/integration/test_integration.py::test_current_credits_counts_only_that_students_courses PASSED [  9%]
tests/integration/test_integration.py::test_transaction_failing_part_way_leaves_neither_seat_nor_enrollment PASSED [ 12%]
tests/integration/test_integration.py::test_successful_enrollment_saves_enrollment_takes_seat_and_confirms_fee PASSED [ 15%]
tests/integration/test_integration.py::test_full_course_raises_course_full_and_sends_rejection PASSED [ 18%]
tests/integration/test_integration.py::test_duplicate_enrollment_raises_already_enrolled_and_sends_nothing PASSED [ 21%]
tests/integration/test_integration.py::test_withdraw_with_one_student_frees_the_seat PASSED [ 25%]
tests/integration/test_integration.py::test_withdraw_removes_only_that_students_enrollment XFAIL [ 28%]
tests/system/test_system.py::test_main_success_scenario_student_enrolls_and_everything_agrees PASSED [ 31%]
tests/system/test_system.py::test_alternative_flow_missing_prerequisite_is_refused_and_notified PASSED [ 34%]
tests/system/test_system.py::test_invalid_or_hostile_enrollment_body_gets_json_400_and_changes_nothing[missing-course_code] PASSED [ 37%]
tests/system/test_system.py::test_invalid_or_hostile_enrollment_body_gets_json_400_and_changes_nothing[missing-both-fields] PASSED [ 40%]
tests/system/test_system.py::test_invalid_or_hostile_enrollment_body_gets_json_400_and_changes_nothing[wrong-type-number] PASSED [ 43%]
tests/system/test_system.py::test_invalid_or_hostile_enrollment_body_gets_json_400_and_changes_nothing[wrong-type-null] PASSED [ 46%]
tests/system/test_system.py::test_invalid_or_hostile_enrollment_body_gets_json_400_and_changes_nothing[non-object-list] PASSED [ 50%]
tests/system/test_system.py::test_invalid_or_hostile_enrollment_body_gets_json_400_and_changes_nothing[non-object-string] PASSED [ 53%]
tests/system/test_system.py::test_invalid_or_hostile_enrollment_body_gets_json_400_and_changes_nothing[malformed-json] PASSED [ 56%]
tests/system/test_system.py::test_invalid_or_hostile_enrollment_body_gets_json_400_and_changes_nothing[empty-body] PASSED [ 59%]
tests/system/test_system.py::test_invalid_or_hostile_enrollment_body_gets_json_400_and_changes_nothing[sql-injection] PASSED [ 62%]
tests/system/test_system.py::test_invalid_or_hostile_enrollment_body_gets_json_400_and_changes_nothing[script-injection] PASSED [ 65%]
tests/system/test_system.py::test_invalid_or_hostile_enrollment_body_gets_json_400_and_changes_nothing[oversized-id] PASSED [ 68%]
tests/system/test_system.py::test_every_endpoint_except_health_requires_the_api_key[POST-enrollments-no-key] PASSED [ 71%]
tests/system/test_system.py::test_every_endpoint_except_health_requires_the_api_key[POST-enrollments-wrong-key] PASSED [ 75%]
tests/system/test_system.py::test_every_endpoint_except_health_requires_the_api_key[DELETE-enrollment-no-key] PASSED [ 78%]
tests/system/test_system.py::test_every_endpoint_except_health_requires_the_api_key[DELETE-enrollment-wrong-key] PASSED [ 81%]
tests/system/test_system.py::test_every_endpoint_except_health_requires_the_api_key[GET-schedule-no-key] PASSED [ 84%]
tests/system/test_system.py::test_every_endpoint_except_health_requires_the_api_key[GET-schedule-wrong-key] PASSED [ 87%]
tests/system/test_system.py::test_every_endpoint_except_health_requires_the_api_key[GET-course-no-key] PASSED [ 90%]
tests/system/test_system.py::test_every_endpoint_except_health_requires_the_api_key[GET-course-wrong-key] PASSED [ 93%]
tests/system/test_system.py::test_health_needs_no_api_key PASSED                   [ 96%]
tests/system/test_system.py::test_ten_students_racing_for_three_seats_get_exactly_three PASSED [100%]

============================ 31 passed, 1 xfailed in 32.30s =============================
```

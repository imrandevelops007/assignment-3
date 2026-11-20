"""Fixtures for the integration tests (Section 4).

The tests assemble the REAL repository and service on a REAL SQLite
database file in pytest's tmp_path. Only the notifier (IP5, which in
production would send email) is replaced, by FakeNotifier below.

Every fixture is function-scoped: each test gets a brand-new database
file, so no test can see data left behind by another.
"""

import pytest

import db
from repository import RegistrationRepository
from service import RegistrationService


class FakeNotifier:
    """Test double for the notifier: records every call instead of sending it."""

    def __init__(self):
        self.sent = []

    def send_confirmation(self, student_id, course_code, fee):
        self.sent.append(("confirmation", student_id, course_code, fee))

    def send_rejection(self, student_id, course_code, reason):
        self.sent.append(("rejection", student_id, course_code, reason))


@pytest.fixture
def connection(tmp_path):
    """A new SQLite database file with the schema and a small test catalog.

    Courses:  INTRO  (4 credits, 10 seats, no prerequisite)
              ADV    (3 credits,  2 seats, prerequisite INTRO)
              SMALL  (1 credit,   1 seat,  no prerequisite)
    Students: A1 and A2 (completed INTRO), B1 (completed nothing)
    """
    connection = db.connect(tmp_path / "test.db")
    db.create_schema(connection)
    repo = RegistrationRepository(connection)
    with connection:
        repo.add_course("INTRO", "Introduction", 4, 10)
        repo.add_course("ADV", "Advanced Topics", 3, 2, prerequisite="INTRO")
        repo.add_course("SMALL", "Small Seminar", 1, 1)
        for student_id, name in [("A1", "Alice"), ("A2", "Amir"), ("B1", "Bea")]:
            repo.add_student(student_id, name)
        repo.add_completed("A1", "INTRO")
        repo.add_completed("A2", "INTRO")
    yield connection
    connection.close()


@pytest.fixture
def repository(connection):
    """The real RegistrationRepository on the test database."""
    return RegistrationRepository(connection)


@pytest.fixture
def notifier():
    """A fresh FakeNotifier with nothing recorded."""
    return FakeNotifier()


@pytest.fixture
def service(connection, repository, notifier):
    """The real RegistrationService, wired to the real repository and the fake notifier."""
    return RegistrationService(connection, repository, notifier)
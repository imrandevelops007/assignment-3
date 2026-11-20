"""Integration tests (Section 4).

Real RegistrationRepository and RegistrationService on a real SQLite file
(fixtures in conftest.py). Only the notifier is a test double (FakeNotifier).
"""

import sqlite3

import pytest

from errors import AlreadyEnrolled, CourseFull

pytestmark = pytest.mark.integration


def seats_taken(repository, code):
    return repository.get_course(code)["seats_taken"]


def enrollment_count(connection, course_code):
    return connection.execute(
        "SELECT COUNT(*) FROM enrollments WHERE course_code = ?", (course_code,)
    ).fetchone()[0]



# 4(b) Repository + SQLite (IP4)


def test_take_seat_fills_last_seat_then_refuses_without_changing_anything(connection, repository):
    """REQ-2: the last seat can be taken; one more is refused and seats_taken stays at capacity."""
    with connection:
        assert repository.take_seat("ADV") is True    # seat 1 of 2
        assert repository.take_seat("ADV") is True    # seat 2 of 2: the last seat
    assert seats_taken(repository, "ADV") == 2

    with connection:
        assert repository.take_seat("ADV") is False   # one more: refused
    assert seats_taken(repository, "ADV") == 2        # nothing changed


def test_duplicate_enrollment_is_rejected_by_the_database(connection, repository):
    """REQ-3: the enrollments primary key refuses a second (student, course) row."""
    with connection:
        repository.add_enrollment("A1", "INTRO")

    with pytest.raises(sqlite3.IntegrityError):
        with connection:
            repository.add_enrollment("A1", "INTRO")

    assert enrollment_count(connection, "INTRO") == 1


def test_current_credits_counts_only_that_students_courses(connection, repository):
    """REQ-1: current_credits is the total credits of the student's own enrollments."""
    with connection:
        repository.add_enrollment("A1", "INTRO")   # 4 credits
        repository.add_enrollment("A1", "SMALL")   # 1 credit
        repository.add_enrollment("A2", "ADV")     # 3 credits, another student

    assert repository.current_credits("A1") == 5
    assert repository.current_credits("A2") == 3
    assert repository.current_credits("B1") == 0   # enrolled in nothing


def test_transaction_failing_part_way_leaves_neither_seat_nor_enrollment(connection, repository):
    """REQ-2, REQ-3: the seat and the enrollment are saved together or not at all."""
    with pytest.raises(sqlite3.IntegrityError):
        with connection:
            assert repository.take_seat("INTRO") is True        # step 1 succeeds
            repository.add_enrollment("NOSUCH", "INTRO")         # step 2: unknown student,
                                                                 # foreign key fails
    assert seats_taken(repository, "INTRO") == 0                 # seat rolled back
    assert enrollment_count(connection, "INTRO") == 0            # no enrollment
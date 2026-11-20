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






# 4(c) Service + repository + notifier (IP3, IP5)


def test_successful_enrollment_saves_enrollment_takes_seat_and_confirms_fee(
        service, repository, notifier):
    """REQ-1, REQ-2, REQ-4, REQ-5: enrolled, one seat taken, confirmation with the fee."""
    result = service.enroll("A1", "ADV")

    assert result == {"student_id": "A1", "course_code": "ADV",
                      "credits": 3, "total_credits": 3, "fee": 300.0}
    # database side
    assert [c["code"] for c in repository.enrolled_courses("A1")] == ["ADV"]
    assert seats_taken(repository, "ADV") == 1
    # notifier side
    assert notifier.sent == [("confirmation", "A1", "ADV", 300.0)]


def test_full_course_raises_course_full_and_sends_rejection(service, repository, notifier):
    """REQ-2, REQ-5: no seat left -> CourseFull, not enrolled, rejection with its reason."""
    service.enroll("A1", "SMALL")                      # takes the only seat

    with pytest.raises(CourseFull):
        service.enroll("A2", "SMALL")

    # database side
    assert repository.enrolled_courses("A2") == []
    assert seats_taken(repository, "SMALL") == 1
    # notifier side
    assert notifier.sent[-1] == ("rejection", "A2", "SMALL", "course is full")


def test_duplicate_enrollment_raises_already_enrolled_and_sends_nothing(
        service, repository, notifier):
    """REQ-3, REQ-5: second enrollment -> AlreadyEnrolled, no extra seat, no notification."""
    service.enroll("A1", "INTRO")
    sent_before = list(notifier.sent)

    with pytest.raises(AlreadyEnrolled):
        service.enroll("A1", "INTRO")

    # database side
    assert seats_taken(repository, "INTRO") == 1       # no extra seat taken
    assert [c["code"] for c in repository.enrolled_courses("A1")] == ["INTRO"]
    # notifier side
    assert notifier.sent == sent_before                # nothing new sent






# 4(d) The known defect: withdrawing (REQ-6)

def test_withdraw_with_one_student_frees_the_seat(service, repository):
    """REQ-6: with a single student in the course, withdrawing looks correct."""
    service.enroll("A1", "INTRO")

    service.withdraw("A1", "INTRO")

    assert repository.enrolled_courses("A1") == []
    assert seats_taken(repository, "INTRO") == 0


@pytest.mark.xfail(
    strict=True,
    reason="Known defect (REQ-6): RegistrationRepository.remove_enrollment() deletes "
           "WHERE course_code = ? without checking student_id, so one student's "
           "withdrawal removes every student's enrollment in that course "
           "while release_seat() frees only one seat.",
)
def test_withdraw_removes_only_that_students_enrollment(service, repository):
    """REQ-6: withdrawing frees exactly one seat and removes only that student's enrollment."""
    service.enroll("A1", "INTRO")
    service.enroll("A2", "INTRO")
    assert seats_taken(repository, "INTRO") == 2

    service.withdraw("A1", "INTRO")

    assert repository.enrolled_courses("A1") == []
    assert [c["code"] for c in repository.enrolled_courses("A2")] == ["INTRO"]  # fails
    assert seats_taken(repository, "INTRO") == 1
from __future__ import annotations

import secrets
from datetime import date, timedelta
from typing import Any, Optional

from .models import (
    Book,
    Borrower,
    Copy,
    CopyStatus,
    Library,
    Reservation,
    RoomReservation,
    RoomReservationState,
    StudyRoom,
)

# Study rooms: 9:00–19:00; bookings are 1 hour; last start hour is 18 (6pm–7pm).
STUDY_FIRST_START_HOUR = 9
STUDY_LAST_START_HOUR = 18
MAX_ACTIVE_STUDY_ROOM_RESERVATIONS = 8


def _fine_rate(book: Book) -> float:
    return 1.0 if book.is_reference else 0.25


def _loan_days(book: Book) -> int:
    return 3 if book.is_reference else 10


def _reservations_for_book(lib: Library, isbn: str) -> list[Reservation]:
    return sorted(
        [r for r in lib.reservations if r.isbn == isbn],
        key=lambda r: (r.date_reserved, r.reservation_id),
    )


def _count_checked_out(lib: Library, borrower_id: str) -> int:
    return sum(
        1
        for c in lib.copies.values()
        if c.checked_out_by == borrower_id
        and c.status in (CopyStatus.CHECKED_OUT, CopyStatus.OVERDUE)
    )


def _borrower_blocked(lib: Library, b: Borrower) -> tuple[bool, str]:
    if lib.simulation_date > b.card_expiration:
        return True, "Library card has expired."
    if b.fine_balance > 0:
        return True, "Borrower has outstanding fines."
    if any(
        c.status == CopyStatus.OVERDUE and c.checked_out_by == b.borrower_id
        for c in lib.copies.values()
    ):
        return True, "Borrower has overdue material."
    if _count_checked_out(lib, b.borrower_id) >= 4:
        return True, "Borrower already has the maximum of 4 copies checked out."
    return False, ""


def _can_checkout_book_rules(b: Borrower, book: Book) -> tuple[bool, str]:
    if book.is_reference and b.borrower_type != "Teacher":
        return False, "Only teachers may borrow reference copies."
    return True, ""


def find_borrower_by_card(lib: Library, card_barcode: str) -> Optional[Borrower]:
    card_barcode = (card_barcode or "").strip()
    for b in lib.borrowers.values():
        if b.card_barcode == card_barcode:
            return b
    return None


def could_legally_checkout_for_reserve(lib: Library, b: Borrower, book: Book) -> tuple[bool, str]:
    blocked, msg = _borrower_blocked(lib, b)
    if blocked:
        return False, msg
    ok, msg2 = _can_checkout_book_rules(b, book)
    if not ok:
        return False, msg2
    return True, ""


def any_copy_on_shelf(lib: Library, isbn: str) -> bool:
    return any(c.isbn == isbn and c.status == CopyStatus.ON_SHELF for c in lib.copies.values())


def reservation_count(lib: Library, borrower_id: str) -> int:
    return sum(1 for r in lib.reservations if r.borrower_id == borrower_id)


def add_copy(lib: Library, isbn: str) -> tuple[bool, str, Optional[str]]:
    isbn = isbn.strip()
    if isbn not in lib.books:
        return False, "Unknown ISBN — book must exist before adding a copy.", None
    n = lib._next_copy_num
    lib._next_copy_num += 1
    bc = f"COPY-{n:06d}"
    lib.copies[bc] = Copy(barcode=bc, isbn=isbn, status=CopyStatus.ON_SHELF)
    return True, f"Added {bc} for ISBN {isbn}.", bc


def remove_copy(lib: Library, barcode: str, reason: str) -> tuple[bool, str]:
    barcode = barcode.strip()
    c = lib.copies.get(barcode)
    if not c:
        return False, "Copy not found."
    reason = (reason or "").strip().upper()
    if reason not in ("LOST", "DAMAGED"):
        return False, 'Reason must be LOST or DAMAGED.'
    if c.status in (CopyStatus.CHECKED_OUT, CopyStatus.OVERDUE, CopyStatus.ON_HOLD):
        return False, "Cannot remove a copy that is checked out, overdue, or on hold."
    c.status = CopyStatus.LOST if reason == "LOST" else CopyStatus.DAMAGED
    return True, f"Copy {barcode} marked as {c.status}."


def issue_card(
    lib: Library,
    name: str,
    phone: str,
    borrower_type: str,
    years_valid: int = 1,
) -> tuple[bool, str, Optional[str]]:
    name, phone = name.strip(), phone.strip()
    borrower_type = borrower_type.strip()
    if borrower_type not in ("Student", "Teacher"):
        return False, "Borrower type must be Student or Teacher.", None
    bid = f"B-{lib._next_borrower_num:03d}"
    lib._next_borrower_num += 1
    card = f"CARD-{lib._next_card_num:05d}"
    lib._next_card_num += 1
    exp = lib.simulation_date + timedelta(days=365 * years_valid)
    lib.borrowers[bid] = Borrower(
        borrower_id=bid,
        name=name,
        phone=phone,
        borrower_type=borrower_type,
        fine_balance=0.0,
        card_barcode=card,
        card_expiration=exp,
    )
    return True, f"Issued card {card} to {name} ({bid}).", card


def pay_fines(lib: Library, card_barcode: str, amount: float) -> tuple[bool, str]:
    b = find_borrower_by_card(lib, card_barcode)
    if not b:
        return False, "Borrower not found for that card."
    if amount <= 0:
        return False, "Amount must be positive."
    pay = min(amount, b.fine_balance)
    b.fine_balance = round(b.fine_balance - pay, 2)
    return True, f"Applied ${pay:.2f} toward fines. Remaining balance: ${b.fine_balance:.2f}."


def checkout(lib: Library, card_barcode: str, copy_barcode: str) -> tuple[bool, str]:
    b = find_borrower_by_card(lib, card_barcode)
    if not b:
        return False, "Borrower not found for that card."
    c = lib.copies.get(copy_barcode.strip())
    if not c:
        return False, "Copy not found."
    book = lib.books.get(c.isbn)
    if not book:
        return False, "Book metadata missing for this copy."

    if c.status == CopyStatus.ON_HOLD:
        if c.hold_borrower_id != b.borrower_id:
            return False, "This copy is on hold for another borrower."
    elif c.status != CopyStatus.ON_SHELF:
        return False, f"Copy is not available (status {c.status})."

    blocked, msg = _borrower_blocked(lib, b)
    if blocked:
        return False, msg
    ok, msg2 = _can_checkout_book_rules(b, book)
    if not ok:
        return False, msg2

    due = lib.simulation_date + timedelta(days=_loan_days(book))
    c.status = CopyStatus.CHECKED_OUT
    c.checked_out_by = b.borrower_id
    c.date_checked_out = lib.simulation_date
    c.date_due_back = due
    c.amount_owed = 0.0
    c.hold_borrower_id = None
    c.hold_days_remaining = 0
    lib.reservations = [
        r for r in lib.reservations if not (r.borrower_id == b.borrower_id and r.isbn == c.isbn)
    ]
    return True, f"Checked out to {b.name}. Due {due.isoformat()}."


def _expire_hold(lib: Library, copy: Copy) -> None:
    old = copy.hold_borrower_id
    if old:
        lib.reservations = [r for r in lib.reservations if not (r.borrower_id == old and r.isbn == copy.isbn)]
    copy.hold_borrower_id = None
    copy.hold_days_remaining = 0
    nxt = _reservations_for_book(lib, copy.isbn)
    if nxt:
        copy.hold_borrower_id = nxt[0].borrower_id
        copy.hold_days_remaining = 2
    else:
        copy.status = CopyStatus.ON_SHELF


def return_copy_for_borrower(lib: Library, copy_barcode: str, borrower_id: str) -> tuple[bool, str]:
    """Return a copy only if it is currently checked out to the given borrower (patron self-service)."""
    c = lib.copies.get(copy_barcode.strip())
    if not c:
        return False, "Copy not found."
    if c.checked_out_by != borrower_id:
        return False, "This copy is not checked out on your account."
    return return_copy(lib, copy_barcode)


def return_copy(lib: Library, copy_barcode: str) -> tuple[bool, str]:
    c = lib.copies.get(copy_barcode.strip())
    if not c:
        return False, "Copy not found."
    if c.status not in (CopyStatus.CHECKED_OUT, CopyStatus.OVERDUE):
        return False, "Only checked-out or overdue copies can be returned."

    bid = c.checked_out_by
    borrower = lib.borrowers.get(bid) if bid else None
    if borrower and c.status == CopyStatus.OVERDUE and c.amount_owed > 0:
        borrower.fine_balance = round(borrower.fine_balance + c.amount_owed, 2)

    c.checked_out_by = None
    c.date_checked_out = None
    c.date_due_back = None
    c.amount_owed = 0.0

    queue = _reservations_for_book(lib, c.isbn)
    if queue:
        c.status = CopyStatus.ON_HOLD
        c.hold_borrower_id = queue[0].borrower_id
        c.hold_days_remaining = 2
        msg = f"Returned; copy on hold for {queue[0].borrower_id} (next in queue)."
    else:
        c.status = CopyStatus.ON_SHELF
        msg = "Returned; copy is on the shelf."

    return True, msg


def new_day(lib: Library) -> tuple[bool, str]:
    lib.simulation_date += timedelta(days=1)

    for c in lib.copies.values():
        if c.status == CopyStatus.CHECKED_OUT and c.date_due_back and lib.simulation_date > c.date_due_back:
            c.status = CopyStatus.OVERDUE

    for c in lib.copies.values():
        if c.status == CopyStatus.OVERDUE and c.isbn in lib.books:
            c.amount_owed = round(c.amount_owed + _fine_rate(lib.books[c.isbn]), 2)

    for c in list(lib.copies.values()):
        if c.status != CopyStatus.ON_HOLD:
            continue
        c.hold_days_remaining -= 1
        if c.hold_days_remaining <= 0:
            _expire_hold(lib, c)

    for r in lib.room_reservations:
        if r.state != RoomReservationState.CONFIRMED:
            continue
        if r.booking_date < lib.simulation_date:
            r.state = RoomReservationState.COMPLETED

    return True, f"Simulation date is now {lib.simulation_date.isoformat()}."


def reserve_book(lib: Library, card_barcode: str, isbn: str) -> tuple[bool, str]:
    isbn = isbn.strip()
    b = find_borrower_by_card(lib, card_barcode)
    if not b:
        return False, "Borrower not found for that card."
    book = lib.books.get(isbn)
    if not book:
        return False, "Book not found for that ISBN."

    if reservation_count(lib, b.borrower_id) >= 4:
        return False, "Borrower already has 4 active reservations."
    if any(r.borrower_id == b.borrower_id and r.isbn == isbn for r in lib.reservations):
        return False, "Borrower already has a reservation for this book."

    ok, msg = could_legally_checkout_for_reserve(lib, b, book)
    if not ok:
        return False, msg
    if any_copy_on_shelf(lib, isbn):
        return False, "A copy is already on the shelf; reservations are only when no copy is available."

    rid = f"R-{lib._next_res_num:05d}"
    lib._next_res_num += 1
    lib.reservations.append(
        Reservation(
            reservation_id=rid,
            borrower_id=b.borrower_id,
            isbn=isbn,
            date_reserved=lib.simulation_date,
        )
    )
    return True, f"Reservation {rid} placed for {book.title}."


def delete_borrower(lib: Library, borrower_id: str) -> tuple[bool, str]:
    borrower_id = borrower_id.strip()
    b = lib.borrowers.get(borrower_id)
    if not b:
        return False, "Borrower not found."
    if _count_checked_out(lib, borrower_id) > 0:
        return False, "Borrower still has copies checked out."
    if any(
        c.status == CopyStatus.ON_HOLD and c.hold_borrower_id == borrower_id
        for c in lib.copies.values()
    ):
        return False, "Borrower has a copy on hold."
    lib.reservations = [r for r in lib.reservations if r.borrower_id != borrower_id]
    lib.room_reservations = [r for r in lib.room_reservations if r.borrower_id != borrower_id]
    del lib.borrowers[borrower_id]
    return True, f"Removed borrower {borrower_id}."


# --- Study rooms ---


def _slot_blocks_booking(state: str) -> bool:
    return state in (RoomReservationState.CONFIRMED, RoomReservationState.OUT_OF_SERVICE)


def study_slot_hours() -> list[int]:
    return list(range(STUDY_FIRST_START_HOUR, STUDY_LAST_START_HOUR + 1))


def format_study_slot_label(start_hour: int) -> str:
    def hm(h: int) -> str:
        if h <= 0:
            return "12:00 AM"
        if h < 12:
            return f"{h}:00 AM"
        if h == 12:
            return "12:00 PM"
        return f"{h - 12}:00 PM"

    return f"{hm(start_hour)} – {hm(start_hour + 1)}"


def find_room_reservation_conflict(
    lib: Library,
    room_id: str,
    booking_date: date,
    start_hour: int,
    exclude_reservation_id: Optional[str] = None,
) -> Optional[RoomReservation]:
    for r in lib.room_reservations:
        if exclude_reservation_id and r.reservation_id == exclude_reservation_id:
            continue
        if r.room_id != room_id or r.booking_date != booking_date or r.start_hour != start_hour:
            continue
        if _slot_blocks_booking(r.state):
            return r
    return None


def _count_confirmed_room_reservations(lib: Library, borrower_id: str) -> int:
    return sum(
        1
        for r in lib.room_reservations
        if r.borrower_id == borrower_id and r.state == RoomReservationState.CONFIRMED
    )


def study_room_schedule_for_date(lib: Library, booking_date: date) -> dict[str, Any]:
    slots = study_slot_hours()
    rows: list[dict[str, Any]] = []
    for room in sorted(lib.study_rooms.values(), key=lambda x: x.room_id):
        slot_cells: list[dict[str, Any]] = []
        for h in slots:
            if not room.is_active:
                slot_cells.append({"kind": "inactive"})
                continue
            rr = find_room_reservation_conflict(lib, room.room_id, booking_date, h)
            if rr:
                slot_cells.append({"kind": "taken", "state": rr.state})
            else:
                slot_cells.append({"kind": "free"})
        rows.append({"room": room, "slots": slot_cells})
    return {"booking_date": booking_date, "slots": slots, "rows": rows}


def borrower_upcoming_room_reservations(lib: Library, borrower_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in lib.room_reservations:
        if r.borrower_id != borrower_id or r.state != RoomReservationState.CONFIRMED:
            continue
        if r.booking_date < lib.simulation_date:
            continue
        room = lib.study_rooms.get(r.room_id)
        out.append(
            {
                "reservation_id": r.reservation_id,
                "room_id": r.room_id,
                "room_name": room.name if room else r.room_id,
                "room_location": room.location if room else "",
                "booking_date": r.booking_date.isoformat(),
                "start_hour": r.start_hour,
                "slot_label": format_study_slot_label(r.start_hour),
                "num_attendees": r.num_attendees,
                "confirm_code": r.confirm_code,
                "state": r.state,
            }
        )
    out.sort(key=lambda x: (x["booking_date"], x["start_hour"], x["reservation_id"]))
    return out


def borrower_out_of_service_room_notifications(lib: Library, borrower_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in lib.room_reservations:
        if r.borrower_id != borrower_id or r.state != RoomReservationState.OUT_OF_SERVICE:
            continue
        room = lib.study_rooms.get(r.room_id)
        out.append(
            {
                "reservation_id": r.reservation_id,
                "room_id": r.room_id,
                "room_name": room.name if room else r.room_id,
                "booking_date": r.booking_date.isoformat(),
                "slot_label": format_study_slot_label(r.start_hour),
            }
        )
    out.sort(key=lambda x: (x["booking_date"], x["slot_label"], x["reservation_id"]))
    return out


def reserve_study_room(
    lib: Library,
    card_barcode: str,
    room_id: str,
    booking_date: date,
    start_hour: int,
    num_attendees: int,
) -> tuple[bool, str]:
    room_id = room_id.strip()
    b = find_borrower_by_card(lib, card_barcode)
    if not b:
        return False, "Borrower not found for that card."
    if lib.simulation_date > b.card_expiration:
        return False, "Library card has expired."

    room = lib.study_rooms.get(room_id)
    if not room:
        return False, "Study room not found."
    if not room.is_active:
        return False, "That room is not available for booking (out of service)."

    if booking_date < lib.simulation_date:
        return False, "Booking date cannot be in the past."
    if start_hour < STUDY_FIRST_START_HOUR or start_hour > STUDY_LAST_START_HOUR:
        return False, f"Start time must be between {STUDY_FIRST_START_HOUR}:00 and {STUDY_LAST_START_HOUR}:00 (1-hour slots until 7:00 PM close)."

    if num_attendees < 1:
        return False, "Number of attendees must be at least 1."
    if num_attendees > room.capacity:
        return False, f"This room allows at most {room.capacity} attendee(s)."

    if _count_confirmed_room_reservations(lib, b.borrower_id) >= MAX_ACTIVE_STUDY_ROOM_RESERVATIONS:
        return False, f"You already have {MAX_ACTIVE_STUDY_ROOM_RESERVATIONS} active study room reservations."

    if find_room_reservation_conflict(lib, room_id, booking_date, start_hour):
        return False, "That time slot is no longer available."

    rid = f"RR-{lib._next_room_res_num:05d}"
    lib._next_room_res_num += 1
    code = secrets.token_hex(3).upper()
    lib.room_reservations.append(
        RoomReservation(
            reservation_id=rid,
            room_id=room_id,
            borrower_id=b.borrower_id,
            booking_date=booking_date,
            start_hour=start_hour,
            state=RoomReservationState.CONFIRMED,
            num_attendees=num_attendees,
            confirm_code=code,
        )
    )
    return True, f"Confirmed {room.name} on {booking_date.isoformat()} ({format_study_slot_label(start_hour)}). Confirmation code: {code}."


def cancel_study_room_reservation(lib: Library, card_barcode: str, reservation_id: str) -> tuple[bool, str]:
    b = find_borrower_by_card(lib, card_barcode)
    if not b:
        return False, "Borrower not found for that card."
    reservation_id = reservation_id.strip()
    r = next((x for x in lib.room_reservations if x.reservation_id == reservation_id), None)
    if not r or r.borrower_id != b.borrower_id:
        return False, "Reservation not found on your account."
    if r.state != RoomReservationState.CONFIRMED:
        return False, "Only active reservations can be cancelled."
    r.state = RoomReservationState.CANCELLED
    return True, f"Reservation {reservation_id} cancelled."


def modify_study_room_reservation(
    lib: Library,
    card_barcode: str,
    reservation_id: str,
    new_room_id: str,
    new_booking_date: date,
    new_start_hour: int,
    new_num_attendees: int,
) -> tuple[bool, str]:
    b = find_borrower_by_card(lib, card_barcode)
    if not b:
        return False, "Borrower not found for that card."
    reservation_id = reservation_id.strip()
    r = next((x for x in lib.room_reservations if x.reservation_id == reservation_id), None)
    if not r or r.borrower_id != b.borrower_id:
        return False, "Reservation not found on your account."
    if r.state != RoomReservationState.CONFIRMED:
        return False, "Only active reservations can be modified."

    new_room_id = new_room_id.strip()
    room = lib.study_rooms.get(new_room_id)
    if not room:
        return False, "Study room not found."
    if not room.is_active:
        return False, "That room is not available for booking (out of service)."

    if new_booking_date < lib.simulation_date:
        return False, "Booking date cannot be in the past."
    if new_start_hour < STUDY_FIRST_START_HOUR or new_start_hour > STUDY_LAST_START_HOUR:
        return False, f"Start time must be between {STUDY_FIRST_START_HOUR}:00 and {STUDY_LAST_START_HOUR}:00."

    if new_num_attendees < 1:
        return False, "Number of attendees must be at least 1."
    if new_num_attendees > room.capacity:
        return False, f"This room allows at most {room.capacity} attendee(s)."

    if find_room_reservation_conflict(lib, new_room_id, new_booking_date, new_start_hour, exclude_reservation_id=r.reservation_id):
        return False, "That time slot is not available."

    r.room_id = new_room_id
    r.booking_date = new_booking_date
    r.start_hour = new_start_hour
    r.num_attendees = new_num_attendees
    return True, f"Reservation {reservation_id} updated to {room.name} on {new_booking_date.isoformat()} ({format_study_slot_label(new_start_hour)})."


def set_study_room_active(lib: Library, room_id: str, is_active: bool) -> tuple[bool, str]:
    room_id = room_id.strip()
    room = lib.study_rooms.get(room_id)
    if not room:
        return False, "Study room not found."
    room.is_active = is_active
    cancelled = 0
    if not is_active:
        for r in lib.room_reservations:
            if r.room_id == room_id and r.state == RoomReservationState.CONFIRMED:
                # Track maintenance-driven cancellations so borrower portals can notify affected patrons.
                r.state = RoomReservationState.OUT_OF_SERVICE
                cancelled += 1
        msg = f"{room.name} is now out of service for bookings."
        if cancelled:
            msg += f" Cancelled {cancelled} active reservation(s)."
        return True, msg
    return True, f"{room.name} is now available for bookings."


def mark_room_reservation_out_of_service(lib: Library, reservation_id: str) -> tuple[bool, str]:
    reservation_id = reservation_id.strip()
    r = next((x for x in lib.room_reservations if x.reservation_id == reservation_id), None)
    if not r:
        return False, "Room reservation not found."
    if r.state != RoomReservationState.CONFIRMED:
        return False, "Only confirmed reservations can be marked out of service."
    r.state = RoomReservationState.OUT_OF_SERVICE
    return True, f"Reservation {reservation_id} marked out of service."


def staff_room_reservations_list(lib: Library) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for r in sorted(lib.room_reservations, key=lambda x: (x.booking_date, x.start_hour, x.reservation_id)):
        room = lib.study_rooms.get(r.room_id)
        br = lib.borrowers.get(r.borrower_id)
        rows.append(
            {
                "reservation_id": r.reservation_id,
                "state": r.state,
                "room_id": r.room_id,
                "room_name": room.name if room else r.room_id,
                "booking_date": r.booking_date.isoformat(),
                "start_hour": r.start_hour,
                "slot_label": format_study_slot_label(r.start_hour),
                "borrower_id": r.borrower_id,
                "borrower_name": br.name if br else r.borrower_id,
                "num_attendees": r.num_attendees,
                "confirm_code": r.confirm_code,
            }
        )
    return rows


# --- Reports & queries ---


def report_overdue(lib: Library) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    overdue_borrowers = {
        c.checked_out_by
        for c in lib.copies.values()
        if c.status == CopyStatus.OVERDUE and c.checked_out_by
    }
    for bid in sorted(overdue_borrowers):
        b = lib.borrowers.get(bid)
        if not b:
            continue
        entry: dict[str, Any] = {
            "borrower_name": b.name,
            "borrower_type": b.borrower_type,
            "card_barcode": b.card_barcode,
            "overdue_copies": [],
            "reserved_books": [],
        }
        for c in lib.copies.values():
            if c.status != CopyStatus.OVERDUE or c.checked_out_by != bid:
                continue
            book = lib.books.get(c.isbn)
            entry["overdue_copies"].append(
                {
                    "title": book.title if book else "",
                    "author": book.author if book else "",
                    "barcode": c.barcode,
                    "date_checked_out": c.date_checked_out.isoformat() if c.date_checked_out else "",
                    "amount_owed": c.amount_owed,
                }
            )
        for r in lib.reservations:
            if r.borrower_id != bid:
                continue
            book = lib.books.get(r.isbn)
            entry["reserved_books"].append(
                {
                    "title": book.title if book else "",
                    "author": book.author if book else "",
                    "isbn": r.isbn,
                }
            )
        rows.append(entry)
    return rows


def report_inventory(lib: Library) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for isbn in sorted(lib.books.keys()):
        book = lib.books[isbn]
        reservers = []
        for r in _reservations_for_book(lib, isbn):
            br = lib.borrowers.get(r.borrower_id)
            reservers.append(
                {
                    "name": br.name if br else r.borrower_id,
                    "phone": br.phone if br else "",
                    "date_reserved": r.date_reserved.isoformat(),
                }
            )
        copy_rows = []
        for c in sorted(
            (c for c in lib.copies.values() if c.isbn == isbn),
            key=lambda x: x.barcode,
        ):
            cr: dict[str, Any] = {"barcode": c.barcode, "status": c.status}
            if c.status in (CopyStatus.CHECKED_OUT, CopyStatus.OVERDUE):
                br = lib.borrowers.get(c.checked_out_by or "")
                cr["date_checked_out"] = c.date_checked_out.isoformat() if c.date_checked_out else ""
                cr["date_due_back"] = c.date_due_back.isoformat() if c.date_due_back else ""
                cr["amount_owed"] = c.amount_owed
                cr["borrower_name"] = br.name if br else ""
                cr["borrower_type"] = br.borrower_type if br else ""
                cr["card_barcode"] = br.card_barcode if br else ""
            elif c.status == CopyStatus.ON_HOLD:
                br = lib.borrowers.get(c.hold_borrower_id or "")
                cr["hold_for"] = br.name if br else c.hold_borrower_id
                cr["hold_days_remaining"] = c.hold_days_remaining
            copy_rows.append(cr)
        out.append(
            {
                "title": book.title,
                "author": book.author,
                "book_type": book.book_type,
                "isbn": book.isbn,
                "catalog_number": book.catalog_number or "—",
                "edition": book.edition,
                "reservers": reservers,
                "copies": copy_rows,
            }
        )
    return out


def query_borrower(lib: Library, card_barcode: str) -> Optional[dict[str, Any]]:
    b = find_borrower_by_card(lib, card_barcode.strip())
    if not b:
        return None
    checked = []
    for c in lib.copies.values():
        if c.checked_out_by != b.borrower_id:
            continue
        if c.status not in (CopyStatus.CHECKED_OUT, CopyStatus.OVERDUE):
            continue
        book = lib.books.get(c.isbn)
        checked.append(
            {
                "barcode": c.barcode,
                "status": c.status,
                "title": book.title if book else "",
                "author": book.author if book else "",
                "date_checked_out": c.date_checked_out.isoformat() if c.date_checked_out else "",
                "date_due_back": c.date_due_back.isoformat() if c.date_due_back else "",
                "amount_owed": c.amount_owed,
            }
        )
    reserved = []
    for r in lib.reservations:
        if r.borrower_id != b.borrower_id:
            continue
        book = lib.books.get(r.isbn)
        reserved.append(
            {
                "isbn": r.isbn,
                "title": book.title if book else "",
                "author": book.author if book else "",
                "date_reserved": r.date_reserved.isoformat(),
                "reservation_id": r.reservation_id,
            }
        )
    room_rows = borrower_upcoming_room_reservations(lib, b.borrower_id)
    room_oos = borrower_out_of_service_room_notifications(lib, b.borrower_id)
    return {
        "borrower_id": b.borrower_id,
        "name": b.name,
        "phone": b.phone,
        "borrower_type": b.borrower_type,
        "fine_balance": b.fine_balance,
        "card_barcode": b.card_barcode,
        "card_expiration": b.card_expiration.isoformat(),
        "card_expired": lib.simulation_date > b.card_expiration,
        "checked_out": checked,
        "reservations": reserved,
        "room_reservations": room_rows,
        "room_oos_notifications": room_oos,
    }


def query_copy(lib: Library, barcode: str) -> Optional[dict[str, Any]]:
    c = lib.copies.get(barcode.strip())
    if not c:
        return None
    book = lib.books.get(c.isbn)
    row: dict[str, Any] = {
        "barcode": c.barcode,
        "isbn": c.isbn,
        "status": c.status,
        "title": book.title if book else "",
        "author": book.author if book else "",
        "publisher": book.publisher if book else "",
        "edition": book.edition if book else "",
        "book_type": book.book_type if book else "",
        "is_reference": book.is_reference if book else False,
    }
    if c.status in (CopyStatus.CHECKED_OUT, CopyStatus.OVERDUE):
        br = lib.borrowers.get(c.checked_out_by or "")
        row["date_checked_out"] = c.date_checked_out.isoformat() if c.date_checked_out else ""
        row["date_due_back"] = c.date_due_back.isoformat() if c.date_due_back else ""
        row["amount_owed"] = c.amount_owed
        row["borrower_name"] = br.name if br else ""
        row["borrower_type"] = br.borrower_type if br else ""
        row["card_barcode"] = br.card_barcode if br else ""
    if c.status == CopyStatus.ON_HOLD:
        br = lib.borrowers.get(c.hold_borrower_id or "")
        row["hold_for_name"] = br.name if br else ""
        row["hold_borrower_id"] = c.hold_borrower_id
        row["hold_days_remaining"] = c.hold_days_remaining
    return row


def query_book(lib: Library, isbn: str) -> Optional[dict[str, Any]]:
    book = lib.books.get(isbn.strip())
    if not book:
        return None
    copies = [query_copy(lib, c.barcode) for c in lib.copies.values() if c.isbn == book.isbn]
    copies.sort(key=lambda x: x["barcode"])
    res = _reservations_for_book(lib, book.isbn)
    return {
        "isbn": book.isbn,
        "title": book.title,
        "author": book.author,
        "publisher": book.publisher,
        "edition": book.edition,
        "book_type": book.book_type,
        "catalog_number": book.catalog_number,
        "is_reference": book.is_reference,
        "is_hardcover": book.is_hardcover,
        "reservation_count": len(res),
        "copies": copies,
    }

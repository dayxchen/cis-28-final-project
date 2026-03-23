from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


class RoomReservationState:
    """Lifecycle for study-room bookings (see event state diagram)."""

    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class CopyStatus:
    ON_SHELF = "ON_SHELF"
    CHECKED_OUT = "CHECKED_OUT"
    OVERDUE = "OVERDUE"
    ON_HOLD = "ON_HOLD"
    LOST = "LOST"
    DAMAGED = "DAMAGED"


@dataclass
class Book:
    isbn: str
    title: str
    publisher: str
    author: str
    edition: int
    book_type: str  # Fiction | NonFiction
    catalog_number: str
    is_reference: bool
    is_hardcover: bool


@dataclass
class Borrower:
    """Borrower with embedded library card (LibraryCard in the class diagram)."""

    borrower_id: str
    name: str
    phone: str
    borrower_type: str  # Student | Teacher
    fine_balance: float
    card_barcode: str
    card_expiration: date


@dataclass
class Copy:
    barcode: str
    isbn: str
    status: str
    checked_out_by: Optional[str] = None
    date_checked_out: Optional[date] = None
    date_due_back: Optional[date] = None
    amount_owed: float = 0.0
    hold_borrower_id: Optional[str] = None
    hold_days_remaining: int = 0


@dataclass
class Reservation:
    reservation_id: str
    borrower_id: str
    isbn: str
    date_reserved: date


@dataclass
class StudyRoom:
    """Scheduled resource: study room (1-hour slots, 9am–7pm)."""

    room_id: str
    name: str
    capacity: int
    location: str
    equipment: str
    is_active: bool


@dataclass
class RoomReservation:
    """Scheduled reservation for a study room (time window stored as date + start hour)."""

    reservation_id: str
    room_id: str
    borrower_id: str
    booking_date: date
    start_hour: int  # 9–18 inclusive; reservation runs start_hour:00–(start_hour+1):00, closing at 19:00
    state: str
    num_attendees: int
    confirm_code: str


@dataclass
class Library:
    """
    Top-level aggregate: owns books, copies, borrowers (Student/Teacher),
    and reservation queues keyed by ISBN.
    """

    books: dict[str, Book] = field(default_factory=dict)
    borrowers: dict[str, Borrower] = field(default_factory=dict)
    copies: dict[str, Copy] = field(default_factory=dict)
    reservations: list[Reservation] = field(default_factory=list)
    study_rooms: dict[str, StudyRoom] = field(default_factory=dict)
    room_reservations: list[RoomReservation] = field(default_factory=list)
    simulation_date: date = field(default_factory=date.today)
    _next_borrower_num: int = 101
    _next_copy_num: int = 2001
    _next_card_num: int = 1
    _next_res_num: int = 1
    _next_room_res_num: int = 1

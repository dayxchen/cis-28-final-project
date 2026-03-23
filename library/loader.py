from __future__ import annotations

import csv
import re
from datetime import date, datetime
from pathlib import Path

from .models import (
    Book,
    Borrower,
    Copy,
    CopyStatus,
    Library,
    Reservation,
    RoomReservation,
    StudyRoom,
)


def _parse_date(s: str) -> date:
    s = (s or "").strip()
    if not s:
        raise ValueError("empty date")
    return datetime.strptime(s, "%Y-%m-%d").date()


def _parse_float(s: str) -> float:
    s = (s or "").strip()
    return float(s) if s else 0.0


def _parse_bool(s: str) -> bool:
    return (s or "").strip().lower() in ("true", "1", "yes")


def _parse_int(s: str) -> int:
    return int((s or "0").strip() or 0)


def load_library_from_csv(data_dir: Path) -> Library:
    books: dict[str, Book] = {}
    borrowers: dict[str, Borrower] = {}
    copies: dict[str, Copy] = {}
    reservations: list[Reservation] = []

    with open(data_dir / "books.csv", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            isbn = row["isbn"].strip()
            books[isbn] = Book(
                isbn=isbn,
                title=row["title"].strip(),
                publisher=row["publisher"].strip(),
                author=row["author"].strip(),
                edition=_parse_int(row["edition"]),
                book_type=row["book_type"].strip(),
                catalog_number=(row.get("catalog_number") or "").strip(),
                is_reference=_parse_bool(row["is_reference"]),
                is_hardcover=_parse_bool(row["is_hardcover"]),
            )

    max_borrower = 0
    max_card = 0
    with open(data_dir / "borrowers.csv", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            bid = row["borrower_id"].strip()
            m = re.match(r"B-(\d+)", bid)
            if m:
                max_borrower = max(max_borrower, int(m.group(1)))
            cb = row["card_barcode"].strip()
            mc = re.match(r"CARD-(\d+)", cb)
            if mc:
                max_card = max(max_card, int(mc.group(1)))
            borrowers[bid] = Borrower(
                borrower_id=bid,
                name=row["name"].strip(),
                phone=row["phone"].strip(),
                borrower_type=row["borrower_type"].strip(),
                fine_balance=_parse_float(row["fine_balance"]),
                card_barcode=cb,
                card_expiration=_parse_date(row["card_expiration"]),
            )

    max_copy_n = 0
    with open(data_dir / "copies.csv", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            bc = row["barcode"].strip()
            m = re.match(r"COPY-(\d+)", bc)
            if m:
                max_copy_n = max(max_copy_n, int(m.group(1)))
            hold_rem = _parse_int(row.get("hold_days_remaining") or "0")
            copies[bc] = Copy(
                barcode=bc,
                isbn=row["isbn"].strip(),
                status=(row["status"] or "").strip() or CopyStatus.ON_SHELF,
                checked_out_by=(row.get("checked_out_by") or "").strip() or None,
                date_checked_out=_parse_date(row["date_checked_out"])
                if (row.get("date_checked_out") or "").strip()
                else None,
                date_due_back=_parse_date(row["date_due_back"])
                if (row.get("date_due_back") or "").strip()
                else None,
                amount_owed=_parse_float(row.get("amount_owed") or ""),
                hold_borrower_id=(row.get("hold_borrower_id") or "").strip() or None,
                hold_days_remaining=hold_rem,
            )

    max_res = 0
    with open(data_dir / "reservations.csv", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            rid = row["reservation_id"].strip()
            m = re.match(r"R-(\d+)", rid)
            if m:
                max_res = max(max_res, int(m.group(1)))
            reservations.append(
                Reservation(
                    reservation_id=rid,
                    borrower_id=row["borrower_id"].strip(),
                    isbn=row["isbn"].strip(),
                    date_reserved=_parse_date(row["date_reserved"]),
                )
            )

    study_rooms: dict[str, StudyRoom] = {}
    with open(data_dir / "study_rooms.csv", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            rid = row["room_id"].strip()
            study_rooms[rid] = StudyRoom(
                room_id=rid,
                name=row["name"].strip(),
                capacity=_parse_int(row["capacity"]),
                location=row["location"].strip(),
                equipment=(row.get("equipment") or "").strip(),
                is_active=_parse_bool(row.get("is_active") or "true"),
            )

    room_reservations: list[RoomReservation] = []
    max_rr = 0
    rr_path = data_dir / "room_reservations.csv"
    if rr_path.exists():
        with open(rr_path, newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                if not (row.get("reservation_id") or "").strip():
                    continue
                rid = row["reservation_id"].strip()
                m = re.match(r"RR-(\d+)", rid)
                if m:
                    max_rr = max(max_rr, int(m.group(1)))
                room_reservations.append(
                    RoomReservation(
                        reservation_id=rid,
                        room_id=row["room_id"].strip(),
                        borrower_id=row["borrower_id"].strip(),
                        booking_date=_parse_date(row["booking_date"]),
                        start_hour=_parse_int(row["start_hour"]),
                        state=(row.get("state") or "").strip() or "CONFIRMED",
                        num_attendees=max(1, _parse_int(row.get("num_attendees") or "1")),
                        confirm_code=(row.get("confirm_code") or "").strip() or "—",
                    )
                )

    lib = Library(
        books=books,
        borrowers=borrowers,
        copies=copies,
        reservations=reservations,
        study_rooms=study_rooms,
        room_reservations=room_reservations,
        simulation_date=date(2026, 3, 20),
        _next_borrower_num=max_borrower + 1,
        _next_copy_num=max_copy_n + 1,
        _next_card_num=max_card + 1,
        _next_res_num=max_res + 1,
        _next_room_res_num=max_rr + 1,
    )
    return lib

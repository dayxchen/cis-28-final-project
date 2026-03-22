#!/usr/bin/env python3
"""One-off: replace placeholder borrower/book/author strings with realistic names."""
from __future__ import annotations

import csv
import hashlib
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

FIRST = (
    "James", "Maria", "Chen", "Jordan", "Priya", "Diego", "Aisha", "Noah", "Yuki", "Omar",
    "Elena", "Marcus", "Fatima", "Lucas", "Hannah", "Raj", "Sofia", "Ethan", "Mei", "Kwame",
    "Nina", "Leo", "Amara", "Ben", "Zara", "Theo", "Rosa", "Samir", "Clara", "Ian",
    "Keiko", "Andre", "Lila", "Viktor", "Tessa", "Hugo", "Anika", "Felix", "Mira", "Dante",
    "Greta", "Ravi", "Ines", "Jonah", "Sana", "Mateo", "Yara", "Elliot", "Nadia", "Owen",
    "Camila", "Arjun", "Iris", "Silas", "Lena", "Emilio", "Kira", "Adrian", "Maya", "Finn",
    "Bianca", "Kai", "Naomi", "Julian", "Zoe", "Malik", "Paola", "Reid", "Sienna", "Tariq",
    "Vera", "Nolan", "Esme", "Bruno", "Alma", "Caleb", "Dina", "Gavin", "Freya", "Isaac",
    "Jada", "Rowan", "Leila", "Tomas", "Willa", "Ezra", "Noor", "Felipe", "Skye", "Axel",
    "Mina", "Rhys", "Talia", "Oscar", "Uma", "Quinn", "Ren", "Sage", "Wes", "Yael",
)

LAST = (
    "Nguyen", "Patel", "Hernandez", "Kim", "Okafor", "Silva", "Cohen", "Murphy", "Santos", "Park",
    "Ibrahim", "Foster", "Okonkwo", "Berg", "Reyes", "Chang", "Nakamura", "Carvalho", "Walsh", "Singh",
    "Lindstrom", "Morales", "Haddad", "Perez", "Olsen", "Tanaka", "Kowalski", "Rossi", "Abbott", "Dubois",
    "Khan", "Schmidt", "Vargas", "Yamamoto", "Novak", "Alvarez", "Bakker", "Costa", "Ellis", "Farah",
    "Garcia", "Hansen", "Iyer", "Jensen", "Kaur", "Lopez", "Mensah", "Nielsen", "Ortega", "Petrov",
    "Quintero", "Rahman", "Sato", "Torres", "Uzun", "Vega", "Weiss", "Xu", "Yilmaz", "Zhang",
    "Ahmed", "Brown", "Cruz", "Diaz", "Evans", "Flores", "Green", "Harris", "Ito", "Jackson",
    "Kelly", "Liu", "Martin", "Nash", "Owens", "Price", "Quinn", "Rivera", "Stone", "Turner",
    "Underwood", "Vaughn", "White", "Young", "Zhou", "Adams", "Brooks", "Campbell", "Davis", "Edwards",
)

FICTION_ADJS = (
    "Silent", "Broken", "Last", "Golden", "Winter", "Paper", "Glass", "Hidden", "Blue", "Wild",
    "Forgotten", "Electric", "Midnight", "Stone", "River", "Crimson", "Distant", "Small", "Bright", "Heavy",
    "Pale", "Dark", "Open", "Closed", "Second", "First", "Lost", "Found", "Thin", "Thick",
)

FICTION_NOUNS = (
    "Garden", "Harbor", "Clock", "Bridge", "Song", "House", "Road", "Star", "Wave", "Door",
    "Letter", "Room", "Forest", "City", "Train", "Island", "Window", "Mirror", "Field", "Tower",
    "Market", "Station", "River", "Hill", "Coast", "Library", "Theater", "Cafe", "Alley", "Square",
)

NONFIC_TOPICS = (
    "Calculus", "Organic Chemistry", "U.S. History", "World Mythology", "Data Structures",
    "Cell Biology", "Macroeconomics", "Environmental Science", "Linear Algebra", "Psychology",
    "Sociology", "Art History", "Music Theory", "Statistics", "Ethics", "Physics", "Astronomy",
    "Linguistics", "Anthropology", "Political Science", "Neuroscience", "Geology", "Ethnography",
    "Research Methods", "Public Health", "Urban Planning", "Climate Policy", "Machine Learning",
    "Human Anatomy", "Discrete Mathematics", "Modern Poetry", "Film Studies", "Game Design",
)


def person_name(key: str) -> str:
    h = int(hashlib.sha256(key.encode()).hexdigest(), 16)
    f = FIRST[h % len(FIRST)]
    l = LAST[(h // len(FIRST)) % len(LAST)]
    return f"{f} {l}"


def fiction_title(fi: int) -> str:
    """fi = index among Fiction rows; (adj, noun) from grid is unique for each fi < 900."""
    a = FICTION_ADJS[fi % len(FICTION_ADJS)]
    n = FICTION_NOUNS[(fi // len(FICTION_ADJS)) % len(FICTION_NOUNS)]
    if fi % 2 == 0:
        return f"The {a} {n}"
    return f"{a} {n}s"


def nonfiction_title(ni: int) -> str:
    base = NONFIC_TOPICS[ni % len(NONFIC_TOPICS)]
    suffixes = (
        " — A Concise Introduction",
        ": Core Concepts",
        " (Student Edition)",
        ": Practice and Theory",
        " — Essential Readings",
        ": Laboratory Companion",
    )
    suf = suffixes[(ni // len(NONFIC_TOPICS)) % len(suffixes)]
    return f"{base}{suf}, Vol. {ni + 1}"


def main() -> None:
    # --- books ---
    book_path = DATA / "books.csv"
    rows: list[dict[str, str]] = []
    with book_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        assert fieldnames
        fi = ni = 0
        for row in reader:
            old_author = row["author"].strip()
            row["author"] = person_name(f"author:{old_author}")
            bt = row.get("book_type", "").strip()
            if bt == "Fiction":
                row["title"] = fiction_title(fi)
                fi += 1
            else:
                row["title"] = nonfiction_title(ni)
                ni += 1
            rows.append(row)

    with book_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        w.writerows(rows)

    # --- borrowers ---
    bor_path = DATA / "borrowers.csv"
    brows: list[dict[str, str]] = []
    with bor_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        bfields = reader.fieldnames
        assert bfields
        for row in reader:
            bid = row["borrower_id"].strip()
            row["name"] = person_name(f"borrower:{bid}")
            brows.append(row)

    with bor_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=bfields, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        w.writerows(brows)

    print(f"Updated {len(rows)} books, {len(brows)} borrowers.")


if __name__ == "__main__":
    main()

"""
The sensitivity scan of design 5.11, run on GitHub's text before a pull commits it, every title, body and comment.

A fixed set of patterns, money amounts, card and account numbers, email addresses and phone numbers, street
addresses, and whole words such as invoice, salary, lawsuit, diagnosis and tax, "contract" counted only beside a money
amount or a party's name. Beside them, a list of private words the owner keeps outside every repo, whose hit is shown
as "a private word" and never the word. A hit names its pattern and its count alone, never the text it matched, so a
scan's output can be read and recorded without carrying what it found.

An issue the owner allows is recorded in the config with the digest of the text it allowed and the policy version,
so a changed title, body or comment, a new comment or a new policy needs a new word.
"""

from __future__ import annotations

# standard imports
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# third party imports
from kdf_tickets.common import Refusal, value_digest

# module constants
# raised whenever a pattern changes, so every allowance made under an older one asks again
POLICY  = 1
PRIVATE = "a private word"
# an amount after a currency sign, of two digits or more so a shell's $1 is not one, and an amount before a currency
# named in words
SIGNED   = r"[$€£]\s?\d{1,3}(?:,\d{3})+(?:\.\d{2})?|[$€£]\s?\d+\.\d{2}\b|[$€£]\s?\d{2,}\b"
NAMED    = r"\b\d[\d,]*(?:\.\d{2})?\s?(?:USD|EUR|GBP|dollars|euros|pounds)\b"
MONEY    = re.compile("|".join((SIGNED, NAMED)), re.IGNORECASE)
CARD     = re.compile(r"(?<![\d.])(?:\d[ -]?){12,18}\d(?![\d.])")
IBAN     = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")
ACCOUNT  = re.compile(r"\b(?:account|acct|routing)\s*(?:no\.?|number|num|#)\s*:?\s*\d[\d -]{3,}", re.IGNORECASE)
EMAIL    = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE    = re.compile(r"(?<![\w.-])(?:\+\d{1,3}[ .-]?)?(?:\(\d{3}\)\s?|\d{3}[ .-])\d{3}[ .-]\d{4}(?![\w-])")
STREET   = re.compile(
    r"\b\d{1,5}\s+(?:[A-Z][a-z]+\s+){1,3}(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|"
    r"Way|Place|Pl|Terrace|Parkway|Pkwy)\b"
)
WORDS    = re.compile(
    r"\b(?:invoices?|salary|salaries|payroll|lawsuits?|litigation|diagnos[ie]s|tax|taxes|ssn|social security)\b",
    re.IGNORECASE,
)
CONTRACT = re.compile(r"\bcontracts?\b", re.IGNORECASE)
PARTY    = re.compile(r"\bcontracts?\s+(?:with|between)\s+[A-Z][\w&.-]*", re.IGNORECASE)
# addresses that name no person, a documentation domain or a no reply sender
SAFE_MAIL = re.compile(r"(?:no-?reply|@example\.(?:com|org|net)$|@users\.noreply\.github\.com$)", re.IGNORECASE)
NEAR      = 80


@dataclass
class Hit:
    """
    One issue the scan flags, where in it, and each pattern's count, never the text matched.
    """
    number: int
    ident:  str
    digest: str
    counts: dict[str, Counter] = field(default_factory = dict)


    def line(self) -> str:
        """
        Write the hit as the scan prints it.

        Returns:
            str: the issue, then each place and its patterns with their counts
        """
        places = []
        for place, counts in self.counts.items():
            patterns = ", ".join(f"{name} ({count})" for name, count in sorted(counts.items()))
            places.append(f"{place}, {patterns}")
        return f"#{self.number} {self.ident}: " + "; ".join(places)


def luhn(digits: str) -> bool:
    """
    Say whether a run of digits passes the card number check.

    Args:
        digits: the digits alone

    Returns:
        bool: True for a number the Luhn check takes
    """
    total = 0
    for index, digit in enumerate(reversed(digits)):
        value = int(digit) * (2 if index % 2 else 1)
        total += value - 9 if value > 9 else value
    return total % 10 == 0


def iban_ok(text: str) -> bool:
    """
    Say whether a candidate passes the IBAN check of ISO 13616.

    Args:
        text: the candidate

    Returns:
        bool: True for a number whose check digits hold
    """
    plain   = text.replace(" ", "")
    moved   = plain[4:] + plain[:4]
    numeric = "".join(str(int(char, 36)) for char in moved)
    return 15 <= len(plain) <= 34 and int(numeric) % 97 == 1


def private_words(path: Path | None) -> re.Pattern[str] | None:
    """
    Read the owner's list of private words, one a line, a line starting with # a note.

    Args:
        path: the list, kept outside every repo, or None

    Returns:
        re.Pattern[str] | None: a pattern matching any of them as a whole word in any case, None for no list

    Raises:
        Refusal: for a list that cannot be read
    """
    if path is None:
        return None
    try:
        lines = path.read_text(encoding = "utf-8").splitlines()
    except OSError as error:
        raise Refusal(f"the private words list cannot be read, {error}") from None
    words = [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]
    if not words:
        return None
    return re.compile(r"\b(?:" + "|".join(re.escape(word) for word in words) + r")\b", re.IGNORECASE)


def count(text: str, private: re.Pattern[str] | None = None) -> Counter:
    """
    Count each pattern's hits in one text.

    Args:
        text: a title, a body or a comment
        private: the owner's private words, if any

    Returns:
        Counter: each pattern's name and its hits, empty for a clean text
    """
    found: Counter = Counter()
    money = list(MONEY.finditer(text))
    found["a money amount"] += len(money)
    found["a card number"]  += sum(1 for match in CARD.finditer(text) if luhn(re.sub(r"\D", "", match.group())))
    found["an account number"] += sum(1 for match in IBAN.finditer(text) if iban_ok(match.group()))
    found["an account number"] += len(ACCOUNT.findall(text))
    found["an email address"]  += sum(1 for match in EMAIL.finditer(text) if not SAFE_MAIL.search(match.group()))
    found["a phone number"]    += len(PHONE.findall(text))
    found["a street address"]  += len(STREET.findall(text))
    for match in WORDS.finditer(text):
        found[f"the word {match.group().lower()}"] += 1
    for match in CONTRACT.finditer(text):
        beside = any(abs(amount.start() - match.start()) <= NEAR for amount in money)
        if beside or PARTY.match(text, match.start()):
            found["the word contract"] += 1
    if private is not None:
        found[PRIVATE] += len(private.findall(text))
    return Counter({name: hits for name, hits in found.items() if hits})


def subject_digest(title: str, body: str, comments: list[str]) -> str:
    """
    Digest the text an allowance is bound to, the title, the body and every comment in order.

    Args:
        title: the issue's title
        body: its body
        comments: its comments' bodies

    Returns:
        str: the digest
    """
    return value_digest([title, body, comments])


def scan_issue(
    number: int,
    ident: str,
    title: str,
    body: str,
    comments: list[str],
    private: re.Pattern[str] | None = None,
) -> Hit | None:
    """
    Scan one issue's title, body and comments.

    Args:
        number: the issue's number
        ident: its ticket's id, as a pull names it
        title: its title
        body: its body
        comments: its comments' bodies, in order
        private: the owner's private words, if any

    Returns:
        Hit | None: the hit, None for a clean issue
    """
    hit = Hit(number = number, ident = ident, digest = subject_digest(title, body, comments))
    for place, text in (
        ("title", title),
        ("body", body),
        *((f"comment {index}", text) for index, text in enumerate( comments, 1)),
    ):
        found = count(text, private)
        if found:
            hit.counts[place] = found
    return hit if hit.counts else None


def allowed(hit: Hit, allow: dict) -> bool:
    """
    Say whether the owner allowed a hit, its allowance bound to this text and this policy.

    Args:
        hit: the hit
        allow: the config's allowances by ticket id

    Returns:
        bool: True when the allowance's digest and policy are the hit's
    """
    entry = allow.get(hit.ident)
    return isinstance(entry, dict) and entry.get("digest") == hit.digest and entry.get("policy") == POLICY

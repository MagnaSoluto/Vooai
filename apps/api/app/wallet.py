"""Carteira em saldos + ledger (débito/crédito/estorno) — Postgres ou SQLite."""

from __future__ import annotations

from dataclasses import dataclass

from .db import backend, connection, init_db
from .pricing import (
    MIN_TOPUP_BRL,
    SALDO_UNIT_BRL,
    brl_equiv_saldos,
    ceil_brl,
    saldos_from_topup_brl,
)


@dataclass
class User:
    id: int
    email: str
    token: str
    balance_saldos: int

    @property
    def balance_brl(self) -> float:
        """Equivalente em R$ (1 saldo = SALDO_UNIT_BRL) — compat API/UI."""
        return brl_equiv_saldos(self.balance_saldos)


class InsufficientFunds(Exception):
    def __init__(self, balance_saldos: int, required_saldos: int):
        self.balance = balance_saldos
        self.required = required_saldos
        self.balance_saldos = balance_saldos
        self.required_saldos = required_saldos
        super().__init__(
            f"Saldo {balance_saldos} < {required_saldos} saldos"
        )


def _read_saldos(row) -> int:
    if row is None:
        return 0
    raw = row.get("balance_saldos") if hasattr(row, "get") else None
    if raw is None:
        try:
            raw = row["balance_saldos"]
        except Exception:
            raw = None
    if raw is not None:
        return int(raw)
    # legado: só balance_brl
    brl = float(row["balance_brl"] or 0)
    return int(brl // SALDO_UNIT_BRL) if brl > 0 else 0


def _user_from_id(conn, user_id: int) -> User:
    row = conn.fetchone(
        """
        SELECT u.id, u.email, u.token, w.balance_brl, w.balance_saldos
        FROM users u JOIN wallets w ON w.user_id = u.id
        WHERE u.id = ?
        """,
        (user_id,),
    )
    if not row:
        raise KeyError(f"user {user_id}")
    return User(
        id=int(row["id"]),
        email=str(row["email"]),
        token=str(row["token"]),
        balance_saldos=_read_saldos(row),
    )


def get_user_by_id(user_id: int) -> User | None:
    init_db()
    with connection() as conn:
        try:
            return _user_from_id(conn, int(user_id))
        except KeyError:
            return None


def get_user_by_legacy_token(token: str) -> User | None:
    """Somente tokens opacos antigos em users.token (migração). Preferir JWT."""
    init_db()
    token = (token or "").strip()
    if not token or token.count(".") == 2:
        return None
    with connection() as conn:
        row = conn.fetchone(
            """
            SELECT u.id, u.email, u.token, w.balance_brl, w.balance_saldos
            FROM users u JOIN wallets w ON w.user_id = u.id
            WHERE u.token = ?
            """,
            (token,),
        )
        if not row:
            return None
        return User(
            id=int(row["id"]),
            email=str(row["email"]),
            token=str(row["token"]),
            balance_saldos=_read_saldos(row),
        )


get_user_by_token = get_user_by_legacy_token


def register_user(email: str) -> User:
    raise ValueError("Use POST /auth/register com senha ou magic-link.")


def login_or_rotate(email: str, *, rotate: bool = False) -> User:
    raise ValueError("Login por e-mail desativado. Use senha ou magic-link.")


def _set_wallet(conn, user_id: int, saldos: int) -> None:
    saldos = max(0, int(saldos))
    brl = brl_equiv_saldos(saldos)
    if backend() == "postgres":
        conn.execute(
            """
            UPDATE wallets
            SET balance_saldos = ?, balance_brl = ?, updated_at = NOW()
            WHERE user_id = ?
            """,
            (saldos, brl, user_id),
        )
    else:
        conn.execute(
            """
            UPDATE wallets
            SET balance_saldos = ?, balance_brl = ?, updated_at = datetime('now')
            WHERE user_id = ?
            """,
            (saldos, brl, user_id),
        )


def topup(user_id: int, amount_brl: float, *, reason: str = "topup_stub") -> User:
    """Stub local: credita saldos após simular taxa Asaas (igual crédito PIX)."""
    init_db()
    amount = ceil_brl(float(amount_brl))
    if amount < MIN_TOPUP_BRL:
        raise ValueError(f"Recarga mínima: R$ {MIN_TOPUP_BRL:.2f}")
    quote = saldos_from_topup_brl(amount)
    saldos = int(quote["saldos"])
    if saldos <= 0:
        raise ValueError(
            f"Após taxa Asaas (R$ {quote['asaas_fee_brl']:.2f}) não há saldos a creditar."
        )
    with connection(immediate=True) as conn:
        bal = _read_saldos(
            conn.fetchone(
                "SELECT balance_brl, balance_saldos FROM wallets WHERE user_id = ?",
                (user_id,),
            )
        )
        new_bal = bal + saldos
        _set_wallet(conn, user_id, new_bal)
        conn.execute(
            """
            INSERT INTO ledger (
              user_id, kind, amount_brl, balance_after,
              amount_saldos, balance_after_saldos, reason
            )
            VALUES (?, 'credit', ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                brl_equiv_saldos(saldos),
                brl_equiv_saldos(new_bal),
                saldos,
                new_bal,
                f"{reason}|fee={quote['asaas_fee_brl']}|net={quote['net_brl']}",
            ),
        )
        return _user_from_id(conn, user_id)


def debit(
    user_id: int,
    saldos: int,
    *,
    reason: str = "search",
    search_ref: str | None = None,
) -> tuple[User, int]:
    init_db()
    amount = int(saldos)
    if amount <= 0:
        raise ValueError("Débito deve ser > 0 saldos")
    with connection(immediate=True) as conn:
        if backend() == "postgres":
            row_bal = conn.fetchone(
                "SELECT balance_brl, balance_saldos FROM wallets WHERE user_id = ? FOR UPDATE",
                (user_id,),
            )
        else:
            row_bal = conn.fetchone(
                "SELECT balance_brl, balance_saldos FROM wallets WHERE user_id = ?",
                (user_id,),
            )
        if not row_bal:
            raise KeyError(f"wallet {user_id}")
        bal = _read_saldos(row_bal)
        if bal < amount:
            raise InsufficientFunds(bal, amount)
        new_bal = bal - amount
        _set_wallet(conn, user_id, new_bal)
        if backend() == "postgres":
            row = conn.fetchone(
                """
                INSERT INTO ledger (
                  user_id, kind, amount_brl, balance_after,
                  amount_saldos, balance_after_saldos, reason, search_ref
                )
                VALUES (?, 'debit', ?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                (
                    user_id,
                    brl_equiv_saldos(amount),
                    brl_equiv_saldos(new_bal),
                    amount,
                    new_bal,
                    reason,
                    search_ref,
                ),
            )
            ledger_id = int(row["id"])
        else:
            cur = conn.execute(
                """
                INSERT INTO ledger (
                  user_id, kind, amount_brl, balance_after,
                  amount_saldos, balance_after_saldos, reason, search_ref
                )
                VALUES (?, 'debit', ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    brl_equiv_saldos(amount),
                    brl_equiv_saldos(new_bal),
                    amount,
                    new_bal,
                    reason,
                    search_ref,
                ),
            )
            ledger_id = int(cur.lastrowid)
        return _user_from_id(conn, user_id), ledger_id


def refund(ledger_id: int, *, reason: str = "refund") -> User | None:
    init_db()
    with connection(immediate=True) as conn:
        row = conn.fetchone("SELECT * FROM ledger WHERE id = ?", (ledger_id,))
        if not row or row["kind"] != "debit":
            return None
        dup = conn.fetchone(
            "SELECT id FROM ledger WHERE kind = 'refund' AND search_ref = ?",
            (f"refund_of:{ledger_id}",),
        )
        if dup:
            return _user_from_id(conn, int(row["user_id"]))
        uid = int(row["user_id"])
        amount_saldos = row.get("amount_saldos") if hasattr(row, "get") else None
        try:
            if amount_saldos is None:
                amount_saldos = row["amount_saldos"]
        except Exception:
            amount_saldos = None
        if amount_saldos is None:
            amount_saldos = int(round(float(row["amount_brl"]) / SALDO_UNIT_BRL))
        else:
            amount_saldos = int(amount_saldos)
        bal = _read_saldos(
            conn.fetchone(
                "SELECT balance_brl, balance_saldos FROM wallets WHERE user_id = ?",
                (uid,),
            )
        )
        new_bal = bal + amount_saldos
        _set_wallet(conn, uid, new_bal)
        conn.execute(
            """
            INSERT INTO ledger (
              user_id, kind, amount_brl, balance_after,
              amount_saldos, balance_after_saldos, reason, search_ref
            )
            VALUES (?, 'refund', ?, ?, ?, ?, ?, ?)
            """,
            (
                uid,
                brl_equiv_saldos(amount_saldos),
                brl_equiv_saldos(new_bal),
                amount_saldos,
                new_bal,
                reason,
                f"refund_of:{ledger_id}",
            ),
        )
        return _user_from_id(conn, uid)


def ledger_for(user_id: int, *, limit: int = 50) -> list[dict]:
    init_db()
    with connection() as conn:
        rows = conn.fetchall(
            """
            SELECT id, kind, amount_brl, balance_after,
                   amount_saldos, balance_after_saldos,
                   reason, search_ref, created_at
            FROM ledger WHERE user_id = ? ORDER BY id DESC LIMIT ?
            """,
            (user_id, limit),
        )
        out = []
        for r in rows:
            amt_s = r.get("amount_saldos") if hasattr(r, "get") else None
            try:
                if amt_s is None:
                    amt_s = r["amount_saldos"]
            except Exception:
                amt_s = None
            if amt_s is None:
                amt_s = int(round(float(r["amount_brl"]) / SALDO_UNIT_BRL))
            bal_s = r.get("balance_after_saldos") if hasattr(r, "get") else None
            try:
                if bal_s is None:
                    bal_s = r["balance_after_saldos"]
            except Exception:
                bal_s = None
            if bal_s is None:
                bal_s = int(round(float(r["balance_after"]) / SALDO_UNIT_BRL))
            out.append(
                {
                    "id": r["id"],
                    "kind": r["kind"],
                    "amount_saldos": int(amt_s),
                    "balance_after_saldos": int(bal_s),
                    "amount_brl": float(r["amount_brl"]),
                    "balance_after": float(r["balance_after"]),
                    "reason": r["reason"],
                    "search_ref": r["search_ref"],
                    "created_at": str(r["created_at"]),
                }
            )
        return out


def save_pending_charge(
    *,
    cobranca_id: str,
    user_id: int,
    amount_brl: float,
    external_reference: str | None,
) -> None:
    init_db()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO pending_charges (cobranca_id, user_id, amount_brl, status, external_reference)
            VALUES (?, ?, ?, 'pendente', ?)
            ON CONFLICT (cobranca_id) DO NOTHING
            """,
            (cobranca_id, user_id, float(amount_brl), external_reference),
        )


def credit_from_charge(
    *,
    cobranca_id: str,
    amount_brl: float | None = None,
    external_reference: str | None = None,
) -> User | None:
    """Credita saldos quando Billing confirma PIX (desconta taxa Asaas). Idempotente."""
    init_db()
    search_ref = f"recharge:{cobranca_id}"
    with connection(immediate=True) as conn:
        already = conn.fetchone(
            "SELECT id FROM ledger WHERE search_ref = ? AND kind = 'credit'",
            (search_ref,),
        )
        if already:
            pend = conn.fetchone(
                "SELECT user_id FROM pending_charges WHERE cobranca_id = ?",
                (cobranca_id,),
            )
            if pend:
                return _user_from_id(conn, int(pend["user_id"]))
            return None

        pend = conn.fetchone(
            "SELECT user_id, amount_brl FROM pending_charges WHERE cobranca_id = ?",
            (cobranca_id,),
        )
        user_id: int | None = None
        credit_brl = float(amount_brl) if amount_brl and amount_brl > 0 else None
        if pend:
            user_id = int(pend["user_id"])
            stored = float(pend["amount_brl"])
            if credit_brl is not None and abs(credit_brl - stored) > 0.01:
                return None
            credit_brl = stored
        elif external_reference:
            parts = external_reference.split(":")
            if len(parts) >= 2 and parts[0] == "vooai":
                try:
                    user_id = int(parts[1])
                except ValueError:
                    user_id = None
        if user_id is None or credit_brl is None or credit_brl <= 0:
            return None

        quote = saldos_from_topup_brl(credit_brl)
        saldos = int(quote["saldos"])
        if saldos <= 0:
            return None

        bal = _read_saldos(
            conn.fetchone(
                "SELECT balance_brl, balance_saldos FROM wallets WHERE user_id = ?",
                (user_id,),
            )
        )
        new_bal = bal + saldos
        _set_wallet(conn, user_id, new_bal)
        if backend() == "postgres":
            conn.execute(
                """
                UPDATE pending_charges
                SET status = 'pago', paid_at = NOW()
                WHERE cobranca_id = ?
                """,
                (cobranca_id,),
            )
        else:
            conn.execute(
                """
                UPDATE pending_charges
                SET status = 'pago', paid_at = datetime('now')
                WHERE cobranca_id = ?
                """,
                (cobranca_id,),
            )
        conn.execute(
            """
            INSERT INTO ledger (
              user_id, kind, amount_brl, balance_after,
              amount_saldos, balance_after_saldos, reason, search_ref
            )
            VALUES (?, 'credit', ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                brl_equiv_saldos(saldos),
                brl_equiv_saldos(new_bal),
                saldos,
                new_bal,
                f"wallet_recharge_billing|fee={quote['asaas_fee_brl']}|net={quote['net_brl']}|pay={quote['pay_brl']}",
                search_ref,
            ),
        )
        return _user_from_id(conn, user_id)


def wallet_public(user: User) -> dict:
    return {
        "email": user.email,
        "balance_saldos": user.balance_saldos,
        "balance_brl": user.balance_brl,
        "saldo_unit_brl": SALDO_UNIT_BRL,
    }

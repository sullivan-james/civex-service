from __future__ import annotations

import hashlib
import secrets
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from civexhub.db.models import Token, User
from civexhub.domain.dtos import TokenDTO
from civex.domain.exceptions import NotFoundError


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class TokenService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_token(self, user_id: uuid.UUID, name: str) -> tuple[TokenDTO, str]:
        raw = "civex_" + secrets.token_hex(32)
        token = Token(
            id=uuid.uuid4(),
            user_id=user_id,
            token_hash=_hash_token(raw),
            name=name,
        )
        self._session.add(token)
        self._session.flush()
        return _to_dto(token), raw

    def validate_token(self, raw: str) -> User | None:
        from datetime import datetime, timezone
        token_hash = _hash_token(raw)
        token = self._session.query(Token).filter_by(token_hash=token_hash).first()
        if token is None:
            return None
        token.last_used_at = datetime.now(timezone.utc)
        return token.user

    def list_tokens(self, user_id: uuid.UUID) -> list[TokenDTO]:
        tokens = self._session.query(Token).filter_by(user_id=user_id).all()
        return [_to_dto(t) for t in tokens]

    def revoke_token(self, token_id: uuid.UUID, user_id: uuid.UUID) -> None:
        token = self._session.query(Token).filter_by(id=token_id, user_id=user_id).first()
        if token is None:
            raise NotFoundError(f"Token {token_id} not found")
        self._session.delete(token)


def _to_dto(token: Token) -> TokenDTO:
    return TokenDTO(
        id=token.id,
        user_id=token.user_id,
        name=token.name,
        created_at=token.created_at,
        last_used_at=token.last_used_at,
    )

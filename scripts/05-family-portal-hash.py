#!/usr/bin/env python3
"""Генерация bcrypt-хеша для /etc/family-portal/config.yaml"""
from __future__ import annotations

import getpass
import sys

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def main() -> int:
    if len(sys.argv) > 1:
        password = sys.argv[1]
    else:
        password = getpass.getpass("Пароль: ")
        confirm = getpass.getpass("Повтор: ")
        if password != confirm:
            print("Пароли не совпали", file=sys.stderr)
            return 1

    if len(password) < 8:
        print("Минимум 8 символов", file=sys.stderr)
        return 1

    print(pwd_context.hash(password))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

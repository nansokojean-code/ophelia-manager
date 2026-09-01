#!/bin/bash
cd "$(dirname "$0")"
if [ ! -f .env ]; then
  echo "Lege zuerst .env an (siehe .env.example)."
  exit 1
fi
python3 bot/main.py

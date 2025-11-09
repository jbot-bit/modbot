"""
Thin entrypoint used by Replit/Deployments.

Replit workflows and deployment configs expect `python bot.py`, so we just
delegate to the refactored implementation that already supports polling and
webhook modes via env vars (RUN_MODE/WEBHOOK_URL/PORT).
"""
from bot_refactored import main


if __name__ == "__main__":
    main()

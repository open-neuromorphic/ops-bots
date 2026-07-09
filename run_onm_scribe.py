import os
from dotenv import load_dotenv
from core.bot_factory import run_bot
from core.manifest import BOTS

load_dotenv(os.path.join("secrets", ".env"))

if __name__ == "__main__":
    run_bot("ONM Scribe Bot", BOTS["onm-scribe"].cogs, BOTS["onm-scribe"].token_env)
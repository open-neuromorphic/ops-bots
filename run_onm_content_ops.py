import os
from dotenv import load_dotenv
from core.bot_factory import run_bot
from core.manifest import BOTS

load_dotenv(os.path.join("secrets", ".env"))

if __name__ == "__main__":
    run_bot("ONM Content Ops Bot", BOTS["onm-content-ops"].cogs, BOTS["onm-content-ops"].token_env)
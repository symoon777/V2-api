import os
from dotenv import load_dotenv
load_dotenv()

class Config:
    # Like APIs
    LIKE_API_100: str    = os.getenv("LIKE_API_100", "https://ff.api.emonaxc.com/like?key=YSXHC6&uid={UID}")
    LIKE_API_200: str    = os.getenv("LIKE_API_200", "http://amsfresh200likeapi.vercel.app/like?uid={UID}&server_name=bd")
    LIKE_API_SECRET: str = os.getenv("LIKE_API_SECRET", "")  # 100 API er key URL e ache
    ADMIN_TOKEN: str     = os.getenv("ADMIN_TOKEN", "ams_admin_2024_secret")
    APP_ENV: str         = os.getenv("APP_ENV", "production")

cfg = Config()

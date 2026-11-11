from fastapi.templating import Jinja2Templates

from app.config import PAKET

templates = Jinja2Templates(directory=PAKET / "web" / "templates")

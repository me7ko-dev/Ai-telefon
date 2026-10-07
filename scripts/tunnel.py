"""Пуска Cloudflare Tunnel към локалния сървър и записва публичния адрес в панела.

Употреба (от папката на проекта, при пуснат сървър):
    python scripts/tunnel.py            # тунел към http://localhost:8000
    python scripts/tunnel.py 8001       # друг порт

Нужен е инсталиран cloudflared (виж docs/ETAP2_ELEVENLABS.md).
Безплатният („quick“) тунел дава нов адрес при всяко пускане – скриптът го записва
автоматично, а в панела остава само да натиснеш „Изпрати към ElevenLabs“.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def save_public_url(url: str) -> None:
    from sqlalchemy import select

    from app.config import get_settings
    from app.db import SessionLocal, init_db
    from app.models import Business
    from app.services.elevenlabs import get_config

    init_db()
    with SessionLocal() as db:
        business = db.scalar(select(Business).where(Business.slug == get_settings().panel_business_slug))
        if business is None:
            print("! Още няма фирма в базата – пусни сървъра веднъж и опитай пак.")
            return
        cfg = get_config(db, business)
        cfg.public_base_url = url
        db.commit()


def main() -> None:
    port = sys.argv[1] if len(sys.argv) > 1 else "8000"
    exe = shutil.which("cloudflared")
    if not exe:
        sys.exit("cloudflared не е намерен. Инсталирай го – виж docs/ETAP2_ELEVENLABS.md, стъпка 2.")

    cmd = [exe, "tunnel", "--no-autoupdate", "--url", f"http://localhost:{port}"]
    print("Пускам:", " ".join(cmd), "\n(спиране с Ctrl+C)\n")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
    found = False
    try:
        for line in proc.stdout:
            if not found and (m := URL_RE.search(line)):
                found = True
                url = m.group(0)
                save_public_url(url)
                print("=" * 64)
                print(f"  Публичен адрес: {url}")
                print(f"  Проверка:       {url}/health")
                print("  Адресът е записан в панела → „Агент“ → „Изпрати към ElevenLabs“.")
                print("=" * 64, flush=True)
            elif "ERR" in line or "error" in line.lower():
                print(line.rstrip(), flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()

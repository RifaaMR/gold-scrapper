import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


def apply_stealth(context):
    """bot wall"""
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        window.chrome = { runtime: {}, loadTimes: function() {}, csi: function() {}, app: {} };
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['id-ID', 'id', 'en-US', 'en'] });
    """)


def clean_price(price_str: str) -> int:
    """clear numeric"""
    digits = re.sub(r"[^\d]", "", str(price_str))
    return int(digits) if digits else 0


def scrape_aneka_logam(page) -> list[dict]:
    """Get Aneka Logam"""
    url = "https://www.anekalogam.co.id/id"
    print(f"[INFO] Mengakses {url} ...")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)

    soup = BeautifulSoup(page.content(), "html.parser")
    text_content = soup.get_text(" ", strip=True)
    now_utc = datetime.now(timezone.utc)

    sell_price = 0
    buyback_price = 0

    sell_match = re.search(
        r"(?:Harga\s*Jual|Jual).*?Rp\.?\s*([\d\.,]+)", text_content, re.IGNORECASE
    )
    buyback_match = re.search(
        r"(?:Harga\s*Beli|Buyback|Beli\s*Kembali).*?Rp\.?\s*([\d\.,]+)",
        text_content,
        re.IGNORECASE,
    )

    if sell_match:
        sell_price = clean_price(sell_match.group(1))
    if buyback_match:
        buyback_price = clean_price(buyback_match.group(1))

    if sell_price > 0 and buyback_price == 0:
        all_rp = re.findall(r"Rp\.?\s*([1-9][\d\.,]{6,9})", text_content)
        cleaned_prices = []
        for p in all_rp:
            val = clean_price(p)
            if 1000000 <= val <= 5000000 and val not in cleaned_prices:
                cleaned_prices.append(val)
        if len(cleaned_prices) >= 2:
            sell_price = max(cleaned_prices[0], cleaned_prices[1])
            buyback_price = min(cleaned_prices[0], cleaned_prices[1])

    if sell_price == 0:
        raise ValueError("Harga jual tidak ditemukan pada Aneka Logam.")

    return [{
        "source": "anekalogam",
        "material": "gold",
        "materialType": "Antam",
        "weight": 1,
        "weightUnit": "gr",
        "sellPrice": sell_price,
        "buybackPrice": buyback_price,
        "currency": "IDR",
        "recordedDate": now_utc.strftime("%Y-%m-%d"),
        "lineKey": "",
        "url": "/api/prices/anekalogam",
        "displayName": "Aneka Logam",
        "logo": "",
        "urlHomepage": "https://www.anekalogam.co.id"
    }]


def select_butik_if_needed(page):
    """close pop-up 'belum tersedia' dan select location"""
    page.wait_for_timeout(3000)

    # 1. close popup klik ok
    try:
        ok_btn = page.locator("button:has-text('OK')").first
        if ok_btn.is_visible(timeout=4000):
            print("[INFO] Menutup pop-up notifikasi Butik ('OK')...")
            ok_btn.click()
            page.wait_for_timeout(1500)
    except Exception:
        pass

    # 2. cek tabel sudah tampil
    body_text = page.evaluate("() => document.body.innerText")
    if "0.5 gr" not in body_text:
        print("[INFO] Lokasi Butik masih kosong ('-'). Memilih Lokasi Butik...")
        try:
            # Klik area teks 'Lokasi Butik' di bagian header
            lokasi_trigger = page.locator("text=Lokasi Butik").first
            if lokasi_trigger.is_visible(timeout=5000):
                # Klik di bawah atau pada elemen container Lokasi Butik
                lokasi_trigger.click()
                page.wait_for_timeout(2000)

            # Cari pilihan ekspedisi
            for keyword in ["Jakarta Ekspedisi", "Ekspedisi", "Pulogadung", "Gedung Antam", "Setiabudi", "Butik Emas"]:
                opt = page.locator(f"text={keyword}").first
                if opt.is_visible(timeout=2000):
                    print(f"[INFO] Memilih butik: {keyword}")
                    opt.click()
                    page.wait_for_timeout(2000)
                    break

            # Jika ada tombol Simpan
            for btn_text in ["Pilih", "Simpan", "Terapkan", "Konfirmasi", "OK"]:
                btn = page.locator(f"button:has-text('{btn_text}')").first
                if btn.is_visible(timeout=1500):
                    btn.click()
                    page.wait_for_timeout(2000)
                    break
        except Exception as e:
            print(f"[DEBUG] Gagal klik dropdown Lokasi Butik: {e}")


def scrape_logam_mulia(page) -> list[dict]:
    """get from logam mulia"""
    url = "https://logammulia.com/harga-emas"
    print(f"[INFO] Mengakses {url} ...")

    # 1. Buka beranda 
    page.goto("https://logammulia.com/", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(3000)

    # close pop-up di beranda 
    try:
        ok_home = page.locator("button:has-text('OK')").first
        if ok_home.is_visible(timeout=2000):
            ok_home.click()
    except Exception:
        pass

    # 2. Buka halaman Harga Emas
    page.goto(url, wait_until="domcontentloaded", timeout=60000)

    # 3. pilih lokasi "-"
    select_butik_if_needed(page)

    # inisialisasi state
    if "/harga-emas" not in page.url:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        select_butik_if_needed(page)

    try:
        page.wait_for_function(
            "() => document.body && document.body.innerText.includes('0.5 gr')",
            timeout=15000
        )
    except Exception:
        page.wait_for_timeout(3000)

    title = page.title()
    visible_text = page.evaluate("() => document.body.innerText")
    normalized_text = re.sub(r"\s+", " ", visible_text)
    now_utc = datetime.now(timezone.utc)

    sell_price = 0
    buyback_price = 0

    # Ekstrak baris"
    # Formating"
    match_1gr = re.search(
        r"(?<![\d\.])1\s*gr\s+Rp\s*([\d\.,]+)\s+Rp\s*([\d\.,]+)",
        normalized_text,
        re.IGNORECASE,
    )

    if match_1gr:
        sell_price = clean_price(match_1gr.group(1))
        print(f"[DEBUG] Baris 1 gr ditemukan! Harga Dasar: {sell_price}, Harga + Pajak: {clean_price(match_1gr.group(2))}")

    # Ambil harga Buyback
    if sell_price > 0:
        try:
            # Cek apakah informasi buyback
            bb_match = re.search(
                r"(?:Buyback|Harga\s*Beli\s*Kembali).*?Rp\s*([1-9][\d\.,]{5,9})",
                normalized_text,
                re.IGNORECASE,
            )
            if bb_match:
                buyback_price = clean_price(bb_match.group(1))
        except Exception:
            pass

    if sell_price == 0:
        page.screenshot(path="debug_lm.png", full_page=True)
        Path("debug_lm_text.txt").write_text(visible_text, encoding="utf-8")
        raise ValueError(
            f"Tabel harga masih belum muncul di '{title}'. "
            "Cek debug_lm.png lokasi butik."
        )

    return [{
        "source": "logammulia",
        "material": "gold",
        "materialType": "Antam",
        "weight": 1,
        "weightUnit": "gr",
        "sellPrice": sell_price,
        "buybackPrice": buyback_price,
        "currency": "IDR",
        "recordedDate": now_utc.strftime("%Y-%m-%d"),
        "lineKey": "",
        "url": "/api/prices/logammulia",
        "displayName": "Logam Mulia",
        "logo": "",
        "urlHomepage": "https://www.logammulia.com"
    }]


def save_json(filepath: Path, data_items: list[dict]):
    now_utc = datetime.now(timezone.utc)
    payload = {
        "success": True,
        "data": data_items,
        "count": len(data_items),
        "timestamp": now_utc.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "cached": True
    }
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"[SUCCESS] File disimpan ke: {filepath}")


def main():
    all_data = []
    aneka_buyback_fallback = 0

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(
                channel="chrome",
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--window-size=1366,768",
                ]
            )
        except Exception:
            browser = p.chromium.launch(
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--window-size=1366,768",
                ]
            )

        context = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
            locale="id-ID",
            timezone_id="Asia/Jakarta",
            permissions=["geolocation"],
            # Set koordinat Geolocation ke Jakarta (Gedung Antam) agar web otomatis mendeteksi butik Jakarta!
            geolocation={"latitude": -6.3016, "longitude": 106.8436},
            extra_http_headers={
                "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
                "Upgrade-Insecure-Requests": "1",
            }
        )
        apply_stealth(context)
        page = context.new_page()

        # 1. Scrape Aneka Logam
        try:
            aneka_items = scrape_aneka_logam(page)
            aneka_buyback_fallback = aneka_items[0]["buybackPrice"]
            print(f"Berhasil mengambil data dari Aneka Logam -> Jual: {aneka_items[0]['sellPrice']}, Buyback: {aneka_items[0]['buybackPrice']}")
            all_data.extend(aneka_items)
            save_json(Path("data/anekalogam.json"), aneka_items)
        except Exception as e:
            print(f"Gagal scrape Aneka Logam: {e}")

        # 2. Scrape Logam Mulia
        try:
            lm_items = scrape_logam_mulia(page)
            if lm_items[0]["buybackPrice"] == 0 and aneka_buyback_fallback > 0:
                lm_items[0]["buybackPrice"] = aneka_buyback_fallback
            print(f"Berhasil mengambil data dari Logam Mulia -> Jual: {lm_items[0]['sellPrice']}, Buyback: {lm_items[0]['buybackPrice']}")
            all_data.extend(lm_items)
            save_json(Path("data/logammulia.json"), lm_items)
        except Exception as e:
            print(f"Gagal scrape Logam Mulia: {e}")

        browser.close()

    if not all_data:
        print("[ERROR] Semua sumber gagal diambil.")
        sys.exit(1)

    save_json(Path("data/prices.json"), all_data)


if __name__ == "__main__":
    main()

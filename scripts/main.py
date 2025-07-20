import csv
import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from zoneinfo import ZoneInfo

today = datetime.now(ZoneInfo('Europe/Sofia')).strftime("%d-%m-%Y %X")

path = os.getcwd()
path_csv_file = os.path.join(path, "data/hdd_data.csv")

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

def save_data(path, title, price):
    def check_header(path):
        with open(path, "r", encoding="utf-8") as csvfile:
            reader = csv.reader(csvfile)
            return any(reader)

    with open(path, "a", encoding="utf-8", newline="") as csvfile:
        fieldnames = ["Date", "Title", "Price"]
        writer = csv.DictWriter(
            csvfile,
            fieldnames=fieldnames,
            dialect="excel",
            delimiter=";",
            quoting=csv.QUOTE_NONE,
            escapechar="\\"
        )

        if not check_header(path):
            writer.writeheader()

        writer.writerow({"Date": today, "Title": title, "Price": price})

clear_screen()


url_links = [
    "https://www.technopolis.bg/bg/Vanshni-diskove/Vanshen-disk-SEAGATE-BASIC-STJL4000400/p/522176",
    "https://www.technopolis.bg/bg/Vanshni-diskove/Vanshen-disk-TOSHIBA-CANVIO-BASICS-HDTB540EK3AA/p/500485",
    "https://www.technopolis.bg/bg/Vanshni-diskove/Vanshen-disk-WESTERN-DIGITAL-ELEMENTS-WDBU6Y0040BBK-WESN/p/526269",
    "https://www.technopolis.bg/bg/Audio-slushalki/Stereo-slushalki-CANYON-CNS-CBTHS3DG/p/301583",
    "https://www.technopolis.bg/bg/Audio-slushalki/Stereo-slushalki-PANASONIC-RB-HF630BE-A/p/303084",
    "https://www.technopolis.bg/bg/Audio-slushalki/Stereo-slushalki-CANYON-CNS-CBTHS10BK/p/302099",
    "https://www.technopolis.bg/bg/Smartfoni-i-mobilni-telefoni/Smartfon-GSM--SAMSUNG-GALAXY-A56-5G-OLIVE/p/506853",
    "https://www.technopolis.bg/bg/Smartfoni-i-mobilni-telefoni/Smartfon-GSM--SAMSUNG-GALAXY-A36-5G-256-8-LIME/p/506849",
    "https://www.technopolis.bg/bg/Smartfoni-i-mobilni-telefoni/Smartfon-GSM--SAMSUNG-GALAXY-A26-5G-256-8-MINT/p/506841",
    "https://www.technopolis.bg/bg/Smartfoni-i-mobilni-telefoni/Smartfon-GSM--XIAOMI-REDMI-NOTE-14-PRO--5G-BLUE/p/506511",
    "https://www.technopolis.bg/bg/Dronove/Dron-XMART-FOLDING-S6-BLACK/p/301029",
    "https://www.technopolis.bg/bg/Dronove/Dron-XMART-FOLDING-SG700D-BLACK/p/581296",
    "https://www.technopolis.bg/bg/Dronove/Dron-TELLO-BY-DJI/p/581600",
    "https://www.technopolis.bg/bg/Laptopi/Gejming-laptop-LENOVO-LOQ-15IRH8-82XV00LGBM/p/502885",
    "https://www.technopolis.bg/bg/Laptopi/Gejming-laptop-LENOVO-LOQ-15IAX9-83GS002VBM/p/503805",
    "https://www.technopolis.bg/bg/Laptopi/Gejming-laptop-LENOVO-LOQ-15ARP9-83JC000HBM/p/504925",
    "https://www.technopolis.bg/bg/Laptopi/Gejming-laptop-LENOVO-LOQ-15ARP9-83JC0026BM/p/504923",
    "https://www.technopolis.bg/bg/Laptopi/Gejming-laptop-LENOVO-LOQ-15APH8-82XT00DSBM/p/504150",
    "https://www.technopolis.bg/bg/Laptopi/Laptop-LENOVO-IdeaPad-Slim-3-15IRH10-83K10076BM/p/507807",
    "https://www.technopolis.bg/bg/Laptopi/Laptop-LENOVO-IdeaPad-Slim-5-15IRH9-83G1001BRM/p/506052",
    "https://www.technopolis.bg/bg/Laptopi/Laptop-LENOVO-IdeaPad-Slim-3-15IRH10-83K1007FBM/p/507826",
    "https://www.technopolis.bg/bg/Laptopi/Laptop-LENOVO-IdeaPad-Slim-5-16ARP10-83HU000HBM/p/507461",
    "https://www.technopolis.bg/bg/Laptopi/Laptop-LENOVO-IdeaPad-Slim-5-16ARP10-83HU000SBM/p/507463",
    "https://www.technopolis.bg/bg/Nastolni-kompyutri/Gejming-nastolen-kompyutar-GPLAY-GAMING-REACTOR/p/507697",
    "https://www.technopolis.bg/bg/Nastolni-kompyutri/Gejming-nastolen-kompyutar-GRIGS-NOVA-ULTRA/p/503947",
    "https://www.technopolis.bg/bg/Nastolni-kompyutri/Gejming-nastolen-kompyutar-RADIUS-FORTRESS-X3D/p/506750",
]

for link in url_links:
    try:
        page_response = requests.get(link, timeout=10)
        if page_response.status_code == 200:
            page_content = BeautifulSoup(page_response.content, "html.parser")
            # print(page_content)

            title = page_content.find('div', class_="product-name")

            price_box = page_content.find('div', class_="pdp-details__start")

            if price_box:
                price = price_box.find('div', class_="product-box__price")
                
                if price:
                    price_val_text = price.text.strip().replace("Цена:", "").replace(" лв.", "").split("/")
                    price_val = float(price_val_text[0])
                    print(f"::notice ::✅ Успешно взета стойност: \033[1;37;40m{title.text.strip()}\033[0m - \033[1;35;40m{price_val}\033[0m")
                else:
                    prices = price_box.find('div', class_="prices")
                    price = prices.select_one('div.price:not(.old-price)')
                    price_val_text = price.text.strip().replace("Цена:", "").replace(" лв.", "").replace(" .00", "").split("/")
                    price_val = float(price_val_text[0])
                    print(f"::notice ::✅ Успешно взета стойност: \033[1;37;40m{title.text.strip()}\033[0m - \033[1;35;40m{price_val}\033[0m")
                    
            else:
                print("::error ::❌ Елемент с клас pdp-details__start не е намерен.")

            save_data(path_csv_file, title.text.strip(), price_val)
        else:
            print(f"::warning ::⚠️ Страницата върна код: {page_response.status_code}")
            
    except Exception as e:
        print(f"::error ::❌ Грешка при скрапване: {e}")


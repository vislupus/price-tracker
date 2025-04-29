import csv
import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from zoneinfo import ZoneInfo

today = datetime.today(ZoneInfo('Europe/Sofia')).strftime("%d-%m-%Y %X")

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
        )

        if not check_header(path):
            writer.writeheader()

        writer.writerow({"Date": today, "Title": title, "Price": price})

clear_screen()

url_links = [
    "https://www.technopolis.bg/bg/Vanshni-diskove/Vanshen-disk-SEAGATE-BASIC-STJL4000400/p/522176",
    "https://www.technopolis.bg/bg/Vanshni-diskove/Vanshen-disk-TOSHIBA-CANVIO-BASICS-HDTB540EK3AA/p/500485",
    "https://www.technopolis.bg/bg/Vanshni-diskove/Vanshen-disk-WESTERN-DIGITAL-ELEMENTS-WDBU6Y0040BBK-WESN/p/526269"
]

for link in url_links:
    page_response = requests.get(link)
    page_content = BeautifulSoup(page_response.content, "html.parser")

    title = page_content.find('div', class_="product-name")

    price = page_content.find('div', class_="product-box__price")
    price_val = float(price.text.strip().replace("Цена:", "").replace(" лв.", ""))
    print(f"\033[1;37;40m{title.text.strip()}\033[0m - \033[1;35;40m{price_val}\033[0m")

    save_data(path_csv_file, title.text.strip(), price_val)
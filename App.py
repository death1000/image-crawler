import os
import time
import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from PIL import Image
import io
import zipfile
from flask import Flask, request, send_file, render_template
import shutil
import logging

# Thiết lập logging
logging.basicConfig(filename='crawler.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# Danh sách User-Agent
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
]

# Biến toàn cục
MIN_SIZE = 800
MAX_IMAGES_DEFAULT = 50  # Giới hạn mặc định để tránh tải quá nhiều


def get_image_hash(image_data):
    """Tính MD5 hash của dữ liệu ảnh"""
    return hashlib.md5(image_data).hexdigest()


def download_image(img_url, idx, base_url, folder_name, retries=3):
    """Tải một ảnh và lưu vào thư mục tạm"""
    img_url = urljoin(base_url, img_url)
    img_name = os.path.join(folder_name, f"image_{time.time()}_{idx}.jpg")
    headers = {"User-Agent": choice(USER_AGENTS)}

    for attempt in range(retries):
        try:
            response = requests.get(img_url, headers=headers, timeout=10)
            if response.status_code == 200:
                image_data = response.content
                img = Image.open(io.BytesIO(image_data))
                width, height = img.size
                if width < MIN_SIZE or height < MIN_SIZE:
                    return None
                with open(img_name, "wb") as f:
                    f.write(image_data)
                logging.info(f"Downloaded: {img_name}")
                return img_name
            else:
                raise Exception(f"Status code {response.status_code}")
        except Exception as e:
            logging.error(f"Failed to download {img_url}: {str(e)}")
            time.sleep(2 ** attempt)
    return None


def crawl_images(start_url, max_images=MAX_IMAGES_DEFAULT):
    """Thu thập ảnh từ URL và trả về đường dẫn file ZIP"""
    folder_name = f"temp_{int(time.time())}"
    os.makedirs(folder_name, exist_ok=True)

    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"user-agent={choice(USER_AGENTS)}")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    try:
        driver.get(start_url)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)  # Chờ trang tải
        soup = BeautifulSoup(driver.page_source, "html.parser")

        images = soup.find_all("img")
        image_count = 0
        image_hashes = set()

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = []
            for idx, img in enumerate(images):
                if image_count >= max_images:
                    break
                img_url = (img.get("data-srcset", "").split(",")[-1].strip().split(" ")[0] or
                           img.get("data-src") or img.get("src"))
                if img_url:
                    futures.append(executor.submit(download_image, img_url, idx, start_url, folder_name))
            for future in futures:
                img_path = future.result()
                if img_path:
                    with open(img_path, "rb") as f:
                        image_hash = get_image_hash(f.read())
                    if image_hash not in image_hashes:
                        image_hashes.add(image_hash)
                        image_count += 1

        # Tạo file ZIP
        zip_path = f"{folder_name}.zip"
        with zipfile.ZipFile(zip_path, "w") as zipf:
            for root, _, files in os.walk(folder_name):
                for file in files:
                    zipf.write(os.path.join(root, file), file)

    finally:
        driver.quit()
        shutil.rmtree(folder_name, ignore_errors=True)  # Xóa thư mục tạm

    return zip_path if image_count > 0 else None


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        url = request.form.get("url")
        if not url or not url.startswith("http"):
            return render_template("index.html", error="Vui lòng nhập URL hợp lệ!")

        zip_path = crawl_images(url)
        if zip_path:
            return send_file(zip_path, as_attachment=True, download_name="images.zip", mimetype="application/zip")
        else:
            return render_template("index.html", error="Không tìm thấy ảnh để tải!")
    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
# 🤖 Web Novel Automation Tool: Scrape, Translate, and Audiobook/Video Generator

ระบบเครื่องมืออัตโนมัติในการดึงเนื้อหานิยายภาษาจีน แปลเป็นภาษาไทยด้วย Gemini / DeepSeek API โดยอ้างอิงตารางคู่คำศัพท์เฉพาะทาง (`glossary.json`) และแปลงเป็นไฟล์เสียงภาษาไทย (TTS) พร้อมทั้งรวมไฟล์มัลติมีเดีย `.mp4` และสร้างข้อมูลประทับเวลา (Timestamps) สำหรับโพสต์ลง YouTube ได้ทันที

---

## 🛠️ 1. ความต้องการของระบบ (System Requirements)

1. **Python 3.8 หรือสูงกว่า**
2. **ติดตั้งไลบรารีและเครื่องมือที่จำเป็น:**
   * ติดตั้งแพ็คเกจผ่าน pip:
     ```bash
     pip install -r requirements.txt
     ```
   * ติดตั้งเบราว์เซอร์สำหรับ Playwright Scraper:
     ```bash
     playwright install chromium
     ```
3. **การตั้งค่าไฟล์คีย์ API (`.env` ที่โฟลเดอร์เริ่มต้นของโปรเจกต์):**
   สร้างไฟล์ชื่อ `.env` และระบุคีย์บริการที่คุณต้องการใช้งาน:
   ```env
   GEMINI_API_KEY=your_gemini_api_key_here
   DEEPSEEK_API_KEY=your_deepseek_api_key_here
   ```

---

## 📁 2. โครงสร้างโปรเจกต์และรูปแบบชื่อไฟล์

### โครงสร้างไฟล์โค้ดหลัก
* [main.py](file:///Users/chettatosuanchit/Documents/Automation/main.py) - จุดเริ่มต้นเรียกใช้งานคำสั่งผ่าน CLI ทั้งหมด
* [scraper.py](file:///Users/chettatosuanchit/Documents/Automation/scraper.py) - โมดูลดึงข้อมูลหน้าเว็บนิยายจีนแบบ sequential (ตามลิงก์หน้าถัดไป)
* [translator.py](file:///Users/chettatosuanchit/Documents/Automation/translator.py) - โมดูลแปลบทความด้วย Gemini / DeepSeek API พร้อมตรวจสอบ Glossary
* [audiobook.py](file:///Users/chettatosuanchit/Documents/Automation/audiobook.py) - โมดูลแปลงข้อความเป็นเสียง MP3 (Edge-TTS) และเขียนภาพนิ่งประกอบเป็น MP4 (FFmpeg)
* [utils.py](file:///Users/chettatosuanchit/Documents/Automation/utils.py) - เครื่องมืออำนวยความสะดวก (ตัวจัดบาร์แสดงสถานะ, จัดการความสะอาดข้อความ)
* [combine_fast.py](file:///Users/chettatosuanchit/Documents/Automation/combine_fast.py) - สคริปต์แบบเร่งด่วนสำหรับต่อเชื่อมวิดีโอบทใหม่เข้าหัววิดีโอรวมเดิมในทันที (ไม่ต้อง re-encode)

### โครงสร้างโฟลเดอร์เก็บงาน (ระบุโดยออปชัน `--option`)
เมื่อรันคำสั่งโดยชี้ปลายทางโฟลเดอร์เก็บงานผ่าน `--option "/path/to/folder"` ระบบจะสร้างและใช้โครงสร้างดังนี้:
* `[โฟลเดอร์หลัก]/` - ใช้เซฟไฟล์ดิบภาษาจีน (.md) ที่ได้จาก Scraper
* `[โฟลเดอร์หลัก]/done/` - ใช้ย้ายเก็บไฟล์ดิบภาษาจีนหลังจากแปลสำเร็จแล้ว
* `[โฟลเดอร์หลัก]/translate/` - ใช้เก็บไฟล์บทแปลภาษาไทย (.md)
* `[โฟลเดอร์หลัก]/Audiobook/` - แหล่งเก็บงานเสียงและสื่อ ประกอบด้วย:
  * `000X_บทที่ X: ชื่อตอน.mp3` - ไฟล์เสียงรายตอน
  * `combined_audiobook.mp3` - ไฟล์รวมเสียงทุกตอนยาวต่อเนื่อง
  * `combined_audiobook.mp4` - ไฟล์วิดีโอรวมภาพนิ่งและเสียงพร้อมอัปโหลดขึ้น YouTube
  * `timetrack.txt` - ไฟล์เก็บประทับจุดเริ่มเวลาของแต่ละบท (สำหรับใช้ทำ Chapters บน YouTube)

### ✨ มาตรฐานรูปแบบชื่อไฟล์ (Filename Format)
ไฟล์ทั้งหมดที่ผ่านการแปลและแปลงเป็นสื่อ จะถูกจัดรูปแบบชื่อไฟล์ให้สวยงามเป็นระเบียบ ดังนี้:
* **รูปแบบชื่อไฟล์:** `running_<บทที่> <เลขบท>: <ชื่อตอน>` (เช่น `0001_บทที่ 1: เรื่องไมคาดฝัน.md`)
* **การรองรับข้ามระบบปฏิบัติการ (Cross-OS Compatibility):**
  * **macOS / Linux:** จะใช้เครื่องหมายโคลอนและเว้นวรรค (`: `) คั่นตามโครงสร้างมาตรฐาน
  * **Windows:** เนื่องจาก Windows ไม่อนุญาตให้ตั้งชื่อไฟล์ที่มีเครื่องหมาย `:` ระบบจะแปลงไปใช้เครื่องหมายขีดกลางคั่นแทน (` - `) โดยอัตโนมัติเพื่อความปลอดภัยของระบบไฟล์

---

## 🚀 3. วิธีการสั่งรันโปรแกรม (Usage Guide)

> [!TIP]
> ตัวเลือก `--option` ช่วยให้คุณระบุโฟลเดอร์เก็บงานที่อื่นได้ทันทีโดยไม่ต้อง `cd` ย้ายโฟลเดอร์ใน Terminal ครับ

### ทางเลือกที่ 1: คำสั่งรันรวมทุกขั้นตอนรวดเดียว (Stage 1-3)
ดึงหน้าเว็บนิยายจีน ➡️ แปลภาษาไทย ➡️ สร้างเสียงและวิดีโอประกอบรวมสมบูรณ์ในคำสั่งเดียว:
```bash
python3 main.py all --url "URL_เริ่มต้น" --limit จำนวนตอน --title-selector "CSS_Title" --content-selector "CSS_Content" --next-selector "CSS_Next_Link" --option "โฟลเดอร์เก็บงาน"
```
* **ตัวเลือกเสริม:**
  * `--limit`: จำนวนตอนที่ต้องการทำ หรือระบุ `null` เพื่อโหลดไปเรื่อยๆ จนสุดลิงก์ถัดไป
  * `--ai`: เลือกผู้ให้บริการแปลภาษาระหว่าง `gemini` หรือ `deepseek` (ค่าเริ่มต้น: `gemini`)
  * `--model`: ระบุชื่อโมเดลเฉพาะเจาะจง (เช่น `gemini-2.5-flash` หรือ `deepseek-v4-flash`)
  * `--voice`: เสียงผู้พูด TTS (ค่าเริ่มต้น: `th-TH-NiwatNeural` สำหรับเสียงผู้ชาย)
  * `--no-video`: ข้ามการเรนเดอร์วิดีโอรายตอน (แต่ยังคงสร้างวิดีโอรวม)
  * `--proxy`: เปิดใช้พร็อกซีระหว่างเชื่อมต่อ (ระบุ `"true"`)

---

### ทางเลือกที่ 2: สั่งรันเฉพาะขั้นตอนแปลและสร้างเสียงพร้อมกัน (Stage 2 + 3)
หากคุณเคยใช้คำสั่งดึงตอนภาษาจีนมาเก็บไว้ในเครื่องแล้ว และต้องการทำการแปลไทยพร้อมสร้างไฟล์เสียงและวิดีโอรวมจบในขั้นตอนเดียว:
```bash
python3 main.py translate-audiobook --option "โฟลเดอร์เก็บงาน" --limit จำนวนตอน --ai "deepseek"
```
* **ตัวเลือกเสริม:**
  * `--combine` / `--no-combine`: เลือกว่าจะประกอบรวมวิดีโอตอนท้ายสุดหรือไม่ (ค่าเริ่มต้น: `--combine` ทำการประกอบอัตโนมัติ)
  * รองรับตัวเลือก `--ai`, `--model`, `--voice`, `--proxy` และ `--no-video` เช่นเดียวกับแบบครอบคลุม

---

### ทางเลือกที่ 3: สั่งรันแยกทีละสเต็ป (Stage-by-Stage)

#### **สเต็ปที่ 1: ดึงนิยายต้นฉบับภาษาจีน (Scrape)**
```bash
python3 main.py scrape --url "URL_เริ่มต้น" --limit จำนวนตอน --title-selector "CSS_Title" --content-selector "CSS_Content" --next-selector "CSS_Next_Link" --option "โฟลเดอร์เก็บงาน"
```
* **การดึงแบบไม่จำกัดตอน:** ให้ป้อน `--limit null` เพื่อให้ระบบวนลูปดึงไปจนกว่าจะหาปุ่มหน้าถัดไปไม่เจอ

#### **สเต็ปที่ 2: แปลเนื้อหาเปรียบเทียบคำศัพท์ (Translate)**
อ่านไฟล์ดิบภาษาจีนในโฟลเดอร์ ย้ายไฟล์แปลไทยเข้า `translate/` และย้ายไฟล์จีนที่เสร็จแล้วเข้า `done/`
```bash
python3 main.py translate --option "โฟลเดอร์เก็บงาน" --ai "deepseek" --limit จำนวนตอน
```
* **กลไกอัจฉริยะ DeepSeek Batching:** เมื่อเลือกแปลด้วย DeepSeek ระบบจะจัดกลุ่มการแปลทีละ 10 ตอน และทำ Prompt Caching ผ่าน Glossary ย่อยโดยอัตโนมัติเพื่อลดค่าใช้จ่ายและเพิ่มความเร็วในการตอบกลับ

#### **สเต็ปที่ 3: สร้างเสียงและประกอบวิดีโอรวม (Audiobook)**
```bash
python3 main.py audiobook --combine --option "โฟลเดอร์เก็บงาน" --limit จำนวนตอน
```
* **ระบบเช็คข้ามไฟล์เสียง (Skip Logic):** ระบบจะตรวจหาไฟล์เสียงในโฟลเดอร์ `Audiobook/` หากตรวจพบว่าบทนั้นมีไฟล์เสียง MP3 อยู่แล้ว จะทำการข้ามไปประมวลผลบทถัดไปทันทีเพื่อประหยัดเวลา

---

## ⚡️ 4. การใช้สคริปต์ประกอบรวมวิดีโอแบบรวดเร็ว (`combine_fast.py`)

หากเกิดกรณีที่มีการเพิ่มบทใหม่เข้ามาทีหลัง หรือแก้ไขเสียงเฉพาะบางตอน และต้องการเอาบทใหม่ไปต่อหัววิดีโอชุดเดิมแบบด่วนที่สุดโดยไม่ต้องประมวลผลเรนเดอร์ภาพและเสียงใหม่ทั้งหมด (ซึ่งปกติใช้เวลานาน):
```bash
python3 combine_fast.py --cover "พาธรูปปก" --new-audio "พาธไฟล์เสียงใหม่ (.mp3)" --old-video "พาธวิดีโอรวมเดิม (.mp4)" --output "พาธเซฟวิดีโอรวมใหม่ (.mp4)"
```

> [!IMPORTANT]
> สคริปต์จะใช้โหมด `-c copy` ของ FFmpeg ในการเชื่อมต่อ ทำให้วิดีโอเดิมและวิดีโอใหม่ต้องมีโปรไฟล์เดียวกันเสมอ (โปรแกรมจะตั้งค่า 1280x720, 5fps, H.264 Baseline, AAC 44100Hz Stereo เป็นค่าเริ่มต้นโดยอัตโนมัติอยู่แล้ว)

---

## 📋 5. ตัวอย่างชุดคำสั่งรันจริงรายนิยาย (Ready-to-Use Examples)

### 📌 5.1 เรื่อง: ย้อนเวลาสู่หนานหมิงเป็นท่านอ๋อง
* **โฟลเดอร์เก็บงาน:** `/Users/chettatosuanchit/Documents/ย้อนเวลาสู่หนานหมิงเป็นท่านอ๋อง`
* **ข้อมูลเว็บแหล่งที่มา:** `https://funs.me`

* **แบบคำสั่งดึงตอนต้นฉบับอย่างเดียว (โหลดทั้งหมด/ไม่จำกัด):**
  ```bash
  python3 main.py scrape --url "https://funs.me/text/17561/15670177.html" --limit null --title-selector "td[background*='bgheader']" --content-selector "#ChSize" --next-selector "a.pages" --option "/Users/chettatosuanchit/Documents/ย้อนเวลาสู่หนานหมิงเป็นท่านอ๋อง"
  ```
* **แบบสั่งแปลพร้อมสร้างเสียงในคำสั่งเดียว (จำกัด 50 ตอนแรก):**
  ```bash
  python3 main.py translate-audiobook --option "/Users/chettatosuanchit/Documents/ย้อนเวลาสู่หนานหมิงเป็นท่านอ๋อง" --ai "deepseek" --limit 50
  ```
* **แบบรันแยกขั้นตอนสำหรับบทแปลและประกอบวิดีโอเสียง:**
  ```bash
  # ขั้นแปลภาษาไทยด้วย DeepSeek
  python3 main.py translate --option "/Users/chettatosuanchit/Documents/ย้อนเวลาสู่หนานหมิงเป็นท่านอ๋อง" --ai "deepseek" --limit 50
  
  # ขั้นสร้างเสียงและวิดีโอรวม
  python3 main.py audiobook --combine --option "/Users/chettatosuanchit/Documents/ย้อนเวลาสู่หนานหมิงเป็นท่านอ๋อง" --limit 50
  ```

---

### 📌 5.2 เรื่อง: คนบ้าแห่งต้าหมิง
* **โฟลเดอร์เก็บงาน:** `/Users/chettatosuanchit/Documents/คนบ้าแห่งต้าหมิง`
* **ข้อมูลเว็บแหล่งที่มา:** `https://www.bgg99.cc`

* **แบบสั่งรันรวดเดียว All-in-One (25 ตอน):**
  ```bash
  python3 main.py all --url "https://www.bgg99.cc/book/1136853033/916083008.html" --limit 25 --title-selector ".content h1" --content-selector "#content" --next-selector ".page_chapter ul li:nth-child(3) a" --option "/Users/chettatosuanchit/Documents/คนบ้าแห่งต้าหมิง" --ai "deepseek"
  ```
* **แบบสั่งแปลพร้อมสร้างเสียงในคำสั่งเดียว (จำกัด 25 ตอน):**
  ```bash
  python3 main.py translate-audiobook --option "/Users/chettatosuanchit/Documents/คนบ้าแห่งต้าหมิง" --ai "deepseek" --limit 25
  ```

---

### 📌 5.3 เรื่อง: ช่วงเวลาหลายปีของฉันในฐานะนักบวชลัทธิเต๋า
* **โฟลเดอร์เก็บงาน:** `/Users/chettatosuanchit/Documents/ช่วงเวลาหลายปีของฉันในฐานะนักบวชลัทธิเต๋า`
* **ข้อมูลเว็บแหล่งที่มา:** `https://funs.me`

* **แบบสั่งรันรวดเดียว All-in-One (25 ตอน):**
  ```bash
  python3 main.py all --url "https://funs.me/text/2080/15540101.html" --limit 25 --title-selector "td[background*='bgheader'] > font" --content-selector "#ChSize" --next-selector "a.pages" --option "/Users/chettatosuanchit/Documents/ช่วงเวลาหลายปีของฉันในฐานะนักบวชลัทธิเต๋า" --ai "deepseek"
  ```

---

### 📌 5.4 เรื่อง: จิงอันโหว (เดิม)
* **โฟลเดอร์เก็บงาน:** `/Users/chettatosuanchit/Downloads/จิงอันโหว`
* **ข้อมูลเว็บแหล่งที่มา:** `https://funs.me`

* **แบบคำสั่งดึงตอนต้นฉบับอย่างเดียว (โหลดทั้งหมด/ไม่จำกัด):**
  ```bash
  python3 main.py scrape --url "https://funs.me/text/17561/15670001.html" --limit null --title-selector "td[background*='bgheader']" --content-selector "#ChSize" --next-selector "a.pages" --option "/Users/chettatosuanchit/Downloads/จิงอันโหว"
  ```

---

## 🔍 6. วิธีการค้นหาและใช้ CSS Selectors สำหรับหน้าเว็บนิยายใหม่ๆ

เมื่อต้องการดึงข้อมูลจากเว็บนิยายแปลภาษาจีนแห่งใหม่ คุณสามารถค้นหาค่า CSS Selectors ได้ด้วยขั้นตอนดังนี้:

### 1. วิธีเปิดเครื่องมือพัฒนา (Inspect Element)
1. เปิดเบราว์เซอร์ไปยังตอนนิยายที่ต้องการดึง
2. คลิกขวาตรงเนื้อหาที่ต้องการหา (เช่น บนหัวข้อชื่อตอน หรือบนข้อความนิยาย)
3. เลือก **Inspect (ตรวจสอบ)** หรือกดคีย์ลัด:
   * **Windows:** `F12`
   * **Mac:** `Cmd + Option + I`

### 2. รูปแบบ CSS Selectors ที่พบบ่อย
* **ชื่อตอนนิยาย (`--title-selector`):** 
  * มักอยู่ในแท็ก `<h1>`, `<h2>` หรือ class เช่น `.chapter-title` หรือ `h1.title`
  * หากเป็นนิยายบนเว็บตารางโบราณ อาจเป็น `td[background*='bgheader']`
* **กล่องเนื้อหาหลัก (`--content-selector`):**
  * ค้นหาแท็กครอบนอกสุดที่คลุมเนื้อหาบทความนิยายทั้งหมด เช่น `#content`, `#ChSize` หรือ `.read-content`
* **ปุ่มตอนถัดไป (`--next-selector`):**
  * ค้นหาแท็กอ้างอิงลิงก์ `<a>` ที่ใช้สำหรับเปลี่ยนไปยังตอนถัดไป เช่น `a.next`, `a.pages` หรือ `.page_chapter ul li:nth-child(3) a`

> [!WARNING]
> หาก CSS Selector มีเครื่องหมายคำพูดเดี่ยว เช่น `td[background*='bgheader']` เมื่อพิมพ์คำสั่งใน Terminal ให้ทำการ **ครอบค่าตัวเลือกทั้งหมดด้วยเครื่องหมายคำพูดคู่ (Double Quotes)** เสมอ เพื่อไม่ให้ระบบ Shell ของระบบปฏิบัติการสับสน

---

## 📝 7. ข้อกำหนดทางเทคนิคและการปรับปรุงเพิ่มเติม

* **การแสดงผลความคืบหน้า (Progress Bar):** ระบบมีการใช้บาร์แสดงกราฟิกตัวหนังสือ `[██████░░░░] 60% (3/5)` ช่วยให้ติดตามสถานะการรันงานได้อย่างเรียลไทม์
* **ความเสถียรและคุณภาพของไฟล์วิดีโอ (macOS QuickTime & Mobile Compatibility):** ระบบประกอบวิดีโอของโปรเจกต์มีการจูนฟิลเตอร์ระดับลึกเพื่อเรนเดอร์ภาพนิ่งความละเอียดระดับสากล 720p 5fps (Baseline H.264) คู่กับเสียงมาตรฐาน 44100Hz Stereo AAC และใส่คำสั่งพิเศษ `-movflags +faststart` เพื่อช่วยให้ไฟล์ขนาดใหญ่สามารถโหลดล่วงหน้าและเปิดดูบน QuickTime Player ของ macOS รวมถึงเปิดบนสมาร์ทโฟนทั่วไปได้ทันทีโดยไม่มีการติดขัด

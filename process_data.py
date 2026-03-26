import json
import csv
from bs4 import BeautifulSoup


# ---------------- CLEAN HTML ---------------- #
def clean_html(html):
    soup = BeautifulSoup(html, "html.parser")

    # remove noise elements
    for tag in soup(["script", "style", "nav", "footer", "header", "form", "aside"]):
        tag.decompose()

    text = soup.get_text(separator=" ")

    text = " ".join(text.split())

    # remove common junk phrases
    junk_patterns = [
        "we value your privacy",
        "accept all",
        "cookie",
        "no cookies to display",
        "recent posts",
        "recent comments"
    ]

    text_lower = text.lower()

    if any(junk in text_lower for junk in junk_patterns):
        return ""

    return text


# ---------------- CHUNK TEXT ---------------- #
def chunk_text(text, size=120):
    words = text.split()
    chunks = []

    for i in range(0, len(words), size):
        chunk = " ".join(words[i:i+size])

        # ignore very small chunks
        if len(chunk) > 50:
            chunks.append(chunk)

    return chunks


# ---------------- PROCESS ---------------- #
def process_data(domain_name, input_file):
    print("\n🔄 Processing scraped data...")

    # Dynamic output file names
    JSON_OUTPUT = f"{domain_name}_cleaned_data.json"
    TEXT_OUTPUT = f"{domain_name}_cleaned_data.txt"
    CSV_OUTPUT = f"{domain_name}_cleaned_data.csv"

    try:
        with open(input_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ Failed to load input file: {input_file} | {e}")
        return

    json_output = []
    text_output_lines = []
    csv_rows = []

    chunk_id = 1

    for item in data:
        url = item.get("url")
        html = item.get("content", "")

        try:
            clean_text_data = clean_html(html)
            chunks = chunk_text(clean_text_data)

            for chunk in chunks:
                # JSON format
                json_output.append({
                    "id": f"chunk_{chunk_id}",
                    "text": chunk,
                    "url": url
                })

                # TEXT format
                text_output_lines.append(f"[{chunk_id}] {url}\n{chunk}\n\n")

                # CSV format
                csv_rows.append([chunk_id, url, chunk])

                chunk_id += 1

        except Exception as e:
            print(f"⚠️ Processing error → {url} | {e}")

    # -------- SAVE FILES -------- #

    try:
        # JSON
        with open(JSON_OUTPUT, "w", encoding="utf-8") as f:
            json.dump(json_output, f, indent=2, ensure_ascii=False)

        # TEXT
        with open(TEXT_OUTPUT, "w", encoding="utf-8") as f:
            f.writelines(text_output_lines)

        # CSV
        with open(CSV_OUTPUT, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "url", "text"])
            writer.writerows(csv_rows)

        print(f"✅ JSON → {JSON_OUTPUT}")
        print(f"✅ TEXT → {TEXT_OUTPUT}")
        print(f"✅ CSV  → {CSV_OUTPUT}")
        print(f"📊 Total chunks: {len(json_output)}")

    except Exception as e:
        print(f"❌ Error saving files: {e}")
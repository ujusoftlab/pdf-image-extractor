from apscheduler.schedulers.background import BackgroundScheduler
import time
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse
import os
from pdf2image import convert_from_path
from PIL import Image
import zipfile
import io

app = FastAPI()

required_dirs = ["./uploads", "./output_images"]

for d in required_dirs:
    if not os.path.exists(d):
        os.makedirs(d)
        
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "./uploads"
OUTPUT_DIR = "./output_images"
#os.makedirs(UPLOAD_DIR, exist_ok=True)
#os.makedirs(OUTPUT_DIR, exist_ok=True)

@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # 변환
    images = convert_from_path(file_path, dpi=200, first_page=1, last_page=1)
    image_path = os.path.join(OUTPUT_DIR, file.filename.replace(".pdf", ".jpg"))
    images[0].save(image_path, "JPEG")
    return {"filename": file.filename, "image_path": image_path}


@app.post("/crop")
def crop_image(
    filename: str = Form(...),
    top: int = Form(...),
    left: int = Form(...),
    right: int = Form(...),
    bottom: int = Form(...)
):
    image_path = os.path.join(OUTPUT_DIR, filename.replace(".pdf", ".jpg"))
    if not os.path.exists(image_path):
        return {"error": "이미지를 찾을 수 없습니다."}

    # 이미지 열기
    image = Image.open(image_path)
    width, height = image.size

    # crop box 계산
    crop_box = (left, top, width - right, height - bottom)
    cropped_image = image.crop(crop_box)

    # 저장
    cropped_filename = filename.replace(".pdf", "_cropped.jpg")
    cropped_path = os.path.join(OUTPUT_DIR, cropped_filename)
    cropped_image.save(cropped_path, "JPEG")

    return {"cropped_image_path": cropped_path, "message": "이미지 crop 완료"}

@app.get("/download")
def download_image(filename: str):
    file_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(file_path):
        return {"error": "파일이 존재하지 않습니다."}
    
    return FileResponse(
        path=file_path,
        media_type="image/jpeg",
        filename=filename
    )

@app.post("/multi_convert")
def convert_all_pages(filename: str = Form(...)):
    pdf_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(pdf_path):
        return {"error": "PDF 파일을 찾을 수 없습니다."}

    # PDF → 이미지 변환 (전체 페이지)
    images = convert_from_path(pdf_path, dpi=200)

    # 메모리에 zip 생성
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        for i, img in enumerate(images):
            img_io = io.BytesIO()
            img.save(img_io, "JPEG")
            img_io.seek(0)
            zipf.writestr(f"page_{i+1}.jpg", img_io.read())

    zip_buffer.seek(0)

    safe_filename = os.path.basename(filename).replace('.pdf', '').replace(' ', '_')
    zip_filename = f"{safe_filename}_pages.zip"

    return StreamingResponse(zip_buffer, media_type="application/zip", headers={
        "Content-Disposition": f"attachment; filename={zip_filename}"
    })

@app.post("/multi_crop_convert")
def multi_page_crop_convert(
    filename: str = Form(...),
    top: int = Form(...),
    left: int = Form(...),
    right: int = Form(...),
    bottom: int = Form(...)
):
    pdf_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(pdf_path):
        return {"error": "PDF 파일을 찾을 수 없습니다."}

    images = convert_from_path(pdf_path, dpi=200)

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        for i, img in enumerate(images):
            width, height = img.size
            crop_box = (
                left,
                top,
                width - right,
                height - bottom
            )
            cropped_img = img.crop(crop_box)

            img_io = io.BytesIO()
            cropped_img.save(img_io, "JPEG")
            img_io.seek(0)
            zipf.writestr(f"cropped_page_{i+1}.jpg", img_io.read())

    zip_buffer.seek(0)

    safe_filename = os.path.basename(filename).replace('.pdf', '').replace(' ', '_')
    zip_filename = f"{safe_filename}_cropped_pages.zip"

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={zip_filename}"}
    )

def cleanup_old_files(target_dir: str, max_age_seconds: int = 600):
    now = time.time()
    deleted = []

    for fname in os.listdir(target_dir):
        fpath = os.path.join(target_dir, fname)
        if os.path.isfile(fpath):
            mtime = os.path.getmtime(fpath)
            if now - mtime > max_age_seconds:
                os.remove(fpath)
                deleted.append(fname)
    
    if deleted:
        print(f"[자동삭제] {target_dir} → 삭제된 파일들: {deleted}")


# 🔁 1분마다 실행되도록 설정
scheduler = BackgroundScheduler()
scheduler.add_job(lambda: cleanup_old_files("./uploads"), "interval", minutes=1)
scheduler.add_job(lambda: cleanup_old_files("./output_images"), "interval", minutes=1)
scheduler.start()

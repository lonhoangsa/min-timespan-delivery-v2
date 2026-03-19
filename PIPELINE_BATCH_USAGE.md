# 🚀 Pipeline Batch Mode - Hướng Dẫn Sử Dụng

## 📋 Tổng Quan

Pipeline đã được cấu hình để **tự động chạy theo batch mode** (run-batch.yml):
- ✅ Gen 4000 files
- ✅ Push lên GitHub
- ✅ **Tự động chia thành 4 batches** (1000 files/batch)
- ✅ Trigger tất cả 4 batches song song
- ✅ Wait tất cả hoàn thành
- ✅ Download + Lưu data + CSV kết quả

---

## 🎯 Cách Sử Dụng

### **Option 1: Full Pipeline (Khuyến Khích)**

Gen data → Push → Run 4 batches → Download:

```powershell
python scripts/pipeline.py --name Lan5 -y
```

**Điều gì sẽ xảy ra:**
1. Gen 4000 files vào `problems/data/`
2. Push lên GitHub
3. Tính toán batches: 4000 / 1000 = 4 batches
4. Trigger batch 1, 2, 3, 4 (tuần tự)
5. Wait mỗi batch hoàn thành (~2 giờ/batch)
6. Move data từ `problems/data/` → `E:\TTTH\train_data\Lan5`
7. Download CSV summary từ GitHub → `E:\TTTH\train_data\Baseline\Lan5`

**Output:**
- Data files: `E:\TTTH\train_data\Lan5\*.txt` (4000 files)
- Summary: `E:\TTTH\train_data\Baseline\Lan5\summary-batch-{1,2,3,4}.csv`
- Log: `logs/pipeline_Lan5_*.log`

---

### **Option 2: Custom Batch Size**

Nếu muốn 500 files/batch (= 8 batches):

```powershell
python scripts/pipeline.py --name Lan6 --files-per-batch 500 -y
```

**Điều gì sẽ xảy ra:**
1. Gen 4000 files
2. Tính: 4000 / 500 = 8 batches
3. Trigger batch 1, 2, 3, 4, 5, 6, 7, 8

---

### **Option 3: Chỉ Gen + Push (Không Chạy Workflow)**

```powershell
python scripts/pipeline.py --name Lan7 --only-generate -y
```

**Điều gì sẽ xảy ra:**
- Gen 4000 files
- Push lên GitHub
- **Không trigger workflow**
- Dữ liệu vẫn ở `problems/data/`

👉 Dùng khi bạn muốn gen data trước, sau đó trigger workflow thủ công từ GitHub.

---

### **Option 4: Chỉ Download Summary (sau khi batches chạy xong)**

```powershell
python scripts/pipeline.py --name Lan7 --only-download --run-id 123456 456789 789012
```

**Điều gì sẽ xảy ra:**
- Download từ 3 run IDs
- Move data (nếu có)
- Download summary

👉 Dùng nếu bạn chạy batches từ GitHub UI (thay vì pipeline) và muốn download kết quả.

---

### **Option 5: Manual Batch Selection**

Trigger chỉ batch 1 và 2:

```powershell
python scripts/pipeline.py --name Lan8 --batches 1 2 -y
```

**Điều gì sẽ xảy ra:**
- Gen 4000 files
- Push
- Trigger **chỉ batch 1, 2** (bỏ qua batch 3, 4)

---

### **Option 6: Sử Dụng run.yml Cũ (Không Batch)**

Nếu muốn chạy toàn bộ files cùng lúc (như cũ):

```powershell
python scripts/pipeline.py --name Lan9 --workflow run -y
```

**⚠️ Cảnh báo:** Có nguy cơ timeout (6 giờ) nếu files > 3000

---

## 📊 So Sánh Thời Gian

| Scenario | Method | Thời gian | Timeout Risk |
|----------|--------|----------|-------------|
| 4000 files | `run.yml` | ~6 giờ | ⚠️ CẬP TIMEOUT |
| 4000 files | `run-batch.yml` (4 batch) | ~8 giờ (sequential) | ✅ OK |
| 4000 files | `run-batch.yml` (parallel) | ~2 giờ | ✅ OK |

---

## 🔍 Thư Mục Output

### **Data & Summary:**

```
E:\TTTH\train_data\
├── Lan5/                          # Gen data
│   ├── 20.15.0.txt
│   ├── 20.15.1.txt
│   └── ... (4000 files)
└── Baseline/
    └── Lan5/                      # Summary results
        ├── summary-batch-1.csv
        ├── summary-batch-2.csv
        ├── summary-batch-3.csv
        ├── summary-batch-4.csv
        ├── summary-batch-1.db
        ├── summary-batch-2.db
        ├── summary-batch-3.db
        └── summary-batch-4.db
```

### **Logs:**

```
logs/
└── pipeline_Lan5_20260319_210015.log
```

---

## 🛠️ Troubleshooting

### **Lỗi: "gh CLI chua duoc cai dat!"**

```powershell
winget install --id GitHub.cli
gh auth login
```

### **Lỗi: "Khong the tinh batch count!"**

→ Không có files trong `problems/data/`. Dùng `--only-generate` trước.

### **Muốn hủy pipeline đang chạy:**

```powershell
Ctrl+C
```

Các batches đang chạy trên GitHub Actions **sẽ tiếp tục** (không tự động hủy).

---

## 📝 Ví Dụ Thực Tế

### **Workflow 1: Gen + Run Batch Đầy Đủ**

```powershell
# Bước 1: Gen + Push + Trigger 4 batches
python scripts/pipeline.py --name Lan5 -y

# → Chạy ~8 giờ
# → Output: 4000 files + 4 CSV summaries
```

### **Workflow 2: Gen Trước, Trigger Sau**

```powershell
# Bước 1: Gen + Push (không trigger)
python scripts/pipeline.py --name Lan6 --only-generate -y

# → Dữ liệu ở problems/data/
# → Có thể trigger thủ công từ GitHub UI

# Bước 2 (sau khi batch chạy xong): Download
python scripts/pipeline.py --name Lan6 --only-download --run-id 12345678
```

### **Workflow 3: Chạy Batch Custom**

```powershell
# Gen 8000 files thành 8 batches (1000 files/batch)
python scripts/pipeline.py --name Lan7 --files-per-batch 1000 -y

# → 4000 files sinh ra
# → Chia thành 4 batches (vì gen_instance.py tạo 4000)
```

---

## ✅ Checklist Trước Chạy

- [ ] GitHub CLI đã cài (`gh --version`)
- [ ] Đã login GitHub (`gh auth status`)
- [ ] Git configured + push access
- [ ] Đủ dung lượng ổ cứng (~500MB cho 4000 files + results)
- [ ] Kết nối internet ổn định (upload ~500MB lên GitHub)

---

## 🚀 Quick Start

```powershell
cd E:\TTTH\attentionV2\min-timespan-delivery-v2

# Run pipeline: Gen 4000 files → 4 batches → Download
python scripts/pipeline.py --name Lan5 -y
```

**Done!** 🎉

---

## 📞 Support

- Logs: Xem `logs/pipeline_*.log`
- GitHub Actions: https://github.com/PakerB/min-timespan-delivery-v2/actions
- Batches status: GitHub Actions → "Run algorithm (Batched)"

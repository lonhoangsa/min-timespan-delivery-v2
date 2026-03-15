"""
Script quản lý files txt trong folder data
- Option 1: Xóa tất cả files txt
- Option 2: Chuyển files txt sang thư mục backup
"""

import os
import shutil
from pathlib import Path


def count_txt_files(data_folder):
    """Đếm số file .txt trong folder"""
    return len(list(data_folder.glob("*.txt")))


def delete_all_txt_files(data_folder):
    """Xóa tất cả file .txt trong folder data"""
    txt_files = list(data_folder.glob("*.txt"))
    count = len(txt_files)
    
    if count == 0:
        print("❌ Không có file txt nào để xóa!")
        return
    
    print(f"\n⚠️  CẢNH BÁO: Sắp xóa {count} files txt!")
    confirm = input("Bạn có chắc chắn muốn xóa? (y/n): ").strip().lower()
    
    if confirm == 'y':
        deleted = 0
        for file in txt_files:
            try:
                file.unlink()
                deleted += 1
            except Exception as e:
                print(f"❌ Lỗi khi xóa {file.name}: {e}")
        
        print(f"✅ Đã xóa {deleted}/{count} files!")
    else:
        print("❌ Hủy thao tác xóa.")


def move_all_txt_files(data_folder, target_folder):
    """Chuyển tất cả file .txt sang thư mục khác"""
    txt_files = list(data_folder.glob("*.txt"))
    count = len(txt_files)
    
    if count == 0:
        print("❌ Không có file txt nào để chuyển!")
        return
    
    # Tạo thư mục đích nếu chưa có
    target_path = Path(target_folder)
    target_path.mkdir(parents=True, exist_ok=True)
    
    print(f"\n📦 Sắp chuyển {count} files txt")
    print(f"   Từ: {data_folder}")
    print(f"   Đến: {target_folder}")
    
    confirm = input("Bạn có chắc chắn muốn chuyển? (y/n): ").strip().lower()
    
    if confirm == 'y':
        moved = 0
        for file in txt_files:
            try:
                target_file = target_path / file.name
                
                # Nếu file đã tồn tại ở đích, hỏi có ghi đè không
                if target_file.exists():
                    print(f"⚠️  {file.name} đã tồn tại ở đích")
                    overwrite = input(f"   Ghi đè? (y/n/a=all): ").strip().lower()
                    if overwrite == 'n':
                        continue
                    elif overwrite == 'a':
                        # Ghi đè tất cả files còn lại
                        pass
                
                shutil.move(str(file), str(target_file))
                moved += 1
                
                if moved % 100 == 0:
                    print(f"   Đã chuyển {moved}/{count} files...")
                    
            except Exception as e:
                print(f"❌ Lỗi khi chuyển {file.name}: {e}")
        
        print(f"✅ Đã chuyển {moved}/{count} files sang {target_folder}!")
    else:
        print("❌ Hủy thao tác chuyển file.")


def main():
    # Đường dẫn folder data (cùng thư mục với script này)
    script_dir = Path(__file__).parent
    data_folder = script_dir / "data"
    
    # Đường dẫn thư mục đích
    target_folder = r"E:\TTTH\attentionV2\train_data\Lan8"
    
    # Kiểm tra folder data có tồn tại không
    if not data_folder.exists():
        print(f"❌ Folder data không tồn tại: {data_folder}")
        return
    
    # Đếm số file txt
    txt_count = count_txt_files(data_folder)
    
    # Hiển thị menu
    print("=" * 60)
    print("         QUẢN LÝ FILES TXT TRONG FOLDER DATA")
    print("=" * 60)
    print(f"📁 Folder data: {data_folder}")
    print(f"📊 Số file txt hiện tại: {txt_count}")
    print("=" * 60)
    print()
    print("Chọn thao tác:")
    print("  [1] Xóa tất cả files txt trong folder data")
    print(f"  [2] Chuyển tất cả files txt sang: {target_folder}")
    print("  [0] Thoát")
    print()
    
    try:
        choice = input("Nhập lựa chọn (0/1/2): ").strip()
        
        if choice == "1":
            print("\n🗑️  === XÓA TẤT CẢ FILES TXT ===")
            delete_all_txt_files(data_folder)
            
        elif choice == "2":
            print("\n📦 === CHUYỂN TẤT CẢ FILES TXT ===")
            move_all_txt_files(data_folder, target_folder)
            
        elif choice == "0":
            print("👋 Thoát chương trình.")
            
        else:
            print("❌ Lựa chọn không hợp lệ! Vui lòng chọn 0, 1, hoặc 2.")
    
    except KeyboardInterrupt:
        print("\n\n❌ Đã hủy thao tác (Ctrl+C)")
    except Exception as e:
        print(f"\n❌ Lỗi: {e}")
    
    print("\n" + "=" * 60)
    print("Hoàn tất!")


if __name__ == "__main__":
    main()

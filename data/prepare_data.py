import pandas as pd

files = ['DrDoS_DNS.csv', 'Syn.csv', 'UDPLag.csv']
all_data = []

print("กำลังปรับสมดุลข้อมูล...")

# ส่วนหนึ่งของโค้ดใน prepare_data.py
for file in files:
    print(f"กำลังจัดการไฟล์: {file}")
    df = pd.read_csv(file, low_memory=False)
    
    # แยกข้อมูลปกติ (Benign) ออกมาทั้งหมดที่มีในไฟล์นั้น
    benign = df[df[' Label'] == 'BENIGN']
    
    # ปรับ n เป็น 10000 เพื่อดึงข้อมูลการโจมตีเพิ่มขึ้น
    # หมายเหตุ: ตรวจสอบว่าไฟล์นั้นมีข้อมูลถึง 10000 แถวไหม ถ้าไม่ถึงให้ใช้ทั้งหมดที่มี
    n_samples = min(10000, len(df[df[' Label'] != 'BENIGN']))
    attack = df[df[' Label'] != 'BENIGN'].sample(n=n_samples, random_state=42)
    
    all_data.append(benign)
    all_data.append(attack)

# รวมข้อมูล
final_df = pd.concat(all_data, ignore_index=True)

# ตรวจสอบจำนวนอีกครั้ง
print("\nสรุปจำนวนข้อมูลหลังปรับสมดุล:")
print(final_df[' Label'].value_counts())

# บันทึกไฟล์ใหม่
final_df.to_csv('balanced_sdn_dataset.csv', index=False)
print("\nสร้างไฟล์ balanced_sdn_dataset.csv สำเร็จ!")
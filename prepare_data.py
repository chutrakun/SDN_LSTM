"""
เตรียม dataset จาก CICIDS2019
ไฟล์ที่ต้องการ: DrDoS_DNS.csv, Syn.csv, UDPLag.csv
วางไฟล์เหล่านี้ใน ~/sdn-ml-security/data/
"""
import pandas as pd
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
OUT_FILE = os.path.join(DATA_DIR, 'balanced_sdn_dataset.csv')

files = {
    'DrDoS_DNS.csv': 10000,
    'Syn.csv':       10000,
    'UDPLag.csv':    10000,
}

all_data = []
print("กำลังปรับสมดุลข้อมูล...")

for fname, n_attack in files.items():
    fpath = os.path.join(DATA_DIR, fname)
    if not os.path.exists(fpath):
        print(f"⚠️  ไม่พบ {fpath} — ข้าม")
        continue

    print(f"  โหลด {fname}...")
    df = pd.read_csv(fpath, low_memory=False)
    df.columns = df.columns.str.strip()

    # แยก BENIGN และ Attack
    benign = df[df['Label'] == 'BENIGN']
    attack = df[df['Label'] != 'BENIGN']

    n_b = min(n_attack, len(benign))
    n_a = min(n_attack, len(attack))

    all_data.append(benign.sample(n=n_b, random_state=42))
    all_data.append(attack.sample(n=n_a, random_state=42))
    print(f"    BENIGN: {n_b} | Attack: {n_a} ({attack['Label'].unique()})")

final_df = pd.concat(all_data, ignore_index=True)
final_df = final_df.sample(frac=1, random_state=42).reset_index(drop=True)

print(f"\nสรุปจำนวนข้อมูล:")
print(final_df['Label'].value_counts())

final_df.to_csv(OUT_FILE, index=False)
print(f"\n✅ บันทึกที่ {OUT_FILE}")

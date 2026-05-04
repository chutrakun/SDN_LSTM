"""
Train LSTM สำหรับ CICIDS2019
Classes: BENIGN, DrDoS_DNS, Syn, UDP-lag
"""
import pandas as pd
import numpy as np
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Dropout
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder, MinMaxScaler
from sklearn.metrics import classification_report
import joblib, os

BASE     = os.path.dirname(os.path.abspath(__file__))
DATA_PATH= os.path.join(BASE, '../data/balanced_sdn_dataset.csv')
MODEL_DIR= os.path.join(BASE, 'model')
os.makedirs(MODEL_DIR, exist_ok=True)

FEATURES = [
    'Destination Port', 'Protocol', 'Flow Duration',
    'Total Fwd Packets', 'Total Backward Packets',
    'Total Length of Fwd Packets', 'Total Length of Bwd Packets',
    'Flow Bytes/s', 'Flow Packets/s', 'Flow IAT Mean'
]

# ── 1. โหลด Dataset ──
print("📂 Loading dataset...")
df = pd.read_csv(DATA_PATH, low_memory=False)
df.columns = df.columns.str.strip()
print(f"Labels found: {df['Label'].unique()}")
print(df['Label'].value_counts())

# ── 2. Clean ──
X = df[FEATURES].copy()
y = df['Label'].copy()
X = X.replace([np.inf, -np.inf], np.nan)
X = X.fillna(X.mean())

# ── 3. Encode ──
le = LabelEncoder()
y_encoded = le.fit_transform(y)
joblib.dump(le, os.path.join(MODEL_DIR, 'label_encoder.pkl'))
print(f"\nClasses: {list(le.classes_)}")

# ── 4. Scale ──
scaler = MinMaxScaler()
X_scaled = scaler.fit_transform(X)
joblib.dump(scaler, os.path.join(MODEL_DIR, 'scaler.pkl'))

# ── 5. Reshape สำหรับ LSTM [samples, timesteps=1, features] ──
X_reshaped = X_scaled.reshape(X_scaled.shape[0], 1, X_scaled.shape[1])

# ── 6. Train/Test Split ──
X_train, X_test, y_train, y_test = train_test_split(
    X_reshaped, y_encoded, test_size=0.2, random_state=42, stratify=y_encoded)
print(f"\nTrain: {len(X_train)} | Test: {len(X_test)}")

# ── 7. LSTM Model ──
n_classes = len(le.classes_)
model = Sequential([
    LSTM(64, input_shape=(1, len(FEATURES)), return_sequences=True),
    Dropout(0.2),
    LSTM(32),
    Dropout(0.2),
    Dense(n_classes, activation='softmax')
])
model.compile(optimizer='adam',
              loss='sparse_categorical_crossentropy',
              metrics=['accuracy'])
model.summary()

# ── 8. Train ──
print("\n🔄 Training LSTM...")
model.fit(X_train, y_train,
          epochs=20, batch_size=64,
          validation_data=(X_test, y_test))

# ── 9. Evaluate ──
y_pred = np.argmax(model.predict(X_test, verbose=0), axis=1)
print("\n📊 Classification Report:")
print(classification_report(y_test, y_pred, target_names=le.classes_))

# ── 10. Save ──
save_path = os.path.join(MODEL_DIR, 'lstm_sdn_model.h5')
model.save(save_path)
print(f"\n💾 Model saved → {save_path}")
print(f"💾 Scaler saved → {MODEL_DIR}/scaler.pkl")
print(f"💾 LabelEncoder saved → {MODEL_DIR}/label_encoder.pkl")
